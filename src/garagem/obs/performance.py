"""A performance's exit criteria, read back from its own event log. Pure.

Stage 6's paid session is judged by what its log says, and a judgement made by reading
a thousand lines by eye is a judgement nobody can repeat. Each criterion is a function of
the events alone — the spend included, which `scripts/jam.py` records as `session_ended`
— so the verdict printed after the last bar is the one any later reading of
`bench/jam.jsonl` gets.

**Evidence, not only a tick.** Every check carries the numbers it was decided on, because
a criterion that is missed by one cue struck on the bar line and one missed by a broken
scheduler print the same `not met`, and only the evidence tells them apart
(`phase-4-findings.md` §10).

**A check that nothing tested is not met.** A session with no jump in it says nothing
about what happens after a jump, and reporting that as met would close a criterion on an
absence.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from pydantic import BaseModel

from garagem.obs.events import FROZEN, Event

BEATS_PER_BAR: Final = 4
EIGHT_MINUTES_S: Final = 480.0
# Phase 5's Wi-Fi-off session: the setlist's songs, one after another (ADR-025).
SETLIST_SESSION_S: Final = 600.0
# What `setlist_loaded` says answered the producer: takes read from disk, never a network.
BAKED: Final = "baked"
# A scheduler fallback that means a section boundary went by without its section.
UNHANDLED: Final = frozenset({"not_written", "repeated_too_long"})
# A call the network lost, or one the breaker refused because the network had been lost.
NETWORK: Final = frozenset({"ProviderUnavailableError", "CircuitOpenError"})


class Check(BaseModel):
    """One criterion, whether this performance met it, and what that was decided on."""

    model_config = FROZEN

    criterion: str
    met: bool
    evidence: str


def performance_checks(
    events: Sequence[Event], *, minimum_seconds: float = EIGHT_MINUTES_S
) -> tuple[Check, ...]:
    """Every criterion this log can speak to. Cost and staleness need a model in the run;
    cue latency needs a controller. The others are always checked."""
    ended = _last(events, "session_ended")
    checks = [
        _continuous(events, ended, minimum_seconds),
        _deadlines(events),
        _measured(events),
    ]
    if ended is not None and "spent_usd" in ended.detail:
        checks.append(_cost(ended))
    if any(event.kind == "cue_received" for event in events):
        checks.append(_next_bar(events))
    if ended is not None and "spent_usd" in ended.detail:
        checks.append(_never_stale(events))
    if any(_lost_to_the_network(event) for event in events):
        checks.append(_network(events, ended))
    return tuple(checks)


def model_share(events: Sequence[Event]) -> tuple[int, int]:
    """How many of the sections that played the model wrote, out of how many played.

    What played is the last write of a section before its scene was fired; who wrote it is
    the source the scheduler named just before that write. A jump fired for the bar a
    section was already launching on takes that section's place (ADR-022).
    """
    source: dict[int, str] = {}
    written: dict[int, str] = {}
    played: list[tuple[int, str]] = []
    for event in events:
        section = _int(event.detail.get("section"))
        if event.kind == "section_generated" and event.detail.get("source") == "buffer":
            source[section] = "model"
        elif event.kind == "fallback" and event.detail.get("reason") == "not_in_buffer":
            source[section] = "floor"
        elif event.kind == "section_written":
            written[section] = source.pop(section, "floor")
        elif event.kind == "scene_fired":
            launch = int(event.at_beats // BEATS_PER_BAR) + _int(event.detail.get("slack_bars", 0))
            played.append((launch, written.get(section, "floor")))
        elif event.kind == "cue_applied" and event.detail.get("cue") == "chorus_now":
            launch = _int(event.detail.get("fired_bar"))
            if played and played[-1][0] == launch:
                played.pop()
            # The candidate a jump fires was written by the floor before the song began.
            played.append((launch, "floor"))
    return sum(1 for _, who in played if who == "model"), len(played)


def render_checks(
    checks: Sequence[Check],
    share: tuple[int, int] | None = None,
    *,
    phase: str = "Phase 4",
    wrote: str = "the model wrote",
) -> str:
    lines = [f"{phase}, read from this performance's log:"]
    lines.extend(
        f"  [{'met' if check.met else 'NOT met'}] {check.criterion} — {check.evidence}"
        for check in checks
    )
    if share is not None and share[1]:
        lines.append(f"  {wrote} {share[0]} of the {share[1]} sections that played")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- Phase 5: from a setlist


def setlist_checks(events: Sequence[Event], *, share_floor: int | None = None) -> tuple[Check, ...]:
    """One song played from a setlist, against Phase 5's criteria (ADR-024, ADR-025).

    Phase 4's report asks what a generated session answers — deadlines, spend, staleness —
    and a song from disk makes no call to have any of that. What it has to show instead is
    that it played to its end, that nothing could have reached a network, and how much of it
    came from the setlist rather than from the floor.

    **A song is not held to its baked length.** A jump cuts bars and `end` finishes the song
    early, both on purpose, so the conducted song that ran 175 s of a 218 s form was conducted
    rather than broken. Ten minutes is the *session's* line, and `setlist_session_checks` is
    where it is read.
    """
    ended = _last(events, "session_ended")
    checks = [_played_out(events, ended), _offline(events, ended)]
    if any(event.kind == "cue_received" for event in events):
        checks.append(_next_bar(events))
    if share_floor is not None:
        checks.append(_from_the_setlist(events, share_floor))
    return tuple(checks)


def setlist_session_checks(
    events: Sequence[Event],
    *,
    minimum_seconds: float = SETLIST_SESSION_S,
    share_floor: int | None = None,
) -> tuple[Check, ...]:
    """The Wi-Fi-off session: the setlist's songs played one after another (ADR-025).

    A session is the log's **trailing run of setlist songs** — every performance after the
    last one that was not played from a setlist. Each song is its own `jam.py` run, so the
    length that matters is their sum, and a run that stopped early or lost a beat fails the
    whole session rather than only itself.
    """
    played = _trailing_setlist_runs(events)
    checks = [_together(played, minimum_seconds), _offline_together(played)]
    if any(event.kind == "cue_received" for run in played for event in run):
        checks.append(_conducted(played))
    if share_floor is not None:
        checks.append(_from_the_setlist([event for run in played for event in run], share_floor))
    return tuple(checks)


def runs(events: Sequence[Event]) -> tuple[tuple[Event, ...], ...]:
    """The log split into performances. Each ends at its own `session_ended`."""
    split: list[tuple[Event, ...]] = []
    current: list[Event] = []
    for event in events:
        current.append(event)
        if event.kind == "session_ended":
            split.append(tuple(current))
            current = []
    if current:
        split.append(tuple(current))
    return tuple(split)


# ------------------------------------------------------------------------------ criteria


def _continuous(events: Sequence[Event], ended: Event | None, minimum_seconds: float) -> Check:
    fires = [event for event in events if event.kind == "scene_fired"]
    lost = [event for event in events if event.kind == "beat_lost"]
    minutes = minimum_seconds / 60
    # A song from a setlist lasts its form, not a round number of minutes: say it in seconds.
    length = f"{minutes:g} minutes" if minutes.is_integer() else f"{minimum_seconds:.0f} s"
    criterion = f"{length} of continuous session"
    if ended is None or not fires:
        return Check(criterion=criterion, met=False, evidence="the log has no ending to read")
    bpm = float(str(ended.detail["bpm"]))
    seconds = (ended.at_beats - fires[0].at_beats) * 60.0 / bpm
    finished = bool(ended.detail["finished"])
    evidence = (
        f"{seconds:.0f} s, {len(fires) - 1} section changes, "
        f"{'played to its end' if finished else 'stopped early'}, "
        f"{len(lost)} beat{'s' if len(lost) != 1 else ''} lost"
    )
    met = finished and not lost and seconds >= minimum_seconds
    return Check(criterion=criterion, met=met, evidence=evidence)


def _deadlines(events: Sequence[Event]) -> Check:
    asked = sum(1 for event in events if event.kind == "section_requested")
    delivered = sum(1 for event in events if event.kind == "section_parsed")
    missed = sum(1 for event in events if event.kind == "deadline_missed")
    reasons = Counter(
        str(event.detail.get("reason")) for event in events if event.kind == "fallback"
    )
    unhandled = sum(count for reason, count in reasons.items() if reason in UNHANDLED)
    failed_writes = sum(
        1 for event in events if event.kind == "beat_lost" and "error" in event.detail
    )
    floor = reasons.get("not_in_buffer", 0)
    unanswered = _unanswered(events)
    evidence = (
        f"{asked} asked, {delivered} delivered, {missed} over deadline; "
        f"{floor} writes by the floor, each with its seed"
    )
    if unhandled or failed_writes:
        evidence += f"; {unhandled} boundaries without a section, {failed_writes} failed writes"
    if unanswered:
        evidence += f"; {unanswered} requests never answered, declined or failed"
    return Check(
        criterion="no deadline overrun left unhandled",
        met=not unhandled and not failed_writes and not unanswered,
        evidence=evidence,
    )


def _measured(events: Sequence[Event]) -> Check:
    written = Counter(_section_and_seed(e) for e in events if e.kind == "section_written")
    measured = Counter(_section_and_seed(e) for e in events if e.kind == "section_measured")
    unmeasured = sum((written - measured).values())
    total = sum(written.values())
    return Check(
        criterion="coherence metrics on every section",
        met=total > 0 and unmeasured == 0,
        evidence=f"{total - unmeasured} of {total} section writes measured",
    )


def _cost(ended: Event) -> Check:
    spent = Decimal(str(ended.detail["spent_usd"]))
    estimated = Decimal(str(ended.detail["estimated_usd"]))
    target = Decimal(str(ended.detail["target_usd"]))
    cap = Decimal(str(ended.detail["cap_usd"]))
    evidence = (
        f"${spent:.4f} spent (${estimated:.4f} of it estimated from cancelled streams) "
        f"against a ${target:.2f} target, capped at ${cap:.2f}"
    )
    if ended.detail.get("killed"):
        evidence += "; the governor's kill switch engaged"
    return Check(
        criterion="cost inside the declared budget", met=spent <= target, evidence=evidence
    )


def _next_bar(events: Sequence[Event]) -> Check:
    criterion = "a MiniLab cue takes effect on the next bar"
    fired = [e for e in events if e.kind == "cue_applied" and "fired_bar" in e.detail]
    if not fired:
        return Check(criterion=criterion, met=False, evidence="no next-bar cue was applied")
    late = [e for e in fired if _int(e.detail["fired_bar"]) - _int(e.detail["cue_bar"]) != 1]
    evidence = f"{len(fired) - len(late)} of {len(fired)} landed one bar after the pad"
    if late:
        evidence += "; late: " + ", ".join(_where_struck(events, event) for event in late)
    return Check(criterion=criterion, met=not late, evidence=evidence)


def _never_stale(events: Sequence[Event]) -> Check:
    """After every jump the model is asked about the new song, and nothing stale is written."""
    criterion = "after a jump the model is asked again, and a stale section never plays"
    jumps = 0
    unasked: list[int] = []
    for position, event in enumerate(events):
        if event.kind != "form_replanned" or not _follows_a_jump(events, position):
            continue
        jumps += 1
        jumped_to = _int(event.detail["from_section"])
        names = str(event.detail.get("names", "")).split(",")
        if not _retargeted(events[position + 1 :], jumped_to, names):
            unasked.append(jumped_to)

    stale = _stale_writes(events)
    refused = sum(1 for e in events if e.kind == "fallback" and e.detail.get("reason") == "stale")
    if not jumps:
        return Check(criterion=criterion, met=False, evidence="no jump was struck")
    evidence = (
        f"{jumps} jump{'s' if jumps != 1 else ''}, the model asked after "
        f"{jumps - len(unasked)}; {refused} stale scores refused, {stale} written"
    )
    if unasked:
        evidence += "; not asked about the new song after the jump to section " + ", ".join(
            str(i) for i in unasked
        )
    return Check(criterion=criterion, met=not unasked and not stale, evidence=evidence)


def _network(events: Sequence[Event], ended: Event | None) -> Check:
    """The chaos test, as the log can see it: the network went, and the song did not stop.

    Whether anything was *heard* is the ear's half of the criterion, and not this one's.
    """
    criterion = "the network died mid-session and the music played on"
    first = next(i for i, event in enumerate(events) if _lost_to_the_network(event))
    after = events[first:]
    lost = [event for event in events if _lost_to_the_network(event)]
    refused = sum(1 for event in lost if event.detail.get("reason") == "CircuitOpenError")
    beats_lost = sum(1 for event in after if event.kind == "beat_lost")
    unhandled = sum(
        1 for event in after if event.kind == "fallback" and event.detail.get("reason") in UNHANDLED
    )
    finished = ended is not None and bool(ended.detail.get("finished"))
    outages = "; ".join(
        f"lost at bar {_bar_near(events, went)}, "
        + (
            f"back at bar {_bar_near(events, returned)}"
            if returned is not None
            else "not back by the end"
        )
        for went, returned in _outages(events)
    )
    evidence = (
        f"{outages}. {len(lost) - refused} calls failed, {refused} refused by the open "
        f"breaker; after the first loss {beats_lost} beats lost, "
        f"{unhandled} boundaries without a section, "
        f"{'played to its end' if finished else 'stopped early'}"
    )
    met = finished and not beats_lost and not unhandled and not _unanswered(events)
    return Check(criterion=criterion, met=met, evidence=evidence)


def _played_out(events: Sequence[Event], ended: Event | None) -> Check:
    """The song reached its own end, however long the conducting left it, and lost no beat."""
    criterion = "played to its end, with no beat lost"
    fires = [event for event in events if event.kind == "scene_fired"]
    lost = [event for event in events if event.kind == "beat_lost"]
    if ended is None or not fires:
        return Check(criterion=criterion, met=False, evidence="the log has no ending to read")
    seconds = (ended.at_beats - fires[0].at_beats) * 60.0 / float(str(ended.detail["bpm"]))
    finished = bool(ended.detail["finished"])
    evidence = (
        f"{seconds:.0f} s, {len(fires) - 1} section changes, "
        f"{'played to its end' if finished else 'stopped early'}, "
        f"{len(lost)} beat{'s' if len(lost) != 1 else ''} lost"
    )
    return Check(criterion=criterion, met=finished and not lost, evidence=evidence)


def _offline(events: Sequence[Event], ended: Event | None) -> Check:
    """Nothing that could reach a network was built, and nothing was spent."""
    criterion = "no network: the takes came from disk, and nothing was spent"
    loaded = [event for event in events if event.kind == "setlist_loaded"]
    from_disk = bool(loaded) and all(event.detail.get("serving") == BAKED for event in loaded)
    spent = Decimal(str(ended.detail.get("spent_usd", "0"))) if ended is not None else None
    lost = sum(1 for event in events if _lost_to_the_network(event))
    evidence = (
        f"{len(loaded)} song(s) from a setlist, "
        f"{'served from disk' if from_disk else 'NOT served from disk'}, "
        f"${spent if spent is not None else '?'} spent, {lost} calls lost to a network"
    )
    return Check(criterion=criterion, met=from_disk and spent == 0 and not lost, evidence=evidence)


def _from_the_setlist(events: Sequence[Event], floor: int) -> Check:
    """How much of what played came from the setlist's takes, against a line fixed before."""
    criterion = f"at least {floor} sections played from the setlist's takes"
    from_takes, played = model_share(events)
    return Check(
        criterion=criterion,
        met=from_takes >= floor,
        evidence=f"{from_takes} of {played} sections played came from a take",
    )


def _together(played: Sequence[Sequence[Event]], minimum_seconds: float) -> Check:
    criterion = f"{minimum_seconds:.0f} s of setlist, in songs played one after another"
    if not played:
        return Check(criterion=criterion, met=False, evidence="no song from a setlist in the log")
    seconds = 0.0
    lost = 0
    stopped: list[int] = []
    for number, run in enumerate(played, start=1):
        ended = _last(run, "session_ended")
        fires = [event for event in run if event.kind == "scene_fired"]
        lost += sum(1 for event in run if event.kind == "beat_lost")
        if ended is None or not fires:
            stopped.append(number)
            continue
        if not bool(ended.detail["finished"]):
            stopped.append(number)
        seconds += (ended.at_beats - fires[0].at_beats) * 60.0 / float(str(ended.detail["bpm"]))
    evidence = f"{len(played)} songs, {seconds:.0f} s in all, {lost} beats lost" + (
        f", stopped early: {stopped}" if stopped else ", each played to its end"
    )
    return Check(
        criterion=criterion,
        met=seconds >= minimum_seconds and not lost and not stopped,
        evidence=evidence,
    )


def _offline_together(played: Sequence[Sequence[Event]]) -> Check:
    checks = [_offline(run, _last(run, "session_ended")) for run in played]
    criterion = "no network: every song came from disk, and nothing was spent"
    if not checks:
        return Check(criterion=criterion, met=False, evidence="no song from a setlist in the log")
    return Check(
        criterion=criterion,
        met=all(check.met for check in checks),
        evidence="; ".join(check.evidence for check in checks),
    )


def _conducted(played: Sequence[Sequence[Event]]) -> Check:
    controls = Counter(
        str(event.detail.get("cue"))
        for run in played
        for event in run
        if event.kind == "cue_received"
    )
    songs = sum(1 for run in played if any(event.kind == "cue_received" for event in run))
    return Check(
        criterion="conducted from the MiniLab",
        met=songs == len(played),
        evidence=f"{sum(controls.values())} controls in {songs} of {len(played)} songs",
    )


def _trailing_setlist_runs(events: Sequence[Event]) -> tuple[tuple[Event, ...], ...]:
    played: list[tuple[Event, ...]] = []
    for run in runs(events):
        if any(event.kind == "setlist_loaded" for event in run):
            played.append(run)
        elif any(event.kind == "scene_fired" for event in run):
            played = []
    return tuple(played)


# ------------------------------------------------------------------------------- helpers


def _lost_to_the_network(event: Event) -> bool:
    return event.kind == "fallback" and event.detail.get("reason") in NETWORK


def _outages(events: Sequence[Event]) -> list[tuple[int, int | None]]:
    """Where each stretch without the network began, and where the model next delivered.

    A network that drops twice is two outages, and reporting only the last would say the
    model never came back when it had, for a minute in between.
    """
    outages: list[tuple[int, int | None]] = []
    down = False
    for position, event in enumerate(events):
        if _lost_to_the_network(event) and not down:
            outages.append((position, None))
            down = True
        elif event.kind == "section_parsed" and down:
            outages[-1] = (outages[-1][0], position)
            down = False
    return outages


def _unanswered(events: Sequence[Event]) -> int:
    """Requests with no outcome before the producer asked again. A dead producer shows here.

    The producer asks one section at a time, so every `section_requested` is followed by
    its outcome before the next: delivered, over deadline, or a fallback with the model's
    name on it. The last request may still be in flight when the session ends.
    """
    pending = False
    unanswered = 0
    for event in events:
        if event.kind == "section_requested":
            unanswered += pending
            pending = True
        elif event.kind in ("section_parsed", "deadline_missed") or (
            event.kind == "fallback" and "model" in event.detail
        ):
            pending = False
    return unanswered


def _bar_near(events: Sequence[Event], position: int) -> int:
    """The bar the scheduler last stamped before `position`. The producer stamps beat 0."""
    for event in reversed(events[: position + 1]):
        if event.at_beats > 0:
            return int(event.at_beats // BEATS_PER_BAR)
    return 0


def _follows_a_jump(events: Sequence[Event], position: int) -> bool:
    """The re-plan was a jump's. The producer's thread logs too, so its lines may sit between
    the scheduler's `cue_applied` and the `form_replanned` it wrote next."""
    replanned = events[position]
    for event in reversed(events[:position]):
        if event.kind in ("form_replanned", "macro_changed"):
            return False
        if event.kind == "cue_applied":
            return event.detail.get("cue") == "chorus_now" and _int(
                event.detail.get("section")
            ) == _int(replanned.detail.get("from_section"))
    return False


def _retargeted(after: Sequence[Event], jumped_to: int, names: Sequence[str]) -> bool:
    """The producer's next question after the jump is about the re-planned song.

    Not necessarily the section straight after the chorus: the scheduler writes that one
    from the floor a bar or two into the chorus, and a producer still finishing a call
    begun before the jump rightly never asks for it. What matters is that the next section
    it does ask about carries the new plan's name, or that the plan moved again first.
    """
    for event in after:
        section = _int(event.detail.get("section"))
        if event.kind in ("form_replanned", "macro_changed"):
            return True
        if section <= jumped_to:
            continue
        if event.kind == "fallback" and event.detail.get("reason") == "no_time":
            return True
        if event.kind == "section_requested":
            asked = str(event.detail.get("briefing", "")).split(" ")[0]
            wanted = names[section - jumped_to] if section - jumped_to < len(names) else ""
            return asked == wanted
    # Nothing asked before the log ends: fine if nothing after the chorus was written either.
    return not any(
        event.kind == "section_written" and _int(event.detail.get("section")) > jumped_to + 1
        for event in after
    )


def _stale_writes(events: Sequence[Event]) -> int:
    """Writes of a model's score whose briefing is not the one the model delivered."""
    delivered: dict[int, str] = {}
    from_buffer: set[int] = set()
    stale = 0
    for event in events:
        section = _int(event.detail.get("section"))
        if event.kind == "section_parsed":
            delivered[section] = str(event.detail.get("briefing"))
        elif event.kind == "section_generated" and event.detail.get("source") == "buffer":
            from_buffer.add(section)
        elif event.kind == "section_written" and section in from_buffer:
            from_buffer.discard(section)
            if delivered.get(section) != event.detail.get("briefing"):
                stale += 1
    return stale


def _where_struck(events: Sequence[Event], applied: Event) -> str:
    cue = applied.detail["cue"]
    cue_bar = _int(applied.detail["cue_bar"])
    gap = _int(applied.detail["fired_bar"]) - cue_bar
    struck = [
        event
        for event in events
        if event.kind == "cue_received"
        and event.detail.get("cue") == cue
        and _int(event.detail.get("bar")) == cue_bar
    ]
    beat = f" beat {int(struck[-1].at_beats) % BEATS_PER_BAR + 1} of" if struck else ""
    return f"{cue} struck on{beat} bar {cue_bar}, {gap} bars"


def _section_and_seed(event: Event) -> tuple[int, int]:
    return _int(event.detail.get("section")), _int(event.detail.get("seed"))


def _int(value: object) -> int:
    return int(str(value)) if value is not None else -1


def _last(events: Sequence[Event], kind: str) -> Event | None:
    return next((event for event in reversed(events) if event.kind == kind), None)
