"""Bakes a setlist: the model writes each song's sections once, online, into a file.

    uv run python scripts/bake_setlist.py setlists/first.toml         # estimate; spends nothing
    uv run python scripts/bake_setlist.py setlists/first.toml --yes   # bakes; spends real money
    uv run python scripts/bake_setlist.py setlists/first.toml --fake  # the floor's DSL; free
    uv run python scripts/bake_setlist.py setlists/first.toml --rebake-vetoed --yes

Setlist Mode's first half (ADR-000 §7, ADR-024): connected pre-production, so the performance
can be disconnected. `jam.py --setlist setlists/first.json` plays what this writes, from disk.

**Each song is arranged exactly as `jam.py` arranges one**, at the Set's tempo from
`session.toml`, and the form is stored with the takes. The setlist plays the song that was
baked, even after the arranger changes.

**One call per distinct briefing, and only where the performance would ask** (`askable`).
A repeated verse briefed like the first reuses its take (ADR-000's P6), and a section too short
to be worth asking is not asked here either. The floor plays it, as live.

**Every call is the producer's own call.** The same request, the same deadline, and no retry
(P7). A section that misses its deadline, fails, or comes back unplayable is stored as missed
with its reason, and the floor plays it. Asking again is a planning decision, and curation is
where it is taken (Stage 3).

**Nothing goes out without `--yes`.** The estimate counts the calls at the usage Phase 4
measured, beside a pessimistic bound. The bake has its own cap, `--cap-usd`: pre-production is
not a performance, and it must not share the performance's budget.

**`--fake` bakes the floor's own DSL as if the model had written it.** No network, no key, no
money, and a file `jam.py` and `rehearse_session.py` play the same way. It exists to check the
playback path before paying, and it says so in the file (`provider = "fake"`).

**An existing bake is never overwritten**, except by `--rebake-vetoed`, which touches only the
takes curation vetoed (`scripts/curate_setlist.py`). Each is asked for again, once. A delivered
take replaces it, unmarked, and the vetoed one is kept in the song's `retired`. A miss leaves the
veto standing, and the floor keeps playing that briefing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final, TypedDict

from garagem.agents import (
    BAKE_MAX_TOKENS,
    by_id,
    request_for,
    songwriter_request_for,
    structural,
    theme_request_for,
    worth_asking,
)
from garagem.daw import load_session
from garagem.domain import Instrument, Section
from garagem.dsl import (
    SectionStream,
    brief,
    parse_bar_line,
    realise,
    serialize_section,
    songwriter_brief,
    theme_brief,
)
from garagem.dsl.errors import DslError
from garagem.dsl.fragments import StringField
from garagem.engines import Ending, completed, play_section
from garagem.llm import (
    AnthropicAdapter,
    BakedProvider,
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
    load_catalog,
    prices_of,
)
from garagem.setlist import (
    Missed,
    Setlist,
    SetlistError,
    SetlistSpec,
    Song,
    SongSpec,
    Take,
    TakeStatus,
    arranged,
    askable,
    digest,
    load_setlist,
    load_spec,
    save_setlist,
)
from garagem.theory import render_key, repair

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "session.toml"
CATALOG = ROOT / "config" / "models.toml"

DEFAULT_CAP_USD: Final = Decimal("1.00")
# What a delivered section cost in Phase 4's paid session: 295 tokens in, 235 out
# (`phase-4-findings.md` §12). The estimate's expected figure; the bound assumes max_tokens.
MEASURED_USAGE: Final = Usage(input_tokens=295, output_tokens=235)
PESSIMISTIC_INPUT_TOKENS: Final = 700

# **Measured on 2026-09-17**, over the 18 sections of the first songwriter bake: median 425
# tokens in and 1286 out (`phase-6-findings.md` §5). The guess this replaces was 900 in and
# 1000 out, which came in 17% under what the bake actually spent — the sections are longer
# than the shape of the answer suggested, and the input is shorter because the cached
# system block is not counted twice.
SONGWRITER_USAGE: Final = Usage(input_tokens=425, output_tokens=1286)
# Derived from the same bake: $0.0152 for three themes, at this model's prices.
THEME_USAGE: Final = Usage(input_tokens=700, output_tokens=300)


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


def plan(spec: SetlistSpec, bpm: float) -> list[Planned]:
    out = []
    for song in spec.songs:
        form, endings = arranged(song, bpm)
        out.append(Planned(song, form, endings, askable(form, worth_asking)))
    return out


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
        for index in song.asked:
            section = song.form[index]
            answers[songwriter_brief(section, theme)] = serialize_section(
                play_section(section, song.spec.seed + index), pitched=True
            )
    return answers


class ThemeFields(TypedDict):
    """What the theme call is told about a song. Typed, because two callers splat it and a
    field that quietly changed name would make `--fake` miss every theme by a string."""

    title: str
    key: str
    feel: str
    bpm: float
    form: str


def theme_fields(song: Planned) -> ThemeFields:
    """What the theme call is told about a song: enough to write material for it."""
    return {
        "title": song.spec.title,
        "key": render_key(song.spec.key, song.spec.scale),
        "feel": str(song.spec.feel),
        "bpm": song.form[0].bpm,
        "form": " ".join(section.name for section in song.form),
    }


def floor_theme(song: Planned) -> str:
    """The floor's own material: two bars of bass and lead from the song's first chorus.

    Only `--fake` uses it. It exists so the fake bake's theme is the shape a real one will
    be — bar lines, no SEC and no CHD — rather than a placeholder that would let the
    playback path pass on something the model will never send.
    """
    loudest = max(song.asked, key=lambda index: song.form[index].dyn)
    section = song.form[loudest]
    score = play_section(section, song.spec.seed + loudest)
    lines = serialize_section(score, pitched=True).splitlines()
    tags = (str(Instrument.BASS), str(Instrument.LEAD))
    kept: dict[str, list[str]] = {tag: [] for tag in tags}
    for line in lines:
        tag = line.split(maxsplit=1)[0] if line.strip() else ""
        if tag in kept and len(kept[tag]) < 2:
            kept[tag].append(line)
    return "\n".join(line for tag in tags for line in kept[tag])


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


async def shoot(
    provider: LLMProvider,
    model: ModelSpec,
    section: Section,
    index: int,
    seed: int,
    *,
    theme: str | None = None,
) -> Take | Missed:
    """The producer's call for one section, once, inside its deadline. Never raises.

    `theme` switches the whole question: `None` is the live path's request, frozen by
    ADR-025 and used by `--plain` and by `--rebake-vetoed`; a string (empty included) is
    the songwriter's, which asks for pitches and for the material to come back.
    """
    request = (
        request_for(section, model)
        if theme is None
        else songwriter_request_for(section, model, theme=theme)
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
) -> tuple[Take | Missed, bool]:
    """One section, and one more attempt if the first came back unusable. (outcome, retried).

    The one place in this system that asks again, and the reason it is allowed is that
    nothing is playing: P7 forbids a retry **on the critical path**, where a second call
    would cost the bar it was for. Here a refusal costs a section of a setlist nobody is
    listening to yet, and a person would obviously ask again.
    """
    outcome = await shoot(provider, model, section, index, seed, theme=theme)
    if isinstance(outcome, Take) or outcome.reason in NOT_RETRYABLE:
        return outcome, False
    return await shoot(provider, model, section, index, seed, theme=theme), True


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
    songs: list[Song] = []
    for number, song in enumerate(planned, start=1):
        takes: list[Take] = []
        missed: list[Missed] = []
        theme = ""
        if songwriter:
            theme, why = await theme_shot(provider, model, song)
            told = f"{len(theme.splitlines())} bar lines" if theme else f"missed: {why}"
            emit(f"  song {number} theme   {told}\n")
        for index in song.asked:
            section = song.form[index]
            outcome, retried = await asked_twice(
                provider,
                model,
                section,
                index,
                song.spec.seed + index,
                theme=theme if songwriter else None,
            )
            if isinstance(outcome, Take):
                takes.append(outcome)
                verdict = "delivered"
            else:
                missed.append(outcome)
                verdict = f"missed: {outcome.reason}"
            where = f"song {number} section {index + 1:>2}/{len(song.form)}"
            emit(f"  {where} {section.name:<7} {verdict}{' (asked twice)' if retried else ''}\n")
        songs.append(
            Song(
                title=song.spec.title,
                key=song.spec.key,
                scale=song.spec.scale,
                feel=song.spec.feel,
                seconds=song.spec.seconds,
                seed=song.spec.seed,
                form=song.form,
                endings=song.endings,
                theme=theme,
                takes=tuple(takes),
                missed=tuple(missed),
            )
        )
    return songs


# ----------------------------------------------------------------------------------- main


async def rebake(
    provider: LLMProvider,
    model: ModelSpec,
    setlist: Setlist,
    emit: Callable[[str], object] = sys.stderr.write,
) -> tuple[Setlist, int, int]:
    """Ask again for every vetoed take's briefing. (setlist, delivered, still vetoed).

    A delivered take replaces the vetoed one, unmarked, and the vetoed take is retired with the
    song rather than deleted. A miss leaves the veto standing, so the floor keeps that briefing.
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
            outcome = await shoot(provider, model, take.briefing, take.section, take.seed)
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


def _named_after(out: Path, spelled: str) -> str:
    """A setlist is named after the file it lands in, whatever the spec called it.

    **The name is a setlist's identity in the event log, not a label.** `jam.py` writes it with
    every mark, and `curate_setlist.py` joins marks to takes by it, so two setlists sharing one
    cannot have their sessions told apart — which `setlists/songwriter.toml` says in its own
    header is why it has a name of its own.

    `--out` broke that in Phase 7: baking `songwriter.toml` into `arrangement.json` produced a
    second setlist called `songwriter`, and its curation only escaped the first one's marks
    because no take body coincided (`phase-7-findings.md` §6). The file is the thing a person
    passes to `jam.py`, so the file is what the name follows.
    """
    if out.name.endswith(".fake.json"):
        return out.name[: -len(".fake.json")]
    return out.stem if out.stem != spelled else spelled


def paid_provider(
    yes: bool,
    model: ModelSpec,
    calls: int,
    cap_usd: Decimal,
    *,
    songwriter: bool = False,
    songs: int = 0,
) -> LLMProvider | int:
    """The real adapter once `--yes` is given, or the exit code to stop with."""
    expected, bound = estimate(model, calls, songwriter=songwriter, songs=songs)
    basis = (
        "at the usage the first songwriter bake measured"
        if songwriter
        else "at the usage Phase 4 measured"
    )
    sys.stderr.write(
        f"expected ~${expected:.2f} {basis}; at most ~${bound:.2f} "
        f"if every call filled max_tokens; capped at ${cap_usd}\n"
    )
    if not yes:
        sys.stderr.write("nothing sent. Re-run with --yes.\n")
        return 0
    try:
        return AnthropicAdapter.from_env()
    except ProviderError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="setlists/<name>.toml")
    parser.add_argument("--out", type=Path, help="default: the spec's path, .json or .fake.json")
    parser.add_argument("--yes", action="store_true", help="actually bake; spends money")
    parser.add_argument("--fake", action="store_true", help="bake the floor's DSL; free, offline")
    parser.add_argument(
        "--plain",
        action="store_true",
        help="the live path's prompt, with no theme and no pitches (the bake before ADR-026)",
    )
    parser.add_argument(
        "--themes-only",
        action="store_true",
        help="ask only for each song's material and print it; writes no file, costs a cent",
    )
    parser.add_argument(
        "--rebake-vetoed",
        action="store_true",
        help="ask again for the vetoed takes of the existing bake, in place",
    )
    parser.add_argument("--cap-usd", type=Decimal, default=DEFAULT_CAP_USD)
    args = parser.parse_args()

    # A fake bake never takes the real one's name: that file must stay free for the paid bake.
    out: Path = args.out or args.spec.with_suffix(".fake.json" if args.fake else ".json")
    catalog = load_catalog(CATALOG)
    if args.rebake_vetoed:
        return main_rebake(args, out, catalog)

    try:
        spec = load_spec(args.spec)
    except SetlistError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    if out.exists():
        sys.stderr.write(f"{out} already exists and may hold curation. Move it, or pass --out.\n")
        return 1

    bpm = load_session(SESSION).tempo_bpm
    model = structural(catalog)
    planned = plan(spec, bpm)
    calls = sum(len(song.asked) for song in planned)
    sections = sum(len(song.form) for song in planned)
    minutes = sum(s.total_seconds() for song in planned for s in song.form) / 60

    songwriter = not args.plain
    if args.themes_only and args.plain:
        sys.stderr.write("--themes-only is the songwriter's first stage; --plain has none.\n")
        return 1

    for number, song in enumerate(planned, start=1):
        seconds = sum(section.total_seconds() for section in song.form)
        sys.stderr.write(
            f"{number}. {song.spec.title}: {song.spec.feel}, key {song.spec.key} "
            f"{song.spec.scale}, {seconds:.0f}s, {len(song.form)} sections, "
            f"{len(song.asked)} to ask\n"
        )
    themes = len(planned) if songwriter else 0
    sys.stderr.write(
        f"{len(planned)} songs, {minutes:.1f} minutes at {bpm:g} BPM, {sections} sections: "
        f"{calls + themes} calls to {model.id}"
        + (f" ({themes} themes, {calls} sections)\n" if songwriter else "\n")
    )

    inner: LLMProvider
    if args.fake:
        inner = BakedProvider(floor_answers(planned, songwriter=songwriter), name="fake")
        provider_name = "fake"
        sys.stderr.write("baking the floor's own DSL: no network, no money\n")
    else:
        paid = paid_provider(
            args.yes, model, calls, args.cap_usd, songwriter=songwriter, songs=themes
        )
        if isinstance(paid, int):
            return paid
        inner, provider_name = paid, "anthropic"

    provider = guarded(inner, catalog, args.cap_usd)
    if args.themes_only:
        return main_themes(provider, model, planned)
    songs = asyncio.run(bake(provider, model, planned, songwriter=songwriter))
    setlist = Setlist(
        name=_named_after(out, spec.name),
        provider=provider_name,
        model=model.id,
        baked_on=datetime.now(UTC).date(),
        bpm=bpm,
        songs=tuple(songs),
    )
    save_setlist(setlist, out)

    delivered = sum(len(song.takes) for song in songs)
    spent = provider.governor.snapshot()
    sys.stderr.write(
        f"{delivered} of {calls} delivered into {out}; spent ${spent.spent_usd:.4f}"
        + (f" (${spent.estimated_usd:.4f} estimated)" if spent.estimated_usd else "")
        + "\n"
    )
    for baked in songs:
        for miss in baked.missed:
            sys.stderr.write(f"  {baked.title}, section {miss.section + 1}: {miss.reason}\n")
    return 0


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


def main_themes(provider: LLMProvider, model: ModelSpec, planned: list[Planned]) -> int:
    """`--themes-only`: the first stage alone, printed, so the material can be read before
    the sections are paid for.

    The theme is what every section of a song is written against, so a bad one is paid for
    eighteen times over. Three calls cost about a cent; the bake that follows costs thirty.
    """
    written = asyncio.run(themes(provider, model, planned))
    for number, (song, (theme, why)) in enumerate(written, 1):
        sys.stderr.write(f"\n{number}. {song.spec.title} ({song.spec.feel}):\n")
        sys.stderr.write(f"{theme or f'  missed: {why}'}\n")
    spent = provider.governor.snapshot() if isinstance(provider, GuardedProvider) else None
    if spent is not None:
        sys.stderr.write(f"\nno file written; spent ${spent.spent_usd:.4f}\n")
    return 0


def main_rebake(args: argparse.Namespace, path: Path, catalog: list[ModelSpec]) -> int:
    """`--rebake-vetoed`: the one mode that rewrites an existing bake, and only its vetoes."""
    try:
        setlist = load_setlist(path)
    except SetlistError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    vetoed = [
        take for song in setlist.songs for take in song.takes if take.status is TakeStatus.VETOED
    ]
    model = by_id(catalog, setlist.model)
    sys.stderr.write(f"{len(vetoed)} vetoed take(s) in {path} to ask {model.id} for again\n")
    if not vetoed:
        return 0
    inner: LLMProvider
    if args.fake:
        answers = {
            brief(take.briefing): serialize_section(play_section(take.briefing, take.seed))
            for take in vetoed
        }
        inner = BakedProvider(answers, name="fake")
    else:
        paid = paid_provider(args.yes, model, len(vetoed), args.cap_usd)
        if isinstance(paid, int):
            return paid
        inner = paid
    provider = guarded(inner, catalog, args.cap_usd)
    rebaked, delivered, missed = asyncio.run(rebake(provider, model, setlist))
    save_setlist(rebaked, path)
    spent = provider.governor.snapshot()
    sys.stderr.write(
        f"{delivered} replaced, {missed} still vetoed, in {path}; spent ${spent.spent_usd:.4f}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
