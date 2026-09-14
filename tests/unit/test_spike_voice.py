"""The voice spike's listener and report, with no socket and no Claude Code session.

The first real exchange is Fabiano's run. What can be held here is the protocol the listener
answers, that its tools change nothing but a log line, how the conductor session is locked
down, and how the latency is read from two logs.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "spike_voice.py"
    spec = importlib.util.spec_from_file_location("spike_voice", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["spike_voice"] = module
    spec.loader.exec_module(module)
    return module


spike = _load()


def answered(message: dict[str, Any]) -> tuple[dict[str, Any] | None, list[tuple[str, Any]]]:
    calls: list[tuple[str, Any]] = []
    response = spike.handle(message, lambda name, arguments: calls.append((name, arguments)))
    return response, calls


# ------------------------------------------------------------------------------ protocol


def test_initialize_echoes_the_clients_protocol_and_offers_tools() -> None:
    response, _ = answered(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "X"}}
    )
    assert response is not None
    assert response["result"]["protocolVersion"] == "X"
    assert "tools" in response["result"]["capabilities"]


def test_a_notification_gets_no_response() -> None:
    response, _ = answered({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert response is None


def test_the_tools_are_the_ones_stage_4_would_give_the_band() -> None:
    response, _ = answered({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert response is not None
    names = [tool["name"] for tool in response["result"]["tools"]]
    assert names == [
        "next_bridge",
        "end_song",
        "set_tension",
        "set_density",
        "keep",
        "veto",
        "status",
    ]
    assert all(tool["inputSchema"]["type"] == "object" for tool in response["result"]["tools"])


def test_a_tool_call_is_recorded_and_changes_nothing_else() -> None:
    response, calls = answered(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "set_tension", "arguments": {"level": 0.75}},
        }
    )
    assert calls == [("set_tension", {"level": 0.75})]
    assert response is not None
    assert response["result"]["isError"] is False


def test_an_unknown_tool_or_method_is_an_error_and_records_nothing() -> None:
    tool, calls = answered(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "delete_live"}}
    )
    method, _ = answered({"jsonrpc": "2.0", "id": 5, "method": "resources/list"})
    assert tool is not None and tool["error"]["code"] == spike.INVALID_PARAMS
    assert method is not None and method["error"]["code"] == spike.METHOD_NOT_FOUND
    assert calls == []


def test_only_a_local_page_may_call_the_listener() -> None:
    assert spike.local_origin(None)
    assert spike.local_origin("http://localhost:3000")
    assert not spike.local_origin("http://evil.example")


# ------------------------------------------------------------------------ the conductor


def test_the_conductor_session_is_locked_down() -> None:
    argv = spike.conductor_command(8765, "00000000-0000-0000-0000-000000000000", "haiku")
    assert "--restricted" in argv
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--allowedTools") + 1] == "mcp__garagem"
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert settings["language"] == "portuguese"
    assert settings["voice"] == {"enabled": True, "mode": "tap"}
    servers = json.loads(argv[argv.index("--mcp-config") + 1])
    assert servers["mcpServers"]["garagem"]["url"] == "http://127.0.0.1:8765/mcp"


# ------------------------------------------------------------------------------- report


def test_latency_is_read_from_the_prompt_to_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = "11111111-1111-1111-1111-111111111111"
    transcripts = tmp_path / "projects" / "-some-project"
    transcripts.mkdir(parents=True)
    rows = [
        {"type": "user", "timestamp": "2026-09-13T20:00:00.000Z", "message": {"content": "ponte"}},
        {
            "type": "user",
            "timestamp": "2026-09-13T20:00:03.000Z",
            "message": {"content": [{"type": "tool_result", "content": "heard"}]},
        },
        {"type": "user", "timestamp": "2026-09-13T20:00:10.000Z", "message": {"content": "veta"}},
    ]
    (transcripts / f"{session}.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    log = tmp_path / "spike.jsonl"
    log.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {
                    "received_at": "2026-09-13T20:00:02.500+00:00",
                    "tool": "next_bridge",
                    "arguments": {},
                },
                {"received_at": "2026-09-13T20:00:14.000+00:00", "tool": "veto", "arguments": {}},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(spike, "TRANSCRIPTS", tmp_path / "projects")
    text = spike.report(log, session)
    assert "2 tool call(s) reached the listener" in text
    assert "2.5 s  next_bridge" in text
    assert "4.0 s  veto" in text
    assert "median 4.0 s, fastest 2.5 s, slowest 4.0 s" in text
