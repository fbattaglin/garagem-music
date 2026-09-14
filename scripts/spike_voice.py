"""Asks how long a spoken cue takes to reach the band, before anything is built for it.

    uv run python scripts/spike_voice.py            # terminal 1: the listener, and the command
    <the printed claude command>                    # terminal 2: speak to the band
    uv run python scripts/spike_voice.py --report   # afterwards: what arrived, and how fast

Stage 4 of Phase 5 opens with a spike, as the MiniLab plan did (`phase-4-findings.md` §7). The
exit criterion is a session driven only by the MiniLab and by voice. Claude Code already
dictates (`/voice`, with Portuguese), and it already talks to MCP servers over HTTP, so the
voice path is the conductor's own Claude Code session. Nothing is built into GARAGEM until
this says what that path costs.

**What it measures, from two clocks that are not a stopwatch:**
- the moment Fabiano's spoken prompt was submitted, from the conductor session's own transcript
  (`--session-id` is fixed in the printed command, so the file can be found);
- the moment the tool call reached this listener, from its own log.

The difference is the model's turn and the MCP hop. Transcription is live, before submission,
so what it leaves out is the speaking itself.

**The listener is a minimal MCP server over HTTP, on 127.0.0.1 only, from the standard
library.** It implements the four JSON-RPC methods a tool call needs (`initialize`, `ping`,
`tools/list`, `tools/call`) and answers notifications with 202. Its tools are the ones Stage 4
would give the band: `next_bridge`, `end_song`, `set_tension`, `set_density`, `keep`, `veto` and
`status`. **They change nothing.** Each call is logged with its arguments and the time it
arrived, to `bench/spike-voice.jsonl`. No new dependency: whether GARAGEM needs the `mcp`
package is one of the things this answers.

**The conductor session is locked down.** `--restricted` removes the tools that run commands,
`--strict-mcp-config` loads only this listener, and `--allowedTools` pre-approves its tools, so no
permission prompt ever needs the keyboard. It uses the model named by `--model` (Haiku by
default, the fastest measured), dictates in Portuguese, and records on a tap of Space.

**Reading the transcript is best effort.** It is Claude Code's own file, and its format is not
a published interface. If it cannot be read, the report says so and gives the listener's log.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "bench" / "spike-voice.jsonl"
DEFAULT_PORT: Final = 8765
HOST: Final = "127.0.0.1"
PATH: Final = "/mcp"
SERVER_NAME: Final = "garagem"
TRANSCRIPTS = Path.home() / ".claude" / "projects"

PARSE_ERROR: Final = -32700
METHOD_NOT_FOUND: Final = -32601
INVALID_PARAMS: Final = -32602

NO_ARGUMENTS: Final[dict[str, object]] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
A_LEVEL: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "level": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "0 is the knob at its left stop, 0.5 the song as planned, 1 its right",
        }
    },
    "required": ["level"],
    "additionalProperties": False,
}

TOOLS: Final[tuple[dict[str, object], ...]] = (
    {
        "name": "next_bridge",
        "description": "The next section that can still change becomes a bridge.",
        "inputSchema": NO_ARGUMENTS,
    },
    {
        "name": "end_song",
        "description": "The section playing finishes, then the outro and the final chord.",
        "inputSchema": NO_ARGUMENTS,
    },
    {
        "name": "set_tension",
        "description": "Harder fills, walking bass and more lift, from the next section on.",
        "inputSchema": A_LEVEL,
    },
    {
        "name": "set_density",
        "description": "Sparser or busier grooves, from the next section on.",
        "inputSchema": A_LEVEL,
    },
    {
        "name": "keep",
        "description": "Keep the section that is playing: the setlist pins its take.",
        "inputSchema": NO_ARGUMENTS,
    },
    {
        "name": "veto",
        "description": "Veto the section that is playing: the setlist retires its take.",
        "inputSchema": NO_ARGUMENTS,
    },
    {
        "name": "status",
        "description": "What is playing and what comes next. Changes nothing.",
        "inputSchema": NO_ARGUMENTS,
    },
)
TOOL_NAMES: Final = frozenset(str(tool["name"]) for tool in TOOLS)

CONDUCTOR_PROMPT: Final = """You are the conductor's voice for GARAGEM, a band playing live.
The person speaks Portuguese, in short phrases, while the music plays. Map each phrase to one
tool call from the garagem server at once, and never ask a question: the music does not wait.
"ponte" or "próxima ponte" is next_bridge; "termina", "acaba" or "final" is end_song;
"mais/menos tensão" moves set_tension up or down by 0.25 from where you last set it, starting
at 0.5, and a number or "máximo"/"mínimo" sets it outright; "mais/menos denso", "mais cheio" or
"mais vazio" does the same with set_density; "guarda", "gostei" or "mantém" is keep; "veta",
"não gostei" or "tira" is veto; "o que está tocando" is status. If a phrase asks for two things,
make both calls. If it asks for nothing you have a tool for, call status. Reply in at most five
words of Portuguese."""


# ------------------------------------------------------------------------------ JSON-RPC


def now() -> str:
    return datetime.now(UTC).isoformat()


def handle(
    message: dict[str, Any], record: Callable[[str, dict[str, Any]], None]
) -> dict[str, Any] | None:
    """One JSON-RPC message in, its response out, or `None` for a notification."""
    method = message.get("method")
    ident = message.get("id")
    if ident is None:
        return None
    if method == "initialize":
        params = message.get("params") or {}
        return _result(
            ident,
            {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": "spike"},
            },
        )
    if method == "ping":
        return _result(ident, {})
    if method == "tools/list":
        return _result(ident, {"tools": list(TOOLS)})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in TOOL_NAMES:
            return _error(ident, INVALID_PARAMS, f"no tool named {name!r}")
        record(str(name), dict(arguments))
        text = "status: the spike plays nothing" if name == "status" else f"{name}: heard"
        return _result(ident, {"content": [{"type": "text", "text": text}], "isError": False})
    return _error(ident, METHOD_NOT_FOUND, f"no method {method!r}")


def _result(ident: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def _error(ident: object, code: int, text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": text}}


def local_origin(origin: str | None) -> bool:
    """MCP's advice against DNS rebinding: a browser page elsewhere may not drive the band."""
    if origin is None:
        return True
    return origin.startswith(("http://127.0.0.1", "http://localhost"))


def serve(port: int, log: Path) -> None:
    def record(name: str, arguments: dict[str, Any]) -> None:
        received_at = now()
        row: dict[str, object] = {"received_at": received_at, "tool": name, "arguments": arguments}
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle_:
            handle_.write(json.dumps(row) + "\n")
        sys.stderr.write(f"  {received_at[11:23]}  {name} {arguments or ''}\n")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != PATH or not local_origin(self.headers.get("Origin")):
                self.send_error(403 if self.path == PATH else 404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            try:
                message = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                self._json(400, _error(None, PARSE_ERROR, "not JSON"))
                return
            response = handle(message, record) if isinstance(message, dict) else None
            if response is None:
                self.send_response(202)
                self.end_headers()
                return
            self._json(200, response)

        def do_GET(self) -> None:
            # No server-initiated stream: the streamable HTTP transport allows refusing it.
            self.send_error(405)

        def _json(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((HOST, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nstopped. uv run python scripts/spike_voice.py --report\n")
    finally:
        server.server_close()


# ----------------------------------------------------------------------- the conductor


def conductor_command(port: int, session: str, model: str) -> list[str]:
    settings = {"language": "portuguese", "voice": {"enabled": True, "mode": "tap"}}
    servers = {"mcpServers": {SERVER_NAME: {"type": "http", "url": f"http://{HOST}:{port}{PATH}"}}}
    return [
        "claude",
        "--session-id",
        session,
        "--model",
        model,
        "--restricted",
        "--strict-mcp-config",
        "--mcp-config",
        json.dumps(servers),
        "--settings",
        json.dumps(settings),
        "--allowedTools",
        f"mcp__{SERVER_NAME}",
        "--append-system-prompt",
        CONDUCTOR_PROMPT,
    ]


def shell_quote(argv: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(part) for part in argv)


# ------------------------------------------------------------------------------ report


def parse_time(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def prompts_of(transcript: Path) -> list[tuple[datetime, str]]:
    """Each prompt the person submitted, with its time. Tool results are not prompts."""
    out: list[tuple[datetime, str]] = []
    for line in transcript.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") != "user" or row.get("isMeta") or "timestamp" not in row:
            continue
        content = (row.get("message") or {}).get("content")
        if isinstance(content, str) and content.strip() and not content.startswith("<"):
            out.append((parse_time(row["timestamp"]), content.strip()))
    return out


def report(log: Path, session: str | None) -> str:
    if not log.exists():
        return f"{log} does not exist: no tool call reached the listener\n"
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    lines = [f"{len(calls)} tool call(s) reached the listener"]
    prompts: list[tuple[datetime, str]] = []
    if session is not None:
        found = list(TRANSCRIPTS.glob(f"*/{session}.jsonl"))
        if found:
            prompts = prompts_of(found[0])
            lines.append(f"{len(prompts)} spoken prompt(s) in the conductor's transcript")
        else:
            lines.append(f"no transcript for session {session}: latency cannot be read")
    delays: list[float] = []
    for call in calls:
        arrived = parse_time(call["received_at"])
        before = [(at, text) for at, text in prompts if at <= arrived]
        if before:
            at, text = before[-1]
            delay = (arrived - at).total_seconds()
            delays.append(delay)
            lines.append(
                f"  {delay:5.1f} s  {call['tool']:<12} {call['arguments'] or ''}  <- {text!r}"
            )
        else:
            lines.append(f"     -     {call['tool']:<12} {call['arguments'] or ''}")
    if delays:
        ordered = sorted(delays)
        middle = ordered[len(ordered) // 2]
        lines.append(
            f"prompt submitted to tool call: median {middle:.1f} s, "
            f"fastest {ordered[0]:.1f} s, slowest {ordered[-1]:.1f} s"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--model", default="haiku", help="the conductor session's model")
    parser.add_argument("--report", action="store_true", help="read what arrived, and how fast")
    parser.add_argument("--session-id", help="the conductor session, for --report")
    args = parser.parse_args()

    session_file = args.log.with_suffix(".session")
    if args.report:
        session = args.session_id or (
            session_file.read_text(encoding="utf-8").strip() if session_file.exists() else None
        )
        sys.stderr.write(report(args.log, session))
        return 0

    session = str(uuid.uuid4())
    args.log.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(session + "\n", encoding="utf-8")
    sys.stderr.write(
        f"listening on http://{HOST}:{args.port}{PATH}; tool calls go to {args.log}\n\n"
        "In a second terminal, from this folder, start the conductor:\n\n"
        f"{shell_quote(conductor_command(args.port, session, args.model))}\n\n"
        "Then tap Space, speak a cue in Portuguese, and tap Space again to send it.\n"
        "Ctrl-C here when done.\n\n"
    )
    serve(args.port, args.log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
