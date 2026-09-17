"""The setlist format: a spec a person writes, a bake a script writes, and what plays (ADR-024)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from garagem.agents import worth_asking
from garagem.domain import Feel, Section
from garagem.dsl import brief, parse_text, realise, serialize_section
from garagem.engines import SongBrief, arrange, completed, endings_for, play_section, with_climax
from garagem.setlist import (
    FORMAT,
    Setlist,
    SetlistError,
    Song,
    SongSpec,
    Take,
    TakeStatus,
    answers,
    arranged,
    askable,
    body,
    briefings,
    digest,
    drifted,
    load_setlist,
    load_spec,
    played,
    save_setlist,
    served,
)
from garagem.theory import repair

BPM = 132.0
SPEC = SongSpec(title="Seven", key=4, scale="minor", feel=Feel.STRAIGHT8, seconds=120, seed=7)


def a_take(song_form: tuple[Section, ...], index: int, seed: int, **extra: object) -> Take:
    section = song_form[index]
    score = play_section(section, seed + index)
    dsl = serialize_section(score)
    made = repair(completed(realise(parse_text(dsl, section), seed + index)))[0]
    base: dict[str, object] = {
        "section": index,
        "briefing": section,
        "seed": seed + index,
        "model": "claude-sonnet-5",
        "dsl": dsl,
        "parts": "BAS,DRM,GTR,KEY",
        "input_tokens": 295,
        "output_tokens": 235,
        "cost_usd": Decimal("0.0032"),
        "digest": digest(made),
    }
    return Take.model_validate(base | extra)


def a_song(**extra: object) -> Song:
    form, endings = arranged(SPEC, BPM)
    takes = tuple(a_take(form, index, SPEC.seed) for index in askable(form, worth_asking))
    base: dict[str, object] = {
        "title": SPEC.title,
        "key": SPEC.key,
        "scale": SPEC.scale,
        "feel": SPEC.feel,
        "seconds": SPEC.seconds,
        "seed": SPEC.seed,
        "form": form,
        "endings": endings,
        "takes": takes,
    }
    return Song.model_validate(base | extra)


# ------------------------------------------------------------------------------ the spec


def test_the_committed_setlist_spec_loads() -> None:
    spec = load_spec(Path(__file__).resolve().parents[2] / "setlists" / "first.toml")
    assert spec.name == "first"
    assert len(spec.songs) == 3


def test_a_spec_with_no_song_is_refused_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.toml"
    path.write_text('name = "empty"\n', encoding="utf-8")
    with pytest.raises(SetlistError, match=r"empty\.toml"):
        load_spec(path)


def test_a_spec_with_a_bad_feel_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(
        '[[song]]\ntitle = "x"\nkey = 4\nfeel = "polka"\nseconds = 100\nseed = 1\n',
        encoding="utf-8",
    )
    with pytest.raises(SetlistError, match=r"bad\.toml"):
        load_spec(path)


def test_a_song_is_arranged_exactly_as_jam_arranges_one() -> None:
    form, endings = arranged(SPEC, BPM)
    brief_ = SongBrief(key=4, scale="minor", bpm=BPM, feel=Feel.STRAIGHT8, minimum_seconds=120)
    expected = with_climax(arrange(brief_, 7))
    assert form == expected
    assert endings == endings_for(expected)


# ----------------------------------------------------------------------------- askable


def test_one_take_is_asked_per_distinct_briefing_worth_asking() -> None:
    form, _ = arranged(SPEC, BPM)
    asked = askable(form, worth_asking)
    assert len({form[index] for index in asked}) == len(asked)
    assert all(worth_asking(form[index]) for index in asked)
    assert all(form.index(form[index]) == index for index in asked)
    assert len(asked) < len(form)


# ------------------------------------------------------------------------------ a bake


def test_a_take_for_another_briefing_is_refused() -> None:
    song = a_song()
    wrong = song.takes[0].model_copy(update={"section": song.takes[1].section})
    with pytest.raises(ValueError, match="briefing"):
        a_song(takes=(wrong, *song.takes[1:]))


def test_a_take_with_the_wrong_seed_is_refused() -> None:
    song = a_song()
    wrong = song.takes[0].model_copy(update={"seed": 999})
    with pytest.raises(ValueError, match="seed"):
        a_song(takes=(wrong, *song.takes[1:]))


def test_two_takes_for_one_briefing_are_refused() -> None:
    song = a_song()
    with pytest.raises(ValueError, match="two takes"):
        a_song(takes=(*song.takes, song.takes[0]))


def test_a_bake_survives_a_round_trip_through_its_file(tmp_path: Path) -> None:
    from datetime import date

    setlist = Setlist(
        name="t",
        provider="fake",
        model="claude-sonnet-5",
        baked_on=date(2026, 9, 13),
        bpm=BPM,
        songs=(a_song(),),
    )
    path = tmp_path / "t.json"
    save_setlist(setlist, path)
    assert load_setlist(path) == setlist


def test_a_bake_of_another_format_is_refused(tmp_path: Path) -> None:
    from datetime import date

    setlist = Setlist(
        format=FORMAT + 1,
        name="t",
        provider="fake",
        model="m",
        baked_on=date(2026, 9, 13),
        bpm=BPM,
        songs=(a_song(),),
    )
    path = tmp_path / "t.json"
    save_setlist(setlist, path)
    with pytest.raises(SetlistError, match="format"):
        load_setlist(path)


# --------------------------------------------------------------------------- at playback


def test_answers_are_keyed_by_the_briefing_the_prompt_sends() -> None:
    song = a_song()
    held = answers(song)
    for take in song.takes:
        assert held[brief(take.briefing)] == take.dsl
        assert take.briefing in briefings(song)


def test_a_vetoed_take_does_not_play() -> None:
    song = a_song()
    vetoed = song.takes[0].model_copy(update={"status": TakeStatus.VETOED})
    song = a_song(takes=(vetoed, *song.takes[1:]))
    assert brief(vetoed.briefing) not in answers(song)
    assert vetoed.briefing not in briefings(song)


def test_a_take_plays_what_it_played_when_baked() -> None:
    song = a_song()
    assert drifted(song) == ()
    assert played(song.takes[0]) is not None


def test_a_take_whose_notes_changed_is_reported_as_drifted() -> None:
    song = a_song()
    stale = song.takes[0].model_copy(update={"digest": "0" * 16})
    song = a_song(takes=(stale, *song.takes[1:]))
    assert drifted(song) == (stale.section,)


# ------------------------------------------------------------------------------- knobs


def test_a_knob_moved_briefing_is_answered_by_the_take_it_was_moved_from() -> None:
    """Fabiano, 2026-09-13: a knob moves the briefing and the model's take keeps playing."""
    from garagem.engines import shifted

    song = a_song()
    take = song.takes[0]
    moved = shifted(take.briefing, 1, 0.1)
    assert moved != take.briefing
    assert moved in briefings(song)
    assert body(answers(song)[brief(moved)]) == body(take.dsl)


def test_a_take_served_under_a_moved_briefing_echoes_it_and_logs_no_mismatch() -> None:
    """A knob-served take is working as designed, so the log must not count it a violation."""
    from garagem.engines import shifted

    song = a_song()
    take = song.takes[0]
    moved = shifted(take.briefing, 1, 0.1)

    def mismatches(dsl: str) -> int:
        violations = parse_text(dsl, moved).violations
        return sum(1 for v in violations if v.rule == "section_mismatch")

    assert mismatches(take.dsl) > 0
    assert mismatches(answers(song)[brief(moved)]) == 0
    assert served(take, take.briefing) == take.dsl


def test_an_exact_briefing_always_gets_its_own_take() -> None:
    from garagem.setlist.setlist import reachable

    song = a_song()
    held = reachable(song)
    for take in song.takes:
        assert held[take.briefing] == take


def test_a_vetoed_take_answers_no_knob_either() -> None:
    from garagem.engines import shifted

    song = a_song()
    vetoed = song.takes[0].model_copy(update={"status": TakeStatus.VETOED})
    song = a_song(takes=(vetoed, *song.takes[1:]))
    assert all(
        answers(song).get(brief(moved)) != served(vetoed, moved)
        for moved in (shifted(vetoed.briefing, dyn, 0.0) for dyn in (-2, -1, 0, 1, 2))
    )


def test_a_take_realised_under_a_moved_briefing_plays_the_moved_dynamics() -> None:
    """The groove is the take's; the loudness is the knob's."""
    from garagem.engines import shifted

    song = a_song()
    take = song.takes[0]
    louder = shifted(take.briefing, 2, 0.0)
    as_baked = realise(parse_text(take.dsl, take.briefing), take.seed)
    moved = realise(parse_text(take.dsl, louder), take.seed)
    assert moved.section == louder
    loud = max(n.velocity for part in moved.parts for n in part.notes)
    soft = max(n.velocity for part in as_baked.parts for n in part.notes)
    assert loud > soft
