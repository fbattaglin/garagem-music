"""Cassettes: record a real interaction once, replay it forever.

A test in the default suite that makes a network call is a bug. Cassettes are how the
real adapter gets into CI: the interaction is recorded once, by hand, with an API key;
`CassetteProvider` then replays it — offline, deterministic and diffable.

Format: JSONL. The first line is the header, the following ones are the stream events,
one per line, in the order they arrived. One file is one interaction.

**Cassettes store content, not time.** Latency is measured against the real link by the
Phase 0 rig (ADR §4.2); a timing recorded here would only age into a lie.

The request is checked against the recording by fingerprint. When the prompt changes,
the cassette stops matching — on purpose. That is the drift alarm between what the test
thinks it is sending and what was recorded.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from garagem.llm.errors import CassetteMismatchError, CassetteMissingError
from garagem.llm.port import EVENT_ADAPTER, LLMProvider, Request, StreamEvent

FORMAT = 1


class CassetteHeader(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cassette: int = FORMAT
    provider: str
    model: str
    fingerprint: str
    note: str = ""


async def record(
    provider: LLMProvider,
    request: Request,
    path: Path,
    *,
    note: str = "",
    name: str | None = None,
) -> list[StreamEvent]:
    """Drain `provider`'s stream, write it to `path` and return what went through.

    Overwrites. Run this by hand against the real provider; never in CI.

    `name` overrides what goes in the header. The recorder wraps the adapter in a
    `GuardedProvider`, and the header should say which provider produced the bytes,
    not which decorator they passed through on the way out.
    """
    events = [event async for event in provider.stream(request)]
    header = CassetteHeader(
        provider=name or provider.name,
        model=request.model,
        fingerprint=request.fingerprint(),
        note=note,
    )
    lines = [header.model_dump_json()]
    lines += [EVENT_ADAPTER.dump_json(event).decode("utf-8") for event in events]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return events


class CassetteProvider:
    """Replays a recorded cassette. Never touches the network."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._header, self._events = _load(path)

    @property
    def name(self) -> str:
        return f"cassette:{self._header.provider}"

    @property
    def header(self) -> CassetteHeader:
        return self._header

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        current = request.fingerprint()
        if current != self._header.fingerprint:
            raise CassetteMismatchError(
                f"{self._path}: recorded for {self._header.fingerprint}, "
                f"got {current}. The prompt changed — re-record the cassette."
            )
        for event in self._events:
            yield event


def _load(path: Path) -> tuple[CassetteHeader, list[StreamEvent]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CassetteMissingError(f"missing cassette: {path}") from exc

    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        raise CassetteMismatchError(f"empty cassette: {path}")

    header = CassetteHeader.model_validate_json(lines[0])
    if header.cassette != FORMAT:
        raise CassetteMismatchError(f"{path}: format {header.cassette}, expected {FORMAT}")
    events = [EVENT_ADAPTER.validate_json(line) for line in lines[1:]]
    return header, events
