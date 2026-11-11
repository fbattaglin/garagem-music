"""The songwriter: the agent that writes songs before the show (ADR-026, ADR-030).

One model, asked offline. For each song it writes the material first (a riff and two
melodies), then every section with that material in hand. Nothing here runs while the band
plays: a song is composed, stored in a setlist, and played later from disk (ADR-025).

It lived in `scripts/bake_setlist.py` until the studio needed it (ADR-030): composing one
song, or one section of it again with a note, is the same work as baking a whole setlist,
and a script is not something a screen can call. The script is now a thin wrapper.

**It may ask twice, and nothing else in the system may.** P7 forbids a retry on the critical
path. Here nothing is sounding, and asking again is what a person would do.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, TypedDict

from garagem.agents.section import (
    BAKE_MAX_TOKENS,
    request_for,
    songwriter_request_for,
    theme_request_for,
    worth_asking,
)
from garagem.domain import Instrument, Section
from garagem.dsl import (
    SectionStream,
    brief,
    parse_bar_line,
    place_in,
    realise,
    serialize_section,
    songwriter_brief,
    theme_brief,
)
from garagem.dsl.errors import DslError
from garagem.dsl.fragments import StringField
from garagem.engines import Ending, completed, play_section
from garagem.llm import (
    Budget,
    BudgetError,
    CircuitBreaker,
    CircuitOpenError,
    Governor,
    GuardedProvider,
    LLMProvider,
    ModelSpec,
    ProviderError,
    Usage,
    Warmable,
    prices_of,
)
from garagem.setlist import (
    Missed,
    Setlist,
    SetlistSpec,
    Song,
    SongSpec,
    Style,
    Take,
    TakeStatus,
    arranged,
    askable,
    digest,
    direction_for,
)
from garagem.theory import render_key, repair

# What a delivered section cost in Phase 4's paid session: 295 tokens in, 235 out
# (`phase-4-findings.md` §12). The estimate's expected figure; the bound assumes max_tokens.
MEASURED_USAGE: Final = Usage(input_tokens=295, output_tokens=235)
PESSIMISTIC_INPUT_TOKENS: Final = 700

# **Measured on 2026-11-11**, over the 19 sections of the first three songs the studio paid
# for with `claude-opus-5-5`: median 827 tokens in and 3300 out (`phase-9-findings.md` §5).
# The figures this replaces, 425 in and 1286 out, were measured on 2026-09-17 with
# `claude-sonnet-5`, and the studio's first estimates were made with them: it said about
# $0.17 for a song that cost $0.40. The new model thinks before it writes and its thinking is
# billed as output, and the question is longer now that it carries a style and a place.
SONGWRITER_USAGE: Final = Usage(input_tokens=827, output_tokens=3300)
# Derived from the same three songs: $0.115 spent beyond their sections, on three themes.
THEME_USAGE: Final = Usage(input_tokens=700, output_tokens=1800)


def _every_name(*bases: type[Exception]) -> frozenset[str]:
    """Every exception name in these hierarchies.

    `shoot` stores `type(error).__name__`, and what actually arrives is a *subclass*: a
    budget refusal is a `SessionBudgetExceededError`, never a bare `BudgetError`. A guard
    written against the base names would have matched nothing and quietly retried the one
    thing that must not be retried, which is what the test for it caught.
    """
    seen: set[str] = set()
    stack = list(bases)
    while stack:
        cls = stack.pop()
        if cls.__name__ in seen:
            continue
        seen.add(cls.__name__)
        stack.extend(cls.__subclasses__())
    return frozenset(seen)


# One retry, and only here. P7 forbids a retry **on the critical path** — a section about to
# play is failed once and the floor covers it. A bake is planning, nothing is sounding, and
# asking twice is what a person would do. A budget or a breaker refusal is not retried:
# those are the system saying stop, not the model having a bad moment.
NOT_RETRYABLE: Final = _every_name(BudgetError, CircuitOpenError)


# ------------------------------------------------------------------------------- the plan


@dataclass(frozen=True, slots=True)
class Planned:
    """One song of the spec, arranged, with the sections the bake will ask about."""

    spec: SongSpec
    form: tuple[Section, ...]
    endings: tuple[Ending, ...]
    asked: tuple[int, ...]
    # What kind of song it is, in the words the songwriter is given (ADR-030): the style's
    # direction and the bandleader's notes. Empty for a song that names neither.
    direction: str = ""


def plan_song(song: SongSpec, bpm: float, styles: Mapping[str, Style] | None = None) -> Planned:
    form, endings = arranged(song, bpm)
    return Planned(
        song,
        form,
        endings,
        askable(form, worth_asking),
        direction_for(song, dict(styles or {})),
    )


def plan(spec: SetlistSpec, bpm: float, styles: Mapping[str, Style] | None = None) -> list[Planned]:
    return [plan_song(song, bpm, styles) for song in spec.songs]


def planned_from(song: Song, direction: str = "") -> Planned:
    """A composed song as the plan it was composed from, to ask about a section of it again.

    The form is the stored one, never arranged again: the take being replaced answers a
    briefing of the song that was baked, even after the arranger has changed.
    """
    spec = SongSpec(
        title=song.title,
        key=song.key,
        scale=song.scale,
        feel=song.feel,
        seconds=song.seconds,
        seed=song.seed,
        bpm=song.bpm,
        style=song.style,
        notes=song.notes,
    )
    return Planned(spec, song.form, song.endings, askable(song.form, worth_asking), direction)


def place_of(song: Planned, index: int) -> str:
    """Where the section at `index` sits in its song, every place its take will play."""
    alike = [at for at, section in enumerate(song.form) if section == song.form[index]]
    return place_in([section.name for section in song.form], alike)


def section_message(song: Planned, index: int, theme: str, note: str = "") -> str:
    """The songwriter's question about one section, exactly as the request carries it.

    One function for the request and for the floor's answer to it, because `BakedProvider`
    finds an answer by this text and a word of difference is a miss.
    """
    return songwriter_brief(
        song.form[index],
        theme,
        direction=song.direction,
        place=place_of(song, index),
        note=note,
    )


def floor_answers(planned: list[Planned], *, songwriter: bool) -> dict[str, str]:
    """Every question the bake will ask, answered by the floor: what `--fake` bakes.

    In songwriter mode that is two questions per song — the theme, then each section with
    the theme in its message — and the answers are written in the bake's own notation
    (`pitched=True`), so a fake bake exercises the `deg:` and `LED` path end to end before
    a penny is spent. `BakedProvider` matches on the last user message, so these keys have
    to be the exact briefs the requests will carry.
    """
    if not songwriter:
        return {
            brief(song.form[index]): serialize_section(
                play_section(song.form[index], song.spec.seed + index)
            )
            for song in planned
            for index in song.asked
        }

    answers: dict[str, str] = {}
    for song in planned:
        theme = floor_theme(song)
        answers[theme_brief(**theme_fields(song))] = theme
        answers |= floor_sections(song, song.asked, theme)
    return answers


def floor_sections(
    song: Planned, indices: Sequence[int], theme: str, note: str = ""
) -> dict[str, str]:
    """The floor's answer to the songwriter's question about each of these sections."""
    return {
        section_message(song, index, theme, note): serialize_section(
            play_section(song.form[index], song.spec.seed + index), pitched=True
        )
        for index in indices
    }


class ThemeFields(TypedDict):
    """What the theme call is told about a song. Typed, because two callers splat it and a
    field that quietly changed name would make `--fake` miss every theme by a string."""

    title: str
    key: str
    feel: str
    bpm: float
    form: str
    direction: str


def theme_fields(song: Planned) -> ThemeFields:
    """What the theme call is told about a song: enough to write material for it."""
    return {
        "title": song.spec.title,
        "key": render_key(song.spec.key, song.spec.scale),
        "feel": str(song.spec.feel),
        "bpm": song.form[0].bpm,
        "form": " ".join(section.name for section in song.form),
        "direction": song.direction,
    }


def floor_theme(song: Planned) -> str:
    """The floor's own material: the riff, then two bars of verse melody and of chorus melody.

    Only `--fake` uses it. It exists so the fake bake's theme is the shape a real one will
    be — six bar lines in `SYSTEM_THEME`'s order, no SEC and no CHD — rather than a placeholder
    that would let the playback path pass on something the model will never send. The riff
    comes from the song's loudest section; each melody from the first section of its kind,
    or from the loudest when the song has none.
    """
    loudest = max(song.asked, key=lambda index: song.form[index].dyn)

    def first(kind: str) -> int:
        return next((i for i in song.asked if song.form[i].name == kind), loudest)

    def lines_of(index: int, tag: str) -> list[str]:
        score = play_section(song.form[index], song.spec.seed + index)
        lines = serialize_section(score, pitched=True).splitlines()
        return [line for line in lines if line.split(maxsplit=1)[:1] == [tag]][:2]

    bass, lead = str(Instrument.BASS), str(Instrument.LEAD)
    return "\n".join(
        [
            *lines_of(loudest, bass),
            *lines_of(first("verse"), lead),
            *lines_of(first("chorus"), lead),
        ]
    )


def estimate(
    model: ModelSpec, calls: int, *, songwriter: bool = False, songs: int = 0
) -> tuple[Decimal, Decimal]:
    """(expected, at most): the usage per call, and every call filling max_tokens.

    In songwriter mode the per-section figure is an estimate rather than a measurement and
    says so at the constant; the bound assumes `BAKE_MAX_TOKENS`, which is four times the
    live path's, because that is what the request actually allows.
    """
    if not songwriter:
        expected = model.price.cost_of(MEASURED_USAGE) * calls
        bound = model.price.cost_of(
            Usage(input_tokens=PESSIMISTIC_INPUT_TOKENS, output_tokens=model.max_tokens)
        )
        return expected, bound * calls

    expected = (
        model.price.cost_of(SONGWRITER_USAGE) * calls + model.price.cost_of(THEME_USAGE) * songs
    )
    ceiling = model.price.cost_of(
        Usage(input_tokens=PESSIMISTIC_INPUT_TOKENS * 2, output_tokens=BAKE_MAX_TOKENS)
    )
    return expected, ceiling * (calls + songs)


# ---------------------------------------------------------------------------- one section


async def theme_shot(provider: LLMProvider, model: ModelSpec, song: Planned) -> tuple[str, str]:
    """One call for the song's material (ADR-026). `(theme, why it is empty)`.

    A song without a theme still bakes: its sections are written with nothing above the
    briefing, the floor plays its lead, and the music degrades rather than stopping — P2,
    one level up.

    **Every line is parsed before the theme is kept.** A theme is pasted into every section
    prompt of the song, so material the notation cannot read would be repeated into every
    call and paid for each time.

    **And the reason comes back with it.** The first version returned a bare string, so when
    a theme went missing in the second paid bake there was nothing to read: the diagnosis
    cost another call. A fallback that cannot say why it fell back is a fallback nobody can
    fix (`phase-6-findings.md` §7).
    """
    request = theme_request_for(model, **theme_fields(song))
    decoder = StringField()

    async def drain() -> None:
        async for event in provider.stream(request):
            if event.type == "tool_input_delta":
                decoder.feed(event.fragment)

    try:
        await asyncio.wait_for(drain(), timeout=request.deadline_s)
    except TimeoutError:
        return "", f"deadline_missed after {request.deadline_s:.0f}s"
    except (ProviderError, DslError, CircuitOpenError, BudgetError) as error:
        return "", f"{type(error).__name__}: {str(error)[:120]}"

    lines = [line.strip() for line in decoder.value().splitlines() if line.strip()]
    if not lines:
        return "", "the model wrote nothing"
    for line in lines:
        try:
            parse_bar_line(line)
        except DslError as error:
            return "", str(error)[:160]
    return "\n".join(lines), ""


async def theme_asked_twice(
    provider: LLMProvider, model: ModelSpec, song: Planned
) -> tuple[str, str, bool]:
    """The song's material, asked for once more if the first answer could not be used.

    `(theme, why it is empty, whether it was asked twice)`. The show's bake lost "Low
    Ceiling"'s theme to one line the parser refused, and its seven sections were then written
    with nothing in hand (`phase-8-findings.md` §6). A section was already asked for twice;
    the material every section is written from was not. A budget or a breaker refusal is
    still the system saying stop, and is not asked again.
    """
    theme, why = await theme_shot(provider, model, song)
    if theme or why.split(":", 1)[0] in NOT_RETRYABLE:
        return theme, why, False
    theme, why = await theme_shot(provider, model, song)
    return theme, why, True


async def shoot(
    provider: LLMProvider,
    model: ModelSpec,
    section: Section,
    index: int,
    seed: int,
    *,
    theme: str | None = None,
    message: str | None = None,
) -> Take | Missed:
    """The producer's call for one section, once, inside its deadline. Never raises.

    `theme` switches the whole question: `None` is the live path's request, frozen by
    ADR-025 and used by `--plain` and by `--rebake-vetoed`; a string (empty included) is
    the songwriter's, which asks for pitches and for the material to come back.

    `message` is the songwriter's question already worded (`section_message`), with the
    song's direction, the section's place and a note in it. Without one the question is the
    bare briefing under the theme, as every bake before ADR-030 asked it.
    """
    request = (
        request_for(section, model)
        if theme is None
        else songwriter_request_for(section, model, theme=theme, message=message)
    )
    stream = SectionStream(section)
    usage = Usage()

    async def drain() -> None:
        nonlocal usage
        async for event in provider.stream(request):
            stream.feed(event)
            if event.type == "done":
                usage = event.usage

    try:
        await asyncio.wait_for(drain(), timeout=request.deadline_s)
    except TimeoutError:
        return Missed(section=index, reason="deadline_missed", detail=f"{request.deadline_s:.2f}s")
    except (ProviderError, DslError, CircuitOpenError, BudgetError) as error:
        return Missed(section=index, reason=type(error).__name__, detail=str(error)[:200])

    dsl = stream.text
    score = realise(stream.result(), seed)
    if not score.parts:
        return Missed(section=index, reason="nothing_parsed", dsl=dsl)
    parts = ",".join(sorted(str(instrument) for instrument in score.instruments()))
    repaired, left = repair(completed(score))
    if left:
        rules = ",".join(sorted({violation.rule for violation in left}))
        return Missed(section=index, reason="irreparable", detail=rules, dsl=dsl)
    return Take(
        section=index,
        briefing=section,
        seed=seed,
        model=model.id,
        dsl=dsl,
        parts=parts,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=model.price.cost_of(usage),
        digest=digest(repaired),
    )


async def asked_twice(
    provider: LLMProvider,
    model: ModelSpec,
    section: Section,
    index: int,
    seed: int,
    *,
    theme: str | None,
    message: str | None = None,
) -> tuple[Take | Missed, bool]:
    """One section, and one more attempt if the first came back unusable. (outcome, retried).

    The one place in this system that asks again, and the reason it is allowed is that
    nothing is playing: P7 forbids a retry **on the critical path**, where a second call
    would cost the bar it was for. Here a refusal costs a section of a setlist nobody is
    listening to yet, and a person would obviously ask again.
    """
    outcome = await shoot(provider, model, section, index, seed, theme=theme, message=message)
    if isinstance(outcome, Take) or outcome.reason in NOT_RETRYABLE:
        return outcome, False
    again = await shoot(provider, model, section, index, seed, theme=theme, message=message)
    return again, True


async def bake(
    provider: LLMProvider,
    model: ModelSpec,
    planned: list[Planned],
    emit: Callable[[str], object] = sys.stderr.write,
    *,
    songwriter: bool = False,
) -> list[Song]:
    """Every song, one call at a time, in play order, on one event loop.

    In songwriter mode each song takes its theme first and every section of it is then
    written with that theme in hand (ADR-026), which is what makes a song come back to
    something instead of being eight unrelated grooves.
    """
    if isinstance(provider, Warmable):
        with suppress(ProviderError):
            await provider.warm()
    return [
        await compose_song(provider, model, song, emit, songwriter=songwriter, label=f"song {n}")
        for n, song in enumerate(planned, start=1)
    ]


async def compose_song(
    provider: LLMProvider,
    model: ModelSpec,
    song: Planned,
    emit: Callable[[str], object] = sys.stderr.write,
    *,
    songwriter: bool = True,
    label: str = "song",
) -> Song:
    """One song, whole: its material, then every section worth asking about (ADR-030).

    What a bake does for each song, and what the studio does for one. A song is the unit a
    person asks for, listens to and judges, so it is the unit that is composed and paid for.
    """
    takes: list[Take] = []
    missed: list[Missed] = []
    theme = ""
    if songwriter:
        theme, why, twice = await theme_asked_twice(provider, model, song)
        told = f"{len(theme.splitlines())} bar lines" if theme else f"missed: {why}"
        emit(f"  {label} theme   {told}{' (asked twice)' if twice else ''}\n")
    for index in song.asked:
        section = song.form[index]
        outcome, retried = await asked_twice(
            provider,
            model,
            section,
            index,
            song.spec.seed + index,
            theme=theme if songwriter else None,
            message=section_message(song, index, theme) if songwriter else None,
        )
        if isinstance(outcome, Take):
            takes.append(outcome)
            verdict = "delivered"
        else:
            missed.append(outcome)
            verdict = f"missed: {outcome.reason}"
        where = f"{label} section {index + 1:>2}/{len(song.form)}"
        emit(f"  {where} {section.name:<7} {verdict}{' (asked twice)' if retried else ''}\n")
    return Song(
        title=song.spec.title,
        key=song.spec.key,
        scale=song.spec.scale,
        feel=song.spec.feel,
        seconds=song.spec.seconds,
        seed=song.spec.seed,
        form=song.form,
        endings=song.endings,
        theme=theme,
        style=song.spec.style,
        notes=song.spec.notes,
        takes=tuple(takes),
        missed=tuple(missed),
    )


async def redo(
    provider: LLMProvider,
    model: ModelSpec,
    song: Song,
    planned: Planned,
    indices: Sequence[int],
    note: str = "",
    emit: Callable[[str], object] = sys.stderr.write,
) -> tuple[Song, int]:
    """Ask again for some of a song's sections, with its own material in hand. (song, delivered).

    The song keeps its theme, its form and every other take: only the sections named are paid
    for. A delivered take replaces the one that was there, unmarked, and the old one is
    retired with the song rather than deleted, as a vetoed take is. A miss changes nothing.
    A section the first bake missed can be asked for here too, and then it stops being one.

    `note` is the bandleader's, in words, and it reaches the question as it was said.
    """
    takes = {take.section: take for take in song.takes}
    missed = {miss.section: miss for miss in song.missed}
    retired = list(song.retired)
    delivered = 0
    for index in indices:
        section = song.form[index]
        outcome, _ = await asked_twice(
            provider,
            model,
            section,
            index,
            song.seed + index,
            theme=song.theme,
            message=section_message(planned, index, song.theme, note),
        )
        where = f"section {index + 1:>2}/{len(song.form)} {section.name:<7}"
        if isinstance(outcome, Take):
            if index in takes:
                retired.append(takes[index])
            takes[index] = outcome
            missed.pop(index, None)
            delivered += 1
            emit(f"  {where} delivered\n")
        else:
            emit(f"  {where} missed: {outcome.reason}, left as it was\n")
    return (
        song.model_copy(
            update={
                "takes": tuple(takes[index] for index in sorted(takes)),
                "missed": tuple(missed[index] for index in sorted(missed)),
                "retired": tuple(retired),
            }
        ),
        delivered,
    )


# ---------------------------------------------------------------------- asking again


async def rebake(
    provider: LLMProvider,
    model: ModelSpec,
    setlist: Setlist,
    emit: Callable[[str], object] = sys.stderr.write,
) -> tuple[Setlist, int, int]:
    """Ask again for every vetoed take's briefing. (setlist, delivered, still vetoed).

    A delivered take replaces the vetoed one, unmarked, and the vetoed take is retired with the
    song rather than deleted. A miss leaves the veto standing, so the floor keeps that briefing.

    **A song that has material is asked with it** (ADR-030). Until then a vetoed take was
    asked for again through the live prompt, with no theme, no pitches and no lead: the
    replacement was a lesser thing than what it replaced. A song baked `--plain` has no
    material and is still asked the plain way.
    """
    delivered = missed = 0
    songs = []
    for number, song in enumerate(setlist.songs, start=1):
        takes: list[Take] = []
        retired = list(song.retired)
        for take in song.takes:
            if take.status is not TakeStatus.VETOED:
                takes.append(take)
                continue
            outcome = await shoot(
                provider, model, take.briefing, take.section, take.seed, theme=song.theme or None
            )
            where = f"song {number} section {take.section + 1:>2}/{len(song.form)}"
            if isinstance(outcome, Take):
                takes.append(outcome)
                retired.append(take)
                delivered += 1
                emit(f"  {where} {take.briefing.name:<7} delivered\n")
            else:
                takes.append(take)
                missed += 1
                emit(f"  {where} {take.briefing.name:<7} missed: {outcome.reason}, still vetoed\n")
        songs.append(song.model_copy(update={"takes": tuple(takes), "retired": tuple(retired)}))
    return setlist.model_copy(update={"songs": tuple(songs)}), delivered, missed


def guarded(inner: LLMProvider, catalog: list[ModelSpec], cap_usd: Decimal) -> GuardedProvider:
    return GuardedProvider(
        inner,
        governor=Governor(
            Budget(
                session_usd=cap_usd,
                per_minute_usd=cap_usd,
                max_in_flight=1,
                prices=prices_of(catalog),
            )
        ),
        breaker=CircuitBreaker(),
    )


async def themes(
    provider: LLMProvider, model: ModelSpec, planned: list[Planned]
) -> list[tuple[Planned, tuple[str, str]]]:
    """Every song's material, on **one** event loop.

    One loop, not one per song: the adapter's HTTP client binds to the loop it was first
    used on, and `asyncio.run` per song closed it under the next call — "Event loop is
    closed" on the second theme. `bake` had it right and this did not.
    """
    if isinstance(provider, Warmable):
        with suppress(ProviderError):
            await provider.warm()
    return [(song, (await theme_shot(provider, model, song))) for song in planned]
