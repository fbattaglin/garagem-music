"""The songwriter composing one song, and one section of it again (ADR-030).

The bake's own tests (`test_bake_setlist.py`) cover a whole setlist. These cover what the
studio added: what the songwriter is told about a song, a song as the unit that is paid for,
a second ask for the material, and a section asked for again with a note.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

from garagem.agents import songwriter, structural
from garagem.agents.songwriter import (
    compose_song,
    floor_answers,
    floor_sections,
    place_of,
    plan_song,
    planned_from,
    redo,
    section_message,
    theme_asked_twice,
    theme_fields,
)
from garagem.dsl import place_in, songwriter_brief, theme_brief
from garagem.dsl.schema import NOT_THE_EXAMPLE
from garagem.llm import BakedProvider, LLMProvider, Request, StreamEvent, load_catalog
from garagem.setlist import Song, SongSpec, TakeStatus, load_styles

ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_catalog(ROOT / "config" / "models.toml")
MODEL = structural(CATALOG)
STYLES = load_styles(ROOT / "styles")
BPM = 132.0
SPEC = SongSpec(
    title="Red Dirt", key=2, seconds=120, seed=5, style="southern", notes="huge last chorus"
)
PLANNED = plan_song(SPEC, BPM, STYLES)
QUIET = lambda text: None  # noqa: E731


def guarded(inner: LLMProvider) -> LLMProvider:
    return songwriter.guarded(inner, CATALOG, Decimal("1.00"))


class Counting:
    """A provider that passes everything on and remembers what it was asked."""

    name = "counting"

    def __init__(self, inner: BakedProvider) -> None:
        self._inner = inner
        self.asked: list[str] = []

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.asked.append(request.messages[-1].content)
        async for event in self._inner.stream(request):
            yield event


def composed() -> tuple[Song, Counting]:
    provider = Counting(BakedProvider(floor_answers([PLANNED], songwriter=True), name="fake"))
    song = asyncio.run(compose_song(guarded(provider), MODEL, PLANNED, QUIET))
    return song, provider


# ---------------------------------------------------------- what the songwriter is told


def test_the_style_and_the_notes_reach_the_material_and_every_section() -> None:
    _, provider = composed()
    assert len(provider.asked) == 1 + len(PLANNED.asked)
    for message in provider.asked:
        assert "Style: Anthemic southern-tinged rock" in message
        assert "Notes from the bandleader: huge last chorus" in message


def test_a_song_that_names_no_style_is_asked_for_its_material_as_it_always_was() -> None:
    bare = plan_song(SongSpec(title="Bare", key=4, seconds=90, seed=7), BPM, STYLES)
    fields = theme_fields(bare)
    assert bare.direction == ""
    assert theme_brief(**fields) == theme_brief(
        title="Bare", key=fields["key"], feel="straight8", bpm=BPM, form=fields["form"]
    )


def test_a_section_is_told_where_it_sits_in_the_song() -> None:
    index = next(i for i in PLANNED.asked if PLANNED.form[i].name == "chorus")
    alike = [i for i, section in enumerate(PLANNED.form) if section == PLANNED.form[index]]
    place = place_of(PLANNED, index)
    assert f"plays {len(alike)} times" in place or "plays once" in place
    assert f"of {len(PLANNED.form)}" in place
    assert place in section_message(PLANNED, index, "")


def test_the_first_and_the_last_section_are_told_what_they_open_and_end() -> None:
    form = ["intro", "verse", "chorus", "outro"]
    assert "nothing: it opens the song" in place_in(form, [0])
    assert "nothing: it ends the song" in place_in(form, [3])
    assert "Before it the first time comes verse; after it the last time comes outro" in place_in(
        form, [2]
    )


def test_a_section_asked_with_more_than_its_briefing_is_told_not_to_copy_the_example() -> None:
    section = PLANNED.form[PLANNED.asked[0]]
    assert NOT_THE_EXAMPLE not in songwriter_brief(section, "")
    assert NOT_THE_EXAMPLE in section_message(PLANNED, PLANNED.asked[0], "")


# --------------------------------------------------------------------- one song, whole


def test_a_song_is_composed_with_what_it_was_told_stored_beside_it() -> None:
    song, _ = composed()
    assert (song.style, song.notes) == ("southern", "huge last chorus")
    assert song.theme
    assert [take.section for take in song.takes] == list(PLANNED.asked)
    assert not song.missed


def test_material_the_notation_cannot_read_is_asked_for_once_more() -> None:
    answers = floor_answers([PLANNED], songwriter=True)
    good = answers[theme_brief(**theme_fields(PLANNED))]

    class BadThenGood(Counting):
        async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
            first = not self.asked
            self.asked.append(request.messages[-1].content)
            self._inner = BakedProvider(
                {request.messages[-1].content: "LED oct=4 deg:99=5" if first else good}
            )
            async for event in self._inner.stream(request):
                yield event

    provider = BadThenGood(BakedProvider({}))
    theme, why, twice = asyncio.run(theme_asked_twice(guarded(provider), MODEL, PLANNED))
    assert (theme, why, twice) == (good, "", True)
    assert len(provider.asked) == 2


def test_material_that_arrives_is_not_asked_for_twice() -> None:
    provider = Counting(BakedProvider(floor_answers([PLANNED], songwriter=True)))
    _, _, twice = asyncio.run(theme_asked_twice(guarded(provider), MODEL, PLANNED))
    assert not twice
    assert len(provider.asked) == 1


# ------------------------------------------------------------- one section, again


def choruses(song: Song) -> list[int]:
    plan = planned_from(song, PLANNED.direction)
    return [index for index in plan.asked if song.form[index].name == "chorus"]


def test_asking_again_for_the_chorus_pays_for_the_chorus_and_nothing_else() -> None:
    song, _ = composed()
    plan = planned_from(song, PLANNED.direction)
    indices = choruses(song)
    provider = Counting(BakedProvider(floor_sections(plan, indices, song.theme, "heavier")))
    again, delivered = asyncio.run(
        redo(guarded(provider), MODEL, song, plan, indices, "heavier", QUIET)
    )
    assert delivered == len(indices) == len(provider.asked)
    assert again.theme == song.theme and again.form == song.form
    untouched = [take for take in song.takes if take.section not in indices]
    assert [take for take in again.takes if take.section not in indices] == untouched


def test_the_note_reaches_the_songwriter_as_it_was_said_with_the_songs_own_material() -> None:
    song, _ = composed()
    plan = planned_from(song, PLANNED.direction)
    indices = choruses(song)
    provider = Counting(BakedProvider(floor_sections(plan, indices, song.theme, "heavier")))
    asyncio.run(redo(guarded(provider), MODEL, song, plan, indices, "heavier", QUIET))
    for message in provider.asked:
        assert "The bandleader's note: heavier" in message
        assert "The song's material:" in message
        assert "Style: Anthemic southern-tinged rock" in message


def test_a_replaced_take_is_kept_aside_and_the_new_one_is_unmarked() -> None:
    song, _ = composed()
    index = choruses(song)[0]
    marked = tuple(
        take.model_copy(update={"status": TakeStatus.VETOED}) if take.section == index else take
        for take in song.takes
    )
    song = song.model_copy(update={"takes": marked})
    plan = planned_from(song, PLANNED.direction)
    provider = BakedProvider(floor_sections(plan, [index], song.theme))
    again, _ = asyncio.run(redo(guarded(provider), MODEL, song, plan, [index], "", QUIET))
    new = next(take for take in again.takes if take.section == index)
    assert new.status is TakeStatus.UNMARKED
    assert [take.status for take in again.retired] == [TakeStatus.VETOED]


def test_a_miss_leaves_the_song_as_it_was() -> None:
    song, _ = composed()
    plan = planned_from(song, PLANNED.direction)
    again, delivered = asyncio.run(
        redo(guarded(BakedProvider({})), MODEL, song, plan, choruses(song), "x", QUIET)
    )
    assert delivered == 0
    assert again == song


def test_a_composed_song_is_asked_about_again_on_the_form_it_was_baked_with() -> None:
    song, _ = composed()
    plan = planned_from(song, PLANNED.direction)
    assert (plan.form, plan.endings, plan.asked) == (song.form, song.endings, PLANNED.asked)
