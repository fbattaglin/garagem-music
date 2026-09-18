"""Phase 4's exit criteria read back from an event log (`obs/performance.py`).

Stage 6's paid session is judged by these functions, so each is tested against the
smallest log that can fool it: the log that meets a criterion, and the one that looks as
if it does.
"""

from __future__ import annotations

from garagem.obs import (
    Check,
    Event,
    model_share,
    performance_checks,
    render_checks,
    runs,
    setlist_checks,
    setlist_session_checks,
)

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


# ------------------------------------------------------------------------------ the chaos


def test_a_request_with_no_outcome_is_a_producer_that_stopped_answering() -> None:
    """What an uncaught `CircuitOpenError` left behind: requests, and nothing after them."""
    log = [
        e("section_requested", section=3, model="m"),
        e("fallback", section=3, model="m", reason="ProviderUnavailableError"),
        e("section_requested", section=4, model="m"),
        e("section_requested", section=5, model="m"),
        e("section_requested", section=6, model="m"),
        ended(),
    ]
    found = check(performance_checks(log), "no deadline")
    assert not found.met
    assert "2 requests never answered, declined or failed" in found.evidence


def test_without_a_network_failure_there_is_no_chaos_to_report() -> None:
    log = [e("scene_fired", 0.0, section=0), ended(spend=SPEND)]
    assert not any(c.criterion.startswith("the network") for c in performance_checks(log))


def network_lost_at_bar_20(*after: Event) -> list[Event]:
    return [
        e("scene_fired", 0.0, section=0),
        e("section_written", 80.0, section=5, seed=12),
        e("section_requested", section=7, model="m"),
        e("fallback", section=7, model="m", reason="ProviderUnavailableError"),
        e("section_requested", section=8, model="m"),
        e("fallback", section=8, model="m", reason="CircuitOpenError"),
        *after,
    ]


def test_the_music_playing_on_through_a_dead_network_is_met_and_says_when() -> None:
    log = network_lost_at_bar_20(
        e("section_written", 200.0, section=12, seed=19),
        e("section_requested", section=13, model="m"),
        e("section_parsed", section=13, model="m"),
        ended(spend=SPEND),
    )
    found = check(performance_checks(log), "the network died")
    assert found.met
    assert found.evidence == (
        "lost at bar 20, back at bar 50. 1 calls failed, 1 refused by the open breaker; after "
        "the first loss 0 beats lost, 0 boundaries without a section, played to its end"
    )


def test_a_network_that_drops_twice_is_two_outages() -> None:
    """The chaos run of 2026-09-13: back at bar 55, lost again at bar 77."""
    log = network_lost_at_bar_20(
        e("section_written", 200.0, section=12, seed=19),
        e("section_requested", section=13, model="m"),
        e("section_parsed", section=13, model="m"),
        e("section_written", 300.0, section=14, seed=21),
        e("section_requested", section=15, model="m"),
        e("fallback", section=15, model="m", reason="ProviderUnavailableError"),
        ended(spend=SPEND),
    )
    found = check(performance_checks(log), "the network died")
    assert found.met
    assert found.evidence.startswith("lost at bar 20, back at bar 50; lost at bar 75, not back")


def test_a_boundary_without_its_section_after_the_network_went_is_not_met() -> None:
    log = network_lost_at_bar_20(
        e("fallback", 120.0, section=9, reason="not_written"), ended(spend=SPEND)
    )
    found = check(performance_checks(log), "the network died")
    assert not found.met
    assert found.evidence.startswith("lost at bar 20, not back by the end.")


# ------------------------------------------------------- Phase 5: a song from a setlist


def loaded(song: int = 1, *, serving: str = "baked") -> Event:
    return e("setlist_loaded", 0.0, setlist="first", song=song, title="Seven", serving=serving)


def a_song_from_disk(
    song: int = 1, *, beats: float = 220 * BPM / 60, serving: str = "baked", takes: int = 2
) -> list[Event]:
    """One `jam.py --setlist` run: takes out of the buffer, the floor for the rest."""
    log: list[Event] = [loaded(song, serving=serving)]
    for section in range(4):
        if section < takes:
            log.append(e("section_generated", float(section), section=section, source="buffer"))
        else:
            log.append(
                e("fallback", float(section), section=section, seed=section, reason="not_in_buffer")
            )
        log.append(e("section_written", float(section), section=section, seed=section))
        log.append(e("scene_fired", float(section) * 32.0, section=section, slack_bars=1))
    log.append(ended(at=beats, spend={"spent_usd": "0.0000"}))
    return log


def test_a_song_from_disk_meets_phase_fives_lines() -> None:
    checks = setlist_checks(a_song_from_disk(), share_floor=2)
    assert all(check.met for check in checks), [c for c in checks if not c.met]
    assert "2 of 4 sections played came from a take" in check(checks, "at least 2").evidence


def test_a_song_that_spent_money_is_not_offline() -> None:
    log = a_song_from_disk()
    log[-1] = ended(at=220 * BPM / 60, spend={"spent_usd": "0.0035"})
    assert not check(setlist_checks(log), "no network").met


def test_a_song_served_by_an_adapter_is_not_offline() -> None:
    log = a_song_from_disk(serving="anthropic")
    assert not check(setlist_checks(log), "no network").met


def test_a_call_lost_to_a_network_is_not_offline() -> None:
    log = a_song_from_disk()
    log.insert(2, e("fallback", 8.0, section=1, reason="ProviderUnavailableError"))
    assert not check(setlist_checks(log), "no network").met


def test_too_little_of_the_song_from_the_setlist_is_not_met() -> None:
    checks = setlist_checks(a_song_from_disk(takes=1), share_floor=2)
    assert not check(checks, "at least 2").met


def test_a_song_conducted_short_of_its_baked_length_still_played_to_its_end() -> None:
    """`end` on pad 8 and a jump both cut bars on purpose (`phase-5-findings.md` §13)."""
    log = a_song_from_disk(beats=175 * BPM / 60)
    found = check(setlist_checks(log), "played to its end")
    assert found.met
    assert "175 s" in found.evidence


def test_a_song_that_stopped_early_is_not_played_out() -> None:
    log = a_song_from_disk()
    log[-1] = ended(at=100.0, finished=False, spend={"spent_usd": "0.0000"})
    assert not check(setlist_checks(log), "played to its end").met


def test_a_setlist_song_is_not_judged_on_deadlines_or_spend() -> None:
    """A song from disk makes no call, so Phase 4's model criteria say nothing about it."""
    criteria = [c.criterion for c in setlist_checks(a_song_from_disk())]
    assert not any("deadline" in c or "budget" in c for c in criteria)


# ------------------------------------------------------ Phase 5: the whole Wi-Fi-off session


def a_session(songs: int = 3, **extra: object) -> list[Event]:
    log: list[Event] = []
    for song in range(1, songs + 1):
        log.extend(a_song_from_disk(song, **extra))  # type: ignore[arg-type]
    return log


def test_three_songs_back_to_back_make_the_ten_minutes() -> None:
    checks = setlist_session_checks(a_session(), share_floor=6)
    assert all(check.met for check in checks), [c for c in checks if not c.met]
    assert "3 songs, 660 s in all, 0 beats lost" in check(checks, "600 s of setlist").evidence


def test_two_songs_are_not_ten_minutes() -> None:
    assert not check(setlist_session_checks(a_session(2)), "600 s of setlist").met


def test_a_song_that_stopped_early_fails_the_whole_session() -> None:
    log = a_session()
    log[-1] = ended(at=220 * BPM / 60, finished=False, spend={"spent_usd": "0.0000"})
    assert not check(setlist_session_checks(log), "600 s of setlist").met


def test_only_the_trailing_setlist_runs_count_as_the_session() -> None:
    """An earlier generated run in the same log is another day's evidence, not this session."""
    log = [e("scene_fired", 0.0, section=0), ended(spend=SPEND), *a_session()]
    assert check(setlist_session_checks(log), "600 s of setlist").evidence.startswith("3 songs")
    assert len(runs(log)) == 4


def test_a_session_nobody_conducted_reports_no_minilab_line() -> None:
    criteria = [c.criterion for c in setlist_session_checks(a_session())]
    assert "conducted from the MiniLab" not in criteria


def test_a_session_conducted_in_every_song_is_met() -> None:
    log: list[Event] = []
    for song in range(1, 4):
        run = a_song_from_disk(song)
        run.insert(1, e("cue_received", 4.0, cue="fill", family="bar"))
        log.extend(run)
    assert check(setlist_session_checks(log), "conducted").met


def test_a_song_nobody_touched_breaks_the_conducted_line() -> None:
    log: list[Event] = []
    for song in range(1, 4):
        run = a_song_from_disk(song)
        if song != 3:
            run.insert(1, e("cue_received", 4.0, cue="fill", family="bar"))
        log.extend(run)
    found = check(setlist_session_checks(log), "conducted")
    assert not found.met
    assert "in 2 of 3 songs" in found.evidence


def test_the_report_says_which_phase_it_read() -> None:
    printed = render_checks(
        setlist_checks(a_song_from_disk()),
        model_share(a_song_from_disk()),
        phase="Phase 5",
        wrote="from the setlist:",
    )
    assert printed.startswith("Phase 5, read from this performance's log:")
    assert "from the setlist: 2 of the 4 sections that played" in printed
