"""Phase 4's exit criteria read back from an event log (`obs/performance.py`).

Stage 6's paid session is judged by these functions, so each is tested against the
smallest log that can fool it: the log that meets a criterion, and the one that looks as
if it does.
"""

from __future__ import annotations

from garagem.obs import Check, Event, model_share, performance_checks, render_checks

BPM = 132.0
EIGHT_MINUTES_BEATS = 480 * BPM / 60


def e(kind: str, at: float = 0.0, **detail: str | int | float | bool) -> Event:
    return Event(at_beats=at, kind=kind, detail=detail)


def ended(
    at: float = EIGHT_MINUTES_BEATS, *, finished: bool = True, spend: dict[str, str] | None = None
) -> Event:
    return e("session_ended", at, finished=finished, bpm=BPM, **(spend or {}))


SPEND = {"spent_usd": "0.0800", "estimated_usd": "0.0050", "target_usd": "0.10", "cap_usd": "1.00"}


VERSE = "verse 8 bars dyn=2 tension=0.35"


def written(section: int, seed: int, briefing: str = VERSE) -> list[Event]:
    return [
        e("section_written", section=section, seed=seed, briefing=briefing),
        e("section_measured", section=section, seed=seed),
    ]


def check(checks: tuple[Check, ...], starts: str) -> Check:
    return next(c for c in checks if c.criterion.startswith(starts))


# ------------------------------------------------------------------------------ continuity


def test_eight_minutes_played_to_the_end_with_no_beat_lost_is_met() -> None:
    log = [e("scene_fired", 0.0, section=0), e("scene_fired", 32.0, section=1), ended()]
    found = check(performance_checks(log), "8 minutes")
    assert found.met
    assert "480 s, 1 section changes, played to its end, 0 beats lost" in found.evidence


def test_a_short_performance_is_not_eight_minutes() -> None:
    log = [e("scene_fired", 0.0, section=0), ended(at=396.0)]
    assert not check(performance_checks(log), "8 minutes").met


def test_a_lost_beat_breaks_continuity_even_when_the_song_finished() -> None:
    log = [e("scene_fired", 0.0, section=0), e("beat_lost", 40.0, reason="rewind"), ended()]
    assert not check(performance_checks(log), "8 minutes").met


# ------------------------------------------------------------------------------- deadlines


def test_an_overrun_the_floor_played_through_is_handled() -> None:
    log = [
        e("section_requested", section=1),
        e("deadline_missed", section=1),
        e("fallback", 20.0, section=1, seed=8, reason="not_in_buffer"),
        *written(1, 8),
        ended(),
    ]
    found = check(performance_checks(log), "no deadline")
    assert found.met
    assert found.evidence == (
        "1 asked, 0 delivered, 1 over deadline; 1 writes by the floor, each with its seed"
    )


def test_a_boundary_that_passed_without_its_section_is_not_handled() -> None:
    log = [e("fallback", 30.0, section=2, reason="not_written"), ended()]
    found = check(performance_checks(log), "no deadline")
    assert not found.met
    assert "1 boundaries without a section" in found.evidence


# --------------------------------------------------------------------------------- metrics


def test_a_write_without_its_metrics_is_caught() -> None:
    log = [*written(0, 7), e("section_written", section=1, seed=8), ended()]
    found = check(performance_checks(log), "coherence")
    assert not found.met
    assert found.evidence == "1 of 2 section writes measured"


# ------------------------------------------------------------------------------------ cost


def test_cost_is_judged_against_the_target_not_the_cap() -> None:
    over = dict(SPEND, spent_usd="0.2500")
    assert check(performance_checks([ended(spend=SPEND)]), "cost").met
    found = check(performance_checks([ended(spend=over)]), "cost")
    assert not found.met
    assert "$0.2500 spent ($0.0050 of it estimated" in found.evidence
    assert "$0.10 target, capped at $1.00" in found.evidence


def test_without_a_model_cost_and_staleness_are_not_reported() -> None:
    criteria = [c.criterion for c in performance_checks([ended()])]
    assert not any(c.startswith(("cost", "after a jump")) for c in criteria)


# ---------------------------------------------------------------------------- cue latency


def test_a_late_cue_names_the_beat_it_was_struck_on() -> None:
    log = [
        e("cue_received", 99.0, cue="fill", bar=24),
        e("cue_applied", 100.0, cue="fill", cue_bar=24, fired_bar=26),
        e("cue_received", 120.0, cue="stop", bar=30),
        e("cue_applied", 121.0, cue="stop", cue_bar=30, fired_bar=31),
        ended(),
    ]
    found = check(performance_checks(log), "a MiniLab cue")
    assert not found.met
    assert found.evidence == (
        "1 of 2 landed one bar after the pad; late: fill struck on beat 4 of bar 24, 2 bars"
    )


def test_boundary_cues_are_not_next_bar_cues() -> None:
    log = [
        e("cue_received", 8.0, cue="end", bar=2),
        e("cue_applied", 9.0, cue="end", cue_bar=2, section=3),
        e("cue_received", 12.0, cue="stop", bar=3),
        e("cue_applied", 13.0, cue="stop", cue_bar=3, fired_bar=4),
        ended(),
    ]
    assert check(performance_checks(log), "a MiniLab cue").met


# ------------------------------------------------------------------------------- staleness


def a_jump(to: int, names: str) -> list[Event]:
    return [
        e("cue_applied", 40.0, cue="chorus_now", cue_bar=9, fired_bar=10, section=to),
        e("section_requested", section=7, briefing="verse 8 bars dyn=2 tension=0.35"),
        e("form_replanned", 40.0, from_section=to, names=names),
    ]


def test_the_model_asked_about_the_new_song_after_a_jump_is_met() -> None:
    log = [
        *a_jump(3, "chorus,bridge,chorus"),
        e("section_requested", section=4, briefing="bridge 8 bars dyn=3 tension=0.55"),
        ended(spend=SPEND),
    ]
    found = check(performance_checks(log), "after a jump")
    assert found.met
    assert found.evidence.startswith("1 jump, the model asked after 1")


def test_asking_under_the_old_plan_after_a_jump_is_not_met() -> None:
    log = [
        *a_jump(3, "chorus,bridge,chorus"),
        e("section_requested", section=4, briefing="verse 8 bars dyn=2 tension=0.35"),
        ended(spend=SPEND),
    ]
    found = check(performance_checks(log), "after a jump")
    assert not found.met
    assert "not asked about the new song after the jump to section 3" in found.evidence


def test_a_model_score_written_under_another_briefing_is_stale() -> None:
    """What the scheduler's guard exists to prevent, caught from the log without it."""
    log = [
        e("section_parsed", section=2, briefing="verse 8 bars dyn=2 tension=0.35"),
        e("section_generated", section=2, seed=9, source="buffer"),
        *written(2, 9, briefing="verse 8 bars dyn=4 tension=0.35"),
        *a_jump(3, "chorus,verse"),
        ended(spend=SPEND),
    ]
    found = check(performance_checks(log), "after a jump")
    assert not found.met
    assert "1 written" in found.evidence


def test_a_session_with_no_jump_has_not_shown_what_happens_after_one() -> None:
    found = check(performance_checks([ended(spend=SPEND)]), "after a jump")
    assert not found.met
    assert found.evidence == "no jump was struck"


# ---------------------------------------------------------------------------- model share


def test_the_share_counts_what_played_not_what_was_written() -> None:
    """Section 1 was the model's until a knob rewrote it from the floor; then it played."""
    log = [
        e("fallback", section=0, seed=7, reason="not_in_buffer"),
        *written(0, 7),
        e("scene_fired", section=0),
        e("section_generated", section=1, seed=8, source="buffer"),
        *written(1, 8),
        e("fallback", section=1, seed=8, reason="not_in_buffer"),
        *written(1, 8),
        e("scene_fired", section=1),
        e("section_generated", section=2, seed=9, source="buffer"),
        *written(2, 9),
        e("scene_fired", section=2),
    ]
    assert model_share(log) == (1, 3)


def test_a_jump_fired_for_the_bar_a_section_was_launching_on_replaces_it() -> None:
    log = [
        e("section_generated", section=1, seed=8, source="buffer"),
        *written(1, 8),
        e("scene_fired", 36.0, section=1, slack_bars=1),
        e("cue_applied", 38.0, cue="chorus_now", cue_bar=9, fired_bar=10, section=1),
    ]
    assert model_share(log) == (0, 1)


def test_the_report_prints_every_check_and_the_share() -> None:
    text = render_checks((Check(criterion="x", met=False, evidence="y"),), (3, 4))
    assert "  [NOT met] x — y" in text
    assert "the model wrote 3 of the 4 sections that played" in text
