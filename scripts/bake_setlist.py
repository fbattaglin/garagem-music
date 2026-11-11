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
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from garagem.agents import by_id, composer
from garagem.agents.songwriter import (
    MEASURED_USAGE,
    NOT_RETRYABLE,
    SONGWRITER_USAGE,
    THEME_USAGE,
    Planned,
    asked_twice,
    bake,
    estimate,
    floor_answers,
    floor_theme,
    guarded,
    plan,
    rebake,
    shoot,
    theme_fields,
    theme_shot,
    themes,
)
from garagem.daw import load_session
from garagem.dsl import brief, serialize_section, songwriter_brief
from garagem.engines import play_section
from garagem.llm import (
    AnthropicAdapter,
    BakedProvider,
    GuardedProvider,
    LLMProvider,
    ModelSpec,
    ProviderError,
    load_catalog,
)
from garagem.setlist import (
    Setlist,
    SetlistError,
    TakeStatus,
    load_setlist,
    load_spec,
    save_setlist,
)

# The songwriter's own names, kept reachable here: the script was where they lived, and the
# tests and `jam.py`'s still reach them through it.
__all__ = [
    "MEASURED_USAGE",
    "NOT_RETRYABLE",
    "SONGWRITER_USAGE",
    "THEME_USAGE",
    "Planned",
    "asked_twice",
    "bake",
    "estimate",
    "floor_answers",
    "floor_theme",
    "guarded",
    "plan",
    "rebake",
    "shoot",
    "theme_fields",
    "theme_shot",
    "themes",
]

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "session.toml"
CATALOG = ROOT / "config" / "models.toml"

DEFAULT_CAP_USD: Final = Decimal("1.00")


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
    model = composer(catalog)
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
            f"{number}. {song.spec.title}: {song.form[0].bpm:g} BPM, {song.spec.feel}, "
            f"key {song.spec.key} "
            f"{song.spec.scale}, {seconds:.0f}s, {len(song.form)} sections, "
            f"{len(song.asked)} to ask\n"
        )
    themes = len(planned) if songwriter else 0
    sys.stderr.write(
        f"{len(planned)} songs, {minutes:.1f} minutes, {sections} sections: "
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
        # Worded as `rebake` will ask: with the song's material where it has some.
        answers = {
            (songwriter_brief(take.briefing, song.theme) if song.theme else brief(take.briefing)): (
                serialize_section(play_section(take.briefing, take.seed), pitched=bool(song.theme))
            )
            for song in setlist.songs
            for take in song.takes
            if take.status is TakeStatus.VETOED
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
