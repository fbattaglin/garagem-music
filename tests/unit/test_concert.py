"""The concert as a file: what a person asks for, written back, and what the show plays of it.

ADR-030. The studio keeps nothing of its own, so everything it decides has to survive being
written to `setlists/<name>.toml` and read again, and the show has to play exactly what that
file says: its order, and only the songs approved once any has been judged.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from garagem.domain import Feel
from garagem.setlist import (
    Setlist,
    SetlistError,
    SetlistSpec,
    Song,
    SongSpec,
    Verdict,
    arranged,
    composed_as,
    direction_for,
    header_of,
    lineup,
    load_spec,
    load_styles,
    render_spec,
    save_spec,
    sketch,
    spec_beside,
)

ROOT = Path(__file__).resolve().parents[2]
STYLES = load_styles(ROOT / "styles")
BPM = 132.0


def asked(title: str, **more: object) -> SongSpec:
    base: dict[str, object] = {"title": title, "key": 4, "seconds": 90, "seed": 7}
    return SongSpec.model_validate(base | more)


def written(spec: SongSpec) -> Song:
    form, endings = arranged(spec, BPM)
    return Song(
        title=spec.title,
        key=spec.key,
        scale=spec.scale,
        feel=spec.feel,
        seconds=spec.seconds,
        seed=spec.seed,
        form=form,
        endings=endings,
        style=spec.style,
        notes=spec.notes,
    )


def bake_of(*songs: SongSpec) -> Setlist:
    return Setlist(
        name="t",
        provider="fake",
        model="m",
        baked_on=date(2026, 11, 11),
        bpm=BPM,
        songs=tuple(written(song) for song in songs),
    )


# ------------------------------------------------------------------- the file, both ways


@pytest.mark.parametrize("path", sorted((ROOT / "setlists").glob("*.toml")), ids=lambda p: p.stem)
def test_every_concert_in_the_repository_survives_being_written_back(
    path: Path, tmp_path: Path
) -> None:
    spec = load_spec(path)
    copy = tmp_path / path.name
    copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    save_spec(spec, copy)
    assert load_spec(copy) == spec


def test_everything_the_studio_decides_survives_the_file(tmp_path: Path) -> None:
    spec = SetlistSpec(
        name="friday",
        songs=(
            asked(
                "Red Dirt",
                scale="major",
                feel=Feel.SHUFFLE,
                bpm=126.5,
                style="southern",
                notes='a "quoted" note,\nwith a second line and a back\\slash',
                verdict=Verdict.APPROVED,
            ),
            asked("Set Aside", parked=True, verdict=Verdict.REJECTED),
        ),
    )
    path = tmp_path / "friday.toml"
    save_spec(spec, path)
    assert load_spec(path) == spec


def test_a_song_is_written_as_what_was_asked_of_it_and_nothing_else() -> None:
    text = render_spec(SetlistSpec(name="t", songs=(asked("Plain"),)))
    assert "style" not in text and "verdict" not in text and "parked" not in text
    assert 'feel = "straight8"' in text


def test_the_opening_comment_is_kept_and_the_rest_is_not(tmp_path: Path) -> None:
    path = tmp_path / "t.toml"
    path.write_text(
        '# What this concert is.\n#\n# Two lines of it.\n\nname = "t"\n\n'
        '# a comment on a song\n[[song]]\ntitle = "One"\nkey = 4\nseconds = 90\nseed = 7\n',
        encoding="utf-8",
    )
    save_spec(load_spec(path), path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# What this concert is.\n#\n# Two lines of it.\n")
    assert "a comment on a song" not in text
    assert header_of(text) == "# What this concert is.\n#\n# Two lines of it."


def test_two_songs_cannot_share_a_title(tmp_path: Path) -> None:
    """A title is how a song's spec finds what was written for it."""
    song = '[[song]]\ntitle = "One"\nkey = 4\nseconds = 90\nseed = 7\n'
    path = tmp_path / "t.toml"
    path.write_text(f'name = "t"\n\n{song}\n{song}', encoding="utf-8")
    with pytest.raises(SetlistError, match="a title names one song"):
        load_spec(path)


# ------------------------------------------------------------- whether a song is current


def test_a_song_written_as_asked_is_current() -> None:
    spec = asked("One", style="arena", notes="loud")
    assert composed_as(spec, written(spec), BPM)


@pytest.mark.parametrize(
    "change",
    [
        {"key": 5},
        {"scale": "major"},
        {"feel": Feel.HALFTIME},
        {"seconds": 120},
        {"seed": 8},
        {"bpm": 140.0},
        {"style": "desert"},
        {"notes": "quieter"},
    ],
    ids=lambda change: next(iter(change)),
)
def test_anything_the_songwriter_or_the_arranger_reads_makes_it_stale(
    change: dict[str, object],
) -> None:
    spec = asked("One", style="arena", notes="loud")
    assert not composed_as(spec.model_copy(update=change), written(spec), BPM)


@pytest.mark.parametrize("change", [{"verdict": Verdict.APPROVED}, {"parked": True}])
def test_a_verdict_or_being_set_aside_changes_nothing_about_the_music(
    change: dict[str, object],
) -> None:
    spec = asked("One")
    assert composed_as(spec.model_copy(update=change), written(spec), BPM)


def test_a_song_with_no_tempo_of_its_own_is_at_the_sets() -> None:
    spec = asked("One")
    assert composed_as(spec, written(spec), BPM)
    assert not composed_as(spec, written(spec), 120.0)


# ----------------------------------------------------------------- what the show plays


def titles(setlist: Setlist, *songs: SongSpec) -> list[str]:
    return [song.title for song in lineup(setlist, SetlistSpec(name="t", songs=songs))]


def test_a_bake_with_no_concert_plays_as_it_was_written() -> None:
    a, b = asked("A"), asked("B")
    assert [song.title for song in lineup(bake_of(a, b), None)] == ["A", "B"]


def test_a_concert_nobody_has_judged_plays_everything_written_in_its_own_order() -> None:
    a, b, c = asked("A"), asked("B"), asked("C")
    assert titles(bake_of(a, b), c, b, a) == ["B", "A"]


def test_once_a_song_is_judged_only_approved_songs_play() -> None:
    a, b, c = asked("A"), asked("B"), asked("C")
    bake = bake_of(a, b, c)
    yes = a.model_copy(update={"verdict": Verdict.APPROVED})
    no = c.model_copy(update={"verdict": Verdict.REJECTED})
    assert titles(bake, yes, b, no) == ["A"]
    assert titles(bake, a, b, no) == []


def test_a_song_set_aside_does_not_play_even_approved() -> None:
    a = asked("A", verdict=Verdict.APPROVED, parked=True)
    b = asked("B", verdict=Verdict.APPROVED)
    assert titles(bake_of(a, b), a, b) == ["B"]


def test_a_bake_finds_its_concert_whoever_wrote_it(tmp_path: Path) -> None:
    assert spec_beside(tmp_path / "show.json") == tmp_path / "show.toml"
    assert spec_beside(tmp_path / "show.fake.json") == tmp_path / "show.toml"


# ----------------------------------------------------------------------------- styles


def test_the_six_styles_load_and_each_can_start_a_song() -> None:
    assert set(STYLES) == {"arena", "desert", "duo", "interlock", "riff-stops", "southern"}
    for style in STYLES.values():
        song = sketch(style, "Untitled 1", 3)
        assert song.feel in style.feels and song.scale in style.scales
        assert song.bpm is not None and style.bpm[0] <= song.bpm <= style.bpm[1] + 1
        assert song.bpm % 2 == 0


def test_a_sketch_is_the_same_song_for_the_same_seed() -> None:
    style = STYLES["desert"]
    assert sketch(style, "x", 5) == sketch(style, "x", 5)
    assert {sketch(style, "x", seed).key for seed in range(40)} != {sketch(style, "x", 5).key}


def test_a_direction_describes_the_writing_and_names_no_band() -> None:
    """The reference is for the person choosing. The songwriter is told what the band does."""
    for style in STYLES.values():
        told = direction_for(sketch(style, "x", 1), STYLES)
        assert told.startswith("Style: ")
        assert style.reference not in told


def test_words_of_ones_own_reach_the_songwriter_as_they_were_written() -> None:
    song = asked("One", style="like a train", notes="no keys at all")
    assert direction_for(song, STYLES) == (
        "Style: like a train\nNotes from the bandleader: no keys at all"
    )


def test_a_song_that_says_nothing_is_asked_for_in_the_words_it_always_was() -> None:
    assert direction_for(asked("One"), STYLES) == ""


def test_a_style_whose_tempo_is_not_a_range_is_refused(tmp_path: Path) -> None:
    (tmp_path / "odd.toml").write_text(
        'summary = "s"\ndirection = "d"\nfeels = ["shuffle"]\n'
        'scales = ["minor"]\nbpm = [140, 90]\n',
        encoding="utf-8",
    )
    with pytest.raises(SetlistError, match="odd"):
        load_styles(tmp_path)
