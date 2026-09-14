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
from typing import Final

from garagem.agents import by_id, request_for, structural, worth_asking
from garagem.daw import load_session
from garagem.domain import Section
from garagem.dsl import SectionStream, brief, realise, serialize_section
from garagem.dsl.errors import DslError
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
from garagem.theory import repair

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "session.toml"
CATALOG = ROOT / "config" / "models.toml"

DEFAULT_CAP_USD: Final = Decimal("1.00")
# What a delivered section cost in Phase 4's paid session: 295 tokens in, 235 out
# (`phase-4-findings.md` §12). The estimate's expected figure; the bound assumes max_tokens.
MEASURED_USAGE: Final = Usage(input_tokens=295, output_tokens=235)
PESSIMISTIC_INPUT_TOKENS: Final = 700


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


def floor_answers(planned: list[Planned]) -> dict[str, str]:
    """Every asked briefing answered with the floor's own DSL: what `--fake` bakes."""
    return {
        brief(song.form[index]): serialize_section(
            play_section(song.form[index], song.spec.seed + index)
        )
        for song in planned
        for index in song.asked
    }


def estimate(model: ModelSpec, calls: int) -> tuple[Decimal, Decimal]:
    """(expected, at most): the measured usage per call, and every call filling max_tokens."""
    expected = model.price.cost_of(MEASURED_USAGE) * calls
    bound = model.price.cost_of(
        Usage(input_tokens=PESSIMISTIC_INPUT_TOKENS, output_tokens=model.max_tokens)
    )
    return expected, bound * calls


# ---------------------------------------------------------------------------- one section


async def shoot(
    provider: LLMProvider, model: ModelSpec, section: Section, index: int, seed: int
) -> Take | Missed:
    """The producer's call for one section, once, inside its deadline. Never raises."""
    request = request_for(section, model)
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


async def bake(
    provider: LLMProvider,
    model: ModelSpec,
    planned: list[Planned],
    emit: Callable[[str], object] = sys.stderr.write,
) -> list[Song]:
    """Every song, one call at a time, in play order, on one event loop."""
    if isinstance(provider, Warmable):
        with suppress(ProviderError):
            await provider.warm()
    songs: list[Song] = []
    for number, song in enumerate(planned, start=1):
        takes: list[Take] = []
        missed: list[Missed] = []
        for index in song.asked:
            section = song.form[index]
            outcome = await shoot(provider, model, section, index, song.spec.seed + index)
            if isinstance(outcome, Take):
                takes.append(outcome)
                verdict = "delivered"
            else:
                missed.append(outcome)
                verdict = f"missed: {outcome.reason}"
            where = f"song {number} section {index + 1:>2}/{len(song.form)}"
            emit(f"  {where} {section.name:<7} {verdict}\n")
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


def paid_provider(yes: bool, model: ModelSpec, calls: int, cap_usd: Decimal) -> LLMProvider | int:
    """The real adapter once `--yes` is given, or the exit code to stop with."""
    expected, bound = estimate(model, calls)
    sys.stderr.write(
        f"expected ~${expected:.2f} at the usage Phase 4 measured; at most ~${bound:.2f} "
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

    for number, song in enumerate(planned, start=1):
        seconds = sum(section.total_seconds() for section in song.form)
        sys.stderr.write(
            f"{number}. {song.spec.title}: {song.spec.feel}, key {song.spec.key} "
            f"{song.spec.scale}, {seconds:.0f}s, {len(song.form)} sections, "
            f"{len(song.asked)} to ask\n"
        )
    sys.stderr.write(
        f"{len(planned)} songs, {minutes:.1f} minutes at {bpm:g} BPM, {sections} sections: "
        f"{calls} calls to {model.id}\n"
    )

    inner: LLMProvider
    if args.fake:
        inner = BakedProvider(floor_answers(planned), name="fake")
        provider_name = "fake"
        sys.stderr.write("baking the floor's own DSL: no network, no money\n")
    else:
        paid = paid_provider(args.yes, model, calls, args.cap_usd)
        if isinstance(paid, int):
            return paid
        inner, provider_name = paid, "anthropic"

    provider = guarded(inner, catalog, args.cap_usd)
    songs = asyncio.run(bake(provider, model, planned))
    setlist = Setlist(
        name=spec.name,
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
