"""`garagem studio`: the concert prepared from one screen, with no network and no money.

ADR-030. Every test drives the studio the way a person does, by typed lines, against a copy
of a concert in a temporary folder. `--fake` has the players answer in the songwriter's place,
which is the same path with a free provider. The paid path is tested for the one thing that
is its own: nothing is sent before `yes`.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from garagem.agents.songwriter import floor_answers, plan_song
from garagem.llm import BakedProvider, LLMProvider, ProviderError, Request, StreamEvent, Usage
from garagem.obs import load_events
from garagem.setlist import Verdict, load_setlist, load_spec, load_styles
from garagem.stage.studio import Studio, StudioFiles, StudioWiring, bake_of, run_studio

ROOT = Path(__file__).resolve().parents[2]
CONCERT = """# A test concert.

name = "t"

[[song]]
title = "One"
key = 4
seconds = 90
seed = 7

[[song]]
title = "Two"
key = 9
feel = "shuffle"
seconds = 90
seed = 11
bpm = 112
"""


def no_key() -> LLMProvider:
    raise ProviderError("ANTHROPIC_API_KEY is not set")


def files(tmp_path: Path, name: str = "t") -> StudioFiles:
    concert = tmp_path / "setlists" / f"{name}.toml"
    if name == "t" and not concert.exists():
        concert.parent.mkdir(parents=True, exist_ok=True)
        concert.write_text(CONCERT, encoding="utf-8")
    return StudioFiles(
        concert=concert,
        styles=ROOT / "styles",
        session=ROOT / "session.toml",
        catalog=ROOT / "config" / "models.toml",
        budget=ROOT / "config" / "budget.toml",
        log=tmp_path / "studio.jsonl",
    )


def a_studio(tmp_path: Path, *, fake: bool = True, **wiring: object) -> Studio:
    base: dict[str, object] = {"connect": no_key, "today": lambda: date(2026, 11, 11)}
    return Studio(files(tmp_path), StudioWiring(**(base | wiring)), fake=fake)  # type: ignore[arg-type]


def typed(studio: Studio, *lines: str) -> str:
    return "\n".join(studio.execute(line) for line in lines)


def concert(tmp_path: Path) -> list[tuple[str, str]]:
    spec = load_spec(tmp_path / "setlists" / "t.toml")
    return [(song.title, str(song.verdict)) for song in spec.songs]


# ---------------------------------------------------------------- what kind of song


def test_a_new_song_starts_from_its_style_and_is_in_the_file_at_once(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    said = studio.execute('new desert "dark and slow"')
    song = load_spec(tmp_path / "setlists" / "t.toml").songs[2]
    style = load_styles(ROOT / "styles")["desert"]
    assert (song.title, song.style, song.notes) == ("Untitled 1", "desert", "dark and slow")
    assert song.feel in style.feels and song.seed == 12
    assert "compose 3" in said
    assert "idea" in studio.screen()


def test_new_with_no_style_or_an_unknown_one_lists_the_styles_and_adds_nothing(
    tmp_path: Path,
) -> None:
    studio = a_studio(tmp_path)
    for line in ("new", "new polka"):
        assert "southern" in studio.execute(line)
    assert len(concert(tmp_path)) == 2


def test_every_field_of_a_song_can_be_said_from_the_screen(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    typed(
        studio,
        'title 1 "Low Road"',
        "key 1 F# major",
        "tempo 1 144",
        "feel 1 halftime",
        "length 1 150",
        'style 1 "like a train"',
        'note 1 "no organ"',
        "seed 1 99",
    )
    song = load_spec(tmp_path / "setlists" / "t.toml").songs[0]
    assert song.model_dump(exclude={"verdict", "parked"}) == {
        "title": "Low Road",
        "key": 6,
        "scale": "major",
        "feel": "halftime",
        "seconds": 150.0,
        "seed": 99,
        "bpm": 144.0,
        "style": "like a train",
        "notes": "no organ",
    }


@pytest.mark.parametrize(
    "line",
    ["tempo 1 fast", "tempo 1 -3", "feel 1 waltz", "key 1 H", "key 1 D lydian", "tempo 9 120"],
)
def test_a_value_that_makes_no_sense_changes_nothing_and_says_so(tmp_path: Path, line: str) -> None:
    studio = a_studio(tmp_path)
    before = (tmp_path / "setlists" / "t.toml").read_text(encoding="utf-8")
    assert studio.execute(line)
    assert (tmp_path / "setlists" / "t.toml").read_text(encoding="utf-8") == before


def test_two_songs_cannot_be_given_the_same_title(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    assert "a title names one song" in studio.execute('title 2 "One"')
    assert [title for title, _ in concert(tmp_path)] == ["One", "Two"]


def test_the_files_opening_comment_outlives_the_studio(tmp_path: Path) -> None:
    a_studio(tmp_path).execute("tempo 1 140")
    text = (tmp_path / "setlists" / "t.toml").read_text(encoding="utf-8")
    assert text.startswith("# A test concert.\n")


# ------------------------------------------------------ when the songwriter writes


def test_compose_writes_one_song_and_leaves_the_others_ideas(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    said = studio.execute("compose 2")
    baked = load_setlist(bake_of(tmp_path / "setlists" / "t.toml", fake=True))
    assert [song.title for song in baked.songs] == ["Two"]
    assert baked.provider == "fake" and baked.songs[0].theme
    assert "Two theme" in said and "delivered" in said
    assert studio.state_of(load_spec(tmp_path / "setlists" / "t.toml").songs[0]) == "idea"


def test_compose_all_writes_only_what_is_not_written(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    studio.execute("compose 1")
    said = studio.execute("compose all")
    assert "Two theme" in said and "One theme" not in said
    assert "every song in the concert is written" in studio.execute("compose all")


def test_a_song_already_written_as_asked_is_not_written_again_by_compose(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    studio.execute("compose 1")
    assert "redo 1" in studio.execute("compose 1")


def test_changing_the_music_makes_a_written_song_changed_and_compose_writes_it_again(
    tmp_path: Path,
) -> None:
    studio = a_studio(tmp_path)
    typed(studio, "compose 1", "approve 1")
    assert "compose 1 to write it again" in studio.execute("tempo 1 150")
    assert "changed" in studio.screen()
    assert concert(tmp_path)[0] == ("One", "")
    studio.execute("compose 1")
    baked = load_setlist(studio.bake).songs[0]
    assert baked.bpm == 150.0
    assert len(baked.retired) == len(baked.takes)


def test_renaming_a_song_keeps_what_was_written_for_it(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    typed(studio, "compose 1", 'title 1 "Low Road"')
    assert load_setlist(studio.bake).songs[0].title == "Low Road"
    assert "composed" in studio.screen()


def test_redo_of_one_kind_of_section_keeps_the_rest_and_carries_the_note(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    studio.execute("compose 1")
    before = load_setlist(studio.bake).songs[0]
    said = studio.execute('redo 1 chorus "heavier"')
    after = load_setlist(studio.bake).songs[0]
    choruses = [take.section for take in before.takes if take.briefing.name == "chorus"]
    assert said.count("delivered") == len(choruses) > 0
    assert after.theme == before.theme
    assert [take for take in after.takes if take.section not in choruses] == [
        take for take in before.takes if take.section not in choruses
    ]
    assert len(after.retired) == len(choruses)
    (event,) = [e for e in load_events(tmp_path / "studio.jsonl") if e.kind == "sections_redone"]
    assert event.detail["note"] == "heavier" and event.detail["section"] == "chorus"


def test_redo_names_the_sections_it_can_write_when_asked_for_one_it_cannot(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    studio.execute("compose 1")
    assert "chorus" in studio.execute("redo 1 intro")
    assert "compose 2" in studio.execute("redo 2 chorus")


class Paid:
    """Stands in for the paid songwriter: answers as the floor would, and bills each answer."""

    name = "paid"

    def __init__(self, answers: dict[str, str]) -> None:
        self._inner = BakedProvider(answers)
        self.calls = 0

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        async for event in self._inner.stream(request):
            if event.type == "done":
                yield event.model_copy(
                    update={"usage": Usage(input_tokens=1000, output_tokens=1000)}
                )
            else:
                yield event


def paid_studio(tmp_path: Path) -> tuple[Studio, Paid]:
    spec = load_spec(files(tmp_path).concert)
    plans = [plan_song(song, 132.0, load_styles(ROOT / "styles")) for song in spec.songs]
    provider = Paid(floor_answers(plans, songwriter=True))
    return a_studio(tmp_path, fake=False, connect=lambda: provider), provider


def test_nothing_is_sent_before_yes_and_the_estimate_comes_first(tmp_path: Path) -> None:
    studio, provider = paid_studio(tmp_path)
    said = studio.execute("compose 1")
    assert "claude-opus-5-5" in said and "about $" in said and "Type yes" in said
    assert provider.calls == 0 and not studio.bake.exists()
    assert "delivered" in studio.execute("yes")
    assert provider.calls > 0
    assert load_setlist(studio.bake).provider == "anthropic"


def test_anything_typed_instead_of_yes_leaves_it_undone(tmp_path: Path) -> None:
    studio, provider = paid_studio(tmp_path)
    studio.execute("compose 1")
    assert studio.execute("cost").startswith("left undone")
    assert studio.execute("yes") == "nothing is waiting for a yes"
    assert provider.calls == 0


def test_what_was_spent_is_counted_against_the_sessions_cap(tmp_path: Path) -> None:
    studio, _ = paid_studio(tmp_path)
    typed(studio, "compose 1", "yes")
    said = studio.execute("cost")
    spent = Decimal(said.split("$")[1].split(" ")[0])
    assert spent > 0
    assert f"spent ${spent:.2f} of $2.00" in studio.screen()
    # The sections' cost is stored with their takes; the material's call is the difference.
    sections = Decimal(said.rsplit("$", 1)[1].split(" ")[0])
    assert 0 < sections < spent


def test_with_no_key_the_studio_says_so_and_writes_nothing(tmp_path: Path) -> None:
    studio = a_studio(tmp_path, fake=False)
    studio.execute("compose 1")
    assert "ANTHROPIC_API_KEY is not set; nothing sent" in studio.execute("yes")
    assert not studio.bake.exists()


def test_the_real_bake_is_never_touched_by_the_free_one(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    studio.execute("compose 1")
    assert studio.bake.name == "t.fake.json"
    assert not (tmp_path / "setlists" / "t.json").exists()


# --------------------------------------------------------------- which songs play


def test_a_song_is_approved_only_once_it_is_written_as_asked(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    assert "compose 1" in studio.execute("approve 1")
    assert concert(tmp_path)[0] == ("One", "")
    studio.execute("compose 1")
    assert "approved" in studio.execute("approve 1")
    assert concert(tmp_path)[0] == ("One", str(Verdict.APPROVED))


def test_the_show_plays_the_approved_songs_in_the_concerts_order(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    typed(studio, "new arena", "compose all")
    assert "The show plays: One, Two, Untitled 1." in studio.execute("show")
    typed(studio, "approve 3", "approve 1", "reject 2", "move 3 1")
    assert "The show plays: Untitled 1, One." in studio.execute("show")
    assert "3 songs, 2 in the show" in studio.screen()


def test_a_song_set_aside_leaves_the_show_and_comes_back(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    typed(studio, "compose all", "approve 1", "approve 2", "drop 1")
    assert "The show plays: Two." in studio.execute("show")
    assert "aside" in studio.screen()
    studio.execute("add 1")
    assert "The show plays: One, Two." in studio.execute("show")


def test_a_deleted_song_is_out_of_the_file_and_undo_brings_it_back(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    typed(studio, "compose 1", "delete 1")
    assert [title for title, _ in concert(tmp_path)] == ["Two"]
    studio.execute("undo")
    assert [title for title, _ in concert(tmp_path)] == ["One", "Two"]
    assert "composed" in studio.screen()
    assert studio.execute("undo") == "nothing to take back"


def test_a_concert_keeps_at_least_one_song(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    studio.execute("delete 1")
    assert "at least one song" in studio.execute("delete 1")
    assert len(concert(tmp_path)) == 1


def test_listening_goes_to_the_stage_by_title_and_reads_the_marks_back(tmp_path: Path) -> None:
    heard: list[tuple[Path, str]] = []

    def listen(bake: Path, title: str) -> str:
        heard.append((bake, title))
        return "One: played to its end.\n"

    studio = a_studio(tmp_path, listen=listen)
    assert "compose 1" in studio.execute("listen 1")
    studio.execute("compose 1")
    said = studio.execute("listen 1")
    assert heard == [(studio.bake, "One")]
    assert "played to its end" in said and "approve 1 or reject 1" in said


def test_with_no_stage_listening_and_the_check_say_so(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    studio.execute("compose 1")
    assert "needs a terminal and Live" in studio.execute("listen 1")
    assert "needs Live" in studio.execute("check")


# ------------------------------------------------------------------------ the rest


def test_a_word_nobody_knows_changes_nothing(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    before = (tmp_path / "setlists" / "t.toml").read_text(encoding="utf-8")
    assert studio.execute("explode 1") == "'explode': no such word, type help"
    assert studio.execute('note 1 "unclosed') == "a quote was opened and not closed; nothing done"
    assert studio.execute("   ") == ""
    assert (tmp_path / "setlists" / "t.toml").read_text(encoding="utf-8") == before


def test_help_lists_every_word_the_studio_answers_to(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    listed = studio.execute("help")
    for word in studio._handlers():
        if word != "no":
            assert word in listed, word


def test_a_new_concert_starts_empty_and_becomes_a_file_with_its_first_song(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    assert "empty" in studio.execute('concert new "Friday Night"')
    path = tmp_path / "setlists" / "friday-night.toml"
    assert not path.exists() and "no songs yet" in studio.screen()
    studio.execute("new duo")
    assert load_spec(path).name == "friday-night"
    assert studio.execute("concert") == "concerts: friday-night, t"
    studio.execute("concert open t")
    assert studio.name == "t" and "Two" in studio.screen()
    assert "already exists" in studio.execute("concert new t")
    assert "no concert called" in studio.execute("concert open nowhere")


def test_a_sheet_says_a_song_in_words_before_and_after_it_is_written(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    assert "not written yet" in studio.execute("sheet 1")
    studio.execute("compose 1")
    sheet = studio.execute("sheet 1")
    assert "a riff and two melodies of its own" in sheet
    assert "the songwriter wrote: " in sheet and "the players cover: intro 1" in sheet
    assert "DRM" not in sheet and "deg:" not in sheet


def test_every_decision_is_an_event_in_the_studios_log(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    typed(studio, "new arena", "tempo 1 140", "compose 1", "approve 1", "reject 2", "move 2 1")
    typed(studio, "drop 3", "add 3", "delete 3", "undo")
    kinds = [event.kind for event in load_events(tmp_path / "studio.jsonl")]
    assert kinds == [
        "song_sketched",
        "song_edited",
        "song_composed",
        "song_approved",
        "song_rejected",
        "song_moved",
        "song_set_aside",
        "song_brought_back",
        "song_deleted",
        "change_undone",
    ]


def test_the_screen_is_typed_at_until_quit(tmp_path: Path) -> None:
    studio = a_studio(tmp_path)
    out = io.StringIO()
    assert run_studio(studio, io.StringIO("styles\nquit\ncompose 1\n"), out) == 0
    shown = out.getvalue()
    assert shown.startswith('GARAGEM · STUDIO   concert "t"')
    assert "southern" in shown and shown.rstrip().endswith("the concert is saved as it stands")
    assert not studio.bake.exists()


def test_the_end_of_the_input_ends_the_studio(tmp_path: Path) -> None:
    assert run_studio(a_studio(tmp_path), io.StringIO(""), io.StringIO()) == 0
