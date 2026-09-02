"""The event log: musical time, known kinds, and a read that refuses to guess.

The load path is the one worth being strict about. A log with an unreadable line is a
log that cannot be trusted to be complete, and Phase 2's "zero glitches" criterion is
read *out of this file* — quietly skipping a bad line would turn that claim into a
statement about the lines that happened to parse.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from garagem.obs import (
    KINDS,
    Event,
    EventLog,
    MalformedEventError,
    append_events,
    load_events,
    rate_of,
)


def an_event(**extra: object) -> Event:
    base: dict[str, object] = {"at_beats": 0.0, "kind": "scene_fired"}
    return Event.model_validate(base | extra)


# -------------------------------------------------------------------------------- events


def test_an_event_is_stamped_in_beats_not_seconds() -> None:
    """So the log can be replayed against the music rather than against a stopwatch."""
    assert an_event(at_beats=37.5).at_beats == 37.5


def test_an_event_needs_its_beat() -> None:
    with pytest.raises(ValidationError):
        Event.model_validate({"kind": "scene_fired"})


def test_an_unknown_kind_is_refused_at_construction() -> None:
    """A typo would be an event that is silently never counted."""
    with pytest.raises(ValidationError, match="unknown event kind"):
        an_event(kind="section_writen")


@pytest.mark.parametrize("kind", KINDS)
def test_every_declared_kind_can_be_recorded(kind: str) -> None:
    assert an_event(kind=kind).kind == kind


def test_an_event_is_frozen() -> None:
    with pytest.raises(ValidationError):
        an_event().at_beats = 1.0


# ----------------------------------------------------------------------------------- log


def test_recording_writes_nothing_until_it_is_flushed() -> None:
    """`realtime.md` forbids a synchronous disk write inside the bar loop."""
    log = EventLog(None)
    log.record("scene_fired", 0.0, scene=1)
    assert len(log) == 1


def test_a_flush_writes_only_what_is_new(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    log = EventLog(path)
    log.record("section_generated", 0.0, seed=7)
    assert log.flush() == 1
    assert log.flush() == 0
    log.record("scene_fired", 4.0, scene=1)
    assert log.flush() == 1
    assert len(load_events(path)) == 2


def test_events_carry_their_seed(tmp_path: Path) -> None:
    """Invariant 7: a fallback nobody can reproduce is a fallback nobody can fix."""
    log = EventLog(tmp_path / "session.jsonl")
    event = log.record("fallback", 8.0, seed=7, reason="deadline")
    assert event.detail == {"seed": 7, "reason": "deadline"}


def test_the_log_can_be_read_by_kind() -> None:
    log = EventLog(None)
    log.record("scene_fired", 0.0, scene=0)
    log.record("section_written", 1.0, track=0)
    log.record("scene_fired", 4.0, scene=1)
    assert [event.at_beats for event in log.of_kind("scene_fired")] == [0.0, 4.0]


def test_a_log_with_no_path_still_records_and_flushes() -> None:
    """A dry run is a real run with nowhere to put the paper."""
    log = EventLog(None)
    log.record("scene_fired", 0.0)
    assert log.flush() == 1
    assert len(log.events) == 1


# ---------------------------------------------------------------------------------- file


def test_an_event_round_trips_through_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    original = an_event(at_beats=12.0, kind="fallback", detail={"seed": 7})
    append_events(path, [original])
    assert load_events(path) == (original,)


def test_the_file_is_append_only_across_two_writers(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    append_events(path, [an_event(at_beats=0.0)])
    append_events(path, [an_event(at_beats=4.0)])
    assert [event.at_beats for event in load_events(path)] == [0.0, 4.0]


def test_reading_an_absent_file_gives_nothing_rather_than_raising(tmp_path: Path) -> None:
    assert load_events(tmp_path / "never-written.jsonl") == ()


def test_blank_lines_are_not_events_and_are_not_errors(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(
        '\n{"at_beats": 0.0, "kind": "scene_fired", "detail": {}}\n\n', encoding="utf-8"
    )
    assert len(load_events(path)) == 1


def test_a_malformed_line_is_reported_with_its_number(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(
        '{"at_beats": 0.0, "kind": "scene_fired", "detail": {}}\nnot json at all\n',
        encoding="utf-8",
    )
    with pytest.raises(MalformedEventError, match=":2:"):
        load_events(path)


def test_a_line_with_an_unknown_kind_is_malformed_too(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text('{"at_beats": 0.0, "kind": "guessing", "detail": {}}\n', encoding="utf-8")
    with pytest.raises(MalformedEventError, match="unknown event kind"):
        load_events(path)


# --------------------------------------------------------------- the Phase 3 rate kinds


@pytest.mark.parametrize(
    "kind", ["section_requested", "section_parsed", "deadline_missed", "schema_violation"]
)
def test_the_phase_three_kinds_round_trip(kind: str, tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    append_events(path, [an_event(kind=kind, detail={"section": 0, "model": "claude-sonnet-5"})])
    assert load_events(path)[0].kind == kind


def test_a_rate_is_computed_against_what_was_actually_asked() -> None:
    """The denominator is `section_requested`, not "sections we liked"."""
    log = EventLog(None)
    for index in range(4):
        log.record("section_requested", 0.0, section=index)
    log.record("deadline_missed", 0.0, section=1)
    assert rate_of(log, "deadline_missed") == 0.25


def test_a_rate_with_nothing_asked_is_none_and_not_zero() -> None:
    """A run that made no calls has no conformance rate; 0% would blame the model."""
    assert rate_of(EventLog(None), "schema_violation") is None


def test_a_rate_can_be_computed_from_a_file(tmp_path: Path) -> None:
    """The report reads a log somebody else wrote, so this has to work off disk."""
    path = tmp_path / "session.jsonl"
    log = EventLog(path)
    log.record("section_requested", 0.0, section=0)
    log.record("section_requested", 0.0, section=1)
    log.record("section_generated", 0.0, section=0)
    log.flush()
    assert rate_of(load_events(path), "section_generated") == 0.5


def test_a_cost_bearing_event_carries_a_number() -> None:
    """`usd` as a string would be a total that silently concatenates."""
    log = EventLog(None)
    event = log.record("section_generated", 0.0, section=0, input_tokens=1200, output_tokens=340)
    assert isinstance(event.detail["input_tokens"], int)
