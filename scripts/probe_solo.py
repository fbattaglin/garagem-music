"""Asks the model for **one** solo section, and reads what the notation did to it.

    uv run python scripts/probe_solo.py               # estimate; spends nothing
    uv run python scripts/probe_solo.py --yes         # one call, about a cent
    uv run python scripts/probe_solo.py --fake        # the floor's own solo, same report, free

Stage D of ADR-027, and it is deliberately the cheap half. **Phase 6's most expensive lesson
was that two paid bakes were spent on defects in our own notation** that a $0.0073 call would
have found (`phase-6-findings.md` §7). ADR-027 wrote the rule down as *ask first, build second*,
and this is asking.

**The question.** `LED … deg:` counts degrees of *that bar's chord*, so the notation re-roots at
every bar line. A hook lives inside a bar and does not care. A solo is a phrase that crosses bar
lines, and a written 3 that means one note in bar 1 and a different note in bar 2 may not be able
to carry one. If the model cannot write a line in this spelling, the answer is a scale-relative
`rel=key`. **Do not build that before seeing this.** The probe exists to make the decision
cheap, not to confirm it.

**What it prints, in this order:** the DSL exactly as it arrived; the lead bar by bar, as written
degrees and as realised pitches; the same two rows for the floor's own solo over the same
briefing, as a reference that costs nothing; and whether the section parsed, validated and
needed the repairer. Reading is the point — the numbers at the end are only there to stop a
reader inventing them.

**The theme is a real one, and it is free.** It comes out of `setlists/songwriter.json`, which
the third Phase 6 bake paid for, so the variable under test is the solo section and not the
material above it. One call, one section, no file written.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Final

from garagem.agents import songwriter_request_for, structural
from garagem.daw import load_session
from garagem.domain import (
    PITCH_CLASSES,
    SIXTEENTHS_PER_BAR,
    Chart,
    Feel,
    Instrument,
    Section,
    SectionScore,
)
from garagem.dsl import (
    SectionStream,
    parse_text,
    realise,
    serialize_section,
    songwriter_brief,
)
from garagem.dsl.errors import DslError
from garagem.engines import SHAPES, diatonic, play_section
from garagem.engines.arranger import MAJOR_CHARTS, MINOR_CHARTS, SOLO
from garagem.llm import (
    AnthropicAdapter,
    BakedProvider,
    Budget,
    CircuitBreaker,
    Governor,
    GuardedProvider,
    LLMProvider,
    ModelSpec,
    ProviderError,
    Usage,
    load_catalog,
    prices_of,
)
from garagem.llm.errors import BudgetError, CircuitOpenError
from garagem.theory import (
    chart_pitch_classes,
    grid_slots,
    nearest_slot,
    pitch_classes,
    render_chart,
    render_chord,
    render_key,
    repair,
    validate,
)
from garagem.theory.scales import DEGREES, steps_of

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "session.toml"
CATALOG = ROOT / "config" / "models.toml"
SETLIST = ROOT / "setlists" / "songwriter.json"

# **The cap is not the estimate, and it cannot be.** The governor reserves every call at the
# model's `max_tokens` before it is sent, which for a bake request is about $0.21 — a cap set to
# the expected $0.006 refuses the call it was sized for. So this is one call's worst case with
# room to spare, and the expected figure is printed beside it.
CAP_USD: Final = Decimal("0.30")
# One songwriter section, at the usage the third Phase 6 bake measured (`bake_setlist.py`).
ONE_SECTION: Final = Usage(input_tokens=425, output_tokens=1286)


def the_briefing(song: dict[str, object], bpm: float) -> Section:
    """A solo section as the arranger writes one, in the song the theme belongs to.

    Built here rather than taken from the setlist because the setlist was baked before the
    solo kind existed: its forms have none.
    """
    scale = str(song["scale"])
    charts = MINOR_CHARTS if len(steps_of(scale)) == DEGREES and _minor(scale) else MAJOR_CHARTS
    shape = SHAPES[SOLO]
    key = int(str(song["key"]))
    return Section(
        name=SOLO,
        bars=shape.bars,
        key=key,
        scale=scale,
        feel=Feel(str(song["feel"])),
        bpm=bpm,
        dyn=shape.dyn,
        tension=shape.tension,
        chart=Chart(chords=tuple(diatonic(key, scale, d) for d in charts[SOLO][0])),
    )


def _minor(scale: str) -> bool:
    return steps_of(scale)[2] <= 3


# ------------------------------------------------------------------------------ the report


def lead_bars(dsl: str) -> list[str]:
    """Every `LED` line of the answer, in order. What the model actually wrote."""
    return [line.strip() for line in dsl.splitlines() if line.strip().startswith("LED")]


def realised_bars(score: SectionScore) -> list[list[tuple[int, int]]]:
    """The lead's notes per bar, as (sixteenth within the bar, pitch).

    Off the grid, not off the beat. Humanisation moves an attack by a few milliseconds either
    way, so a note written on a downbeat can arrive just before it and divide into the bar
    before — which is exactly what the first version of this function did to the solo's last
    note, and it made the floor look as though it rested in the bar it lands in.
    """
    slots = grid_slots(score.section)
    bars: list[list[tuple[int, int]]] = [[] for _ in range(score.section.bars)]
    for note in score.part(Instrument.LEAD).notes:
        index = slots.index(nearest_slot(slots, note.start_beats))
        bar, slot = divmod(index, SIXTEENTHS_PER_BAR)
        if 0 <= bar < len(bars):
            bars[bar].append((slot, note.pitch))
    return bars


def notation_loss(floor: SectionScore, seed: int) -> list[tuple[int, int, int, int]]:
    """What writing the floor's own solo in this notation and reading it back costs.

    `(bar, slot, was, became)` per note that moved. **The free half of the probe's question.**
    `LED … deg:` counts degrees of each bar's chord's *implied* scale, and a line that moves
    through the key crosses chords whose implied scale does not contain the note it wants: over
    `C` in E minor there is no degree that spells F#, because C's scale has F. The serializer
    then writes the nearest degree it can, and the note changes.
    """
    section = floor.section
    again = realise(parse_text(serialize_section(floor, pitched=True), section), seed)
    before, after = realised_bars(floor), realised_bars(again)
    moved: list[tuple[int, int, int, int]] = []
    for bar, (was, now) in enumerate(zip(before, after, strict=True)):
        same = {slot: pitch for slot, pitch in was}
        for slot, pitch in now:
            if slot in same and same[slot] != pitch:
                moved.append((bar, slot, same[slot], pitch))
    return moved


def report(label: str, dsl: str, score: SectionScore) -> None:
    write = sys.stderr.write
    write(f"\n--- {label}: the lead, bar by bar ---\n")
    written = lead_bars(dsl)
    realised = realised_bars(score)
    for bar in range(score.section.bars):
        line = written[bar] if bar < len(written) else "(no LED line)"
        notes = realised[bar]
        pitches = " ".join(f"{pitch}" for _, pitch in notes) or "—"
        write(f"  bar {bar + 1}  {line}\n")
        write(f"         -> {pitches}\n")
    played = sum(1 for notes in realised if notes)
    write(f"  {played} of {score.section.bars} bars have a lead in them\n")
    crossings = [
        realised[bar + 1][0][1] - realised[bar][-1][1]
        for bar in range(len(realised) - 1)
        if realised[bar] and realised[bar + 1]
    ]
    if crossings:
        steps = ", ".join(f"{step:+d}" for step in crossings)
        write(f"  across the bar lines, in semitones: {steps}\n")


# --------------------------------------------------------------------------------- the call


async def ask(
    provider: LLMProvider, model: ModelSpec, section: Section, theme: str, seed: int
) -> tuple[str, SectionScore | None]:
    """The DSL as it arrived, and the section realised from it when it can be.

    Both, because they answer different questions: the text is what the model wrote and the
    score is what the notation made of it, and the whole point of the probe is the gap.
    """
    request = songwriter_request_for(section, model, theme=theme)
    stream = SectionStream(section)
    try:
        async for event in provider.stream(request):
            stream.feed(event)
    except (ProviderError, DslError, CircuitOpenError, BudgetError) as error:
        sys.stderr.write(f"\nthe call failed: {type(error).__name__}: {error}\n")
    dsl = stream.text
    try:
        return dsl, realise(stream.result(), seed)
    except DslError as error:
        sys.stderr.write(f"\nnothing playable came back: {error}\n")
        return dsl, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="send the call; spends real money")
    parser.add_argument("--fake", action="store_true", help="the floor's own solo; free")
    parser.add_argument("--song", type=int, default=1, help="whose theme to use, 1-based")
    parser.add_argument("--setlist", type=Path, default=SETLIST)
    args = parser.parse_args()

    catalog = load_catalog(CATALOG)
    # The model the bake would use, not the catalogue's first: a probe of a different
    # model answers a different question, and Opus is four times the price of it.
    model = structural(catalog)
    bpm = load_session(SESSION).tempo_bpm
    setlist = json.loads(args.setlist.read_text(encoding="utf-8"))
    songs = setlist["songs"]
    if not 1 <= args.song <= len(songs):
        sys.stderr.write(f"--song must be 1..{len(songs)}\n")
        return 1
    song = songs[args.song - 1]
    theme = str(song.get("theme") or "")
    section = the_briefing(song, bpm)

    sys.stderr.write(
        f"one solo section for {song['title']!r}: "
        f"{section.bars} bars, key={render_key(section.key, section.scale)}, "
        f"feel={section.feel}, dyn={section.dyn}, tension={section.tension:g}\n"
        f"CHD {render_chart(section.chart)}\n"
        f"the theme comes from {args.setlist.name} and is free\n"
    )

    seed = int(str(song["seed"]))
    floor = play_section(section, seed)
    if args.fake:
        answers = {songwriter_brief(section, theme): serialize_section(floor, pitched=True)}
        inner: LLMProvider = BakedProvider(answers, name="fake")
    else:
        cost = model.price.cost_of(ONE_SECTION)
        sys.stderr.write(
            f"expected ~${cost:.4f} for one call at the usage the last bake measured; "
            f"capped at ${CAP_USD}, which is what the governor has to reserve for it\n"
        )
        if not args.yes:
            sys.stderr.write("nothing sent. Re-run with --yes.\n")
            return 0
        try:
            inner = AnthropicAdapter.from_env()
        except ProviderError as exc:
            sys.stderr.write(f"{exc}\n")
            return 1

    provider = GuardedProvider(
        inner,
        governor=Governor(
            Budget(
                session_usd=CAP_USD,
                per_minute_usd=CAP_USD,
                max_in_flight=1,
                prices=prices_of(catalog),
            )
        ),
        breaker=CircuitBreaker(),
    )
    dsl, score = asyncio.run(ask(provider, model, section, theme, seed))

    sys.stderr.write("\n=== what came back, exactly ===\n")
    sys.stderr.write(f"{dsl or '(nothing)'}\n")

    if score is not None:
        report("the model", dsl, score)
        broken = validate(score)
        _, left = repair(score)
        sys.stderr.write(
            f"\nvalidate before repair: {len(broken)} violation(s)"
            + (f" — {', '.join(sorted({v.rule for v in broken}))}" if broken else "")
            + f"; after repair: {len(left)}\n"
        )

    report("the floor, over the same briefing", serialize_section(floor, pitched=True), floor)

    moved = notation_loss(floor, seed)
    allowed = pitch_classes(section.key, section.scale) | chart_pitch_classes(section.chart)
    outside = [m for m in moved if m[3] % PITCH_CLASSES not in allowed]
    total = sum(len(notes) for notes in realised_bars(floor))
    sys.stderr.write(
        f"\n--- what this notation costs the floor's own solo ---\n"
        f"  {len(moved)} of {total} notes move when it is written as `deg:` and read back"
        f"; {len(outside)} of those land outside the key\n"
    )
    for bar, slot, was, became in moved:
        mark = "  <-- outside the key" if (became % PITCH_CLASSES) not in allowed else ""
        sys.stderr.write(
            f"  bar {bar + 1} slot {slot + 1} over "
            f"{render_chord(section.chart.at(bar))}: {was} -> {became}{mark}\n"
        )
    if moved:
        sys.stderr.write(
            "  A degree is of the bar's chord, so a line that moves through the *key* asks for\n"
            "  notes the chord's own scale cannot spell. The round trip still validates: the\n"
            "  dissonance budget at this tension buys more than this, so the loss is silent.\n"
        )
    spent = provider.governor.snapshot()
    sys.stderr.write(f"\nno file written; spent ${spent.spent_usd:.4f}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
