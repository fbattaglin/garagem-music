"""Keeps and vetoes, read back from an event log with the take each one fell on (ADR-024).

The scheduler logs a mark with what it knows on the bar loop: the section, who wrote it, its
seed. It does not have the take's text, and it must not serialise one there (invariant 3). The
producer already logged the text when it offered the section (`section_parsed`), so the take is
joined here, offline, from the order of the log:

- the last `section_parsed` for a section is the take the buffer held for it;
- `section_generated` from the buffer means that take was written; a `not_in_buffer` fallback
  means the floor's was; a jump's candidate is always the floor's;
- a mark on a section names the take last written for it.

**Runs are separated by `session_ended`**, and a run played from a setlist names it in
`setlist_loaded`. A mark in a run with no setlist is still read, for the counts per author the
phase gate reports, and has no setlist to curate.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from garagem.obs.events import Event

MODEL = "model"
FLOOR = "floor"


@dataclass(frozen=True, slots=True)
class Mark:
    """One keep or veto: where it fell, who wrote that, and the take's text if a model did."""

    mark: str
    section: int
    name: str
    author: str
    seed: int
    setlist: str | None
    song: int | None
    dsl: str | None


def marks(events: Sequence[Event]) -> list[Mark]:
    """Every mark in the log, in the order struck, each joined to the take it fell on."""
    out: list[Mark] = []
    setlist: str | None = None
    song: int | None = None
    parsed: dict[int, str] = {}
    written: dict[int, str | None] = {}
    for event in events:
        detail = event.detail
        if event.kind == "setlist_loaded":
            setlist, song = str(detail["setlist"]), int(str(detail["song"]))
        elif event.kind == "section_parsed" and "dsl" in detail:
            parsed[int(str(detail["section"]))] = str(detail["dsl"])
        elif event.kind == "section_generated" and detail.get("source") == "buffer":
            index = int(str(detail["section"]))
            written[index] = parsed.get(index)
        elif (event.kind == "fallback" and detail.get("reason") == "not_in_buffer") or (
            event.kind == "cue_applied" and detail.get("cue") == "chorus_now"
        ):
            written[int(str(detail["section"]))] = None
        elif event.kind == "take_marked":
            index = int(str(detail["section"]))
            author = str(detail["author"])
            out.append(
                Mark(
                    mark=str(detail["mark"]),
                    section=index,
                    name=str(detail["name"]),
                    author=author,
                    seed=int(str(detail["seed"])),
                    setlist=setlist,
                    song=song,
                    dsl=written.get(index) if author == MODEL else None,
                )
            )
        elif event.kind == "session_ended":
            setlist, song = None, None
            parsed.clear()
            written.clear()
    return out


def per_author(found: Sequence[Mark]) -> dict[str, Counter[str]]:
    """Keeps and vetoes counted by who wrote what they fell on. Telemetry, never a target."""
    counts: dict[str, Counter[str]] = {MODEL: Counter(), FLOOR: Counter()}
    for mark in found:
        counts.setdefault(mark.author, Counter())[mark.mark] += 1
    return counts
