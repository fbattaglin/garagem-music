"""What we ask a model for, and how the question is split for caching.

Three things live here and the split between them is the whole design.

**`TOOL`** is the strict schema of ADR-009: one required string, no additional
properties. The model answers through it or not at all. Free text is not a fallback — a
system that accepted prose here would be a system whose parser has to guess.

**`SYSTEM`** is the *stable block*: the DSL rules and the persona, identical for every
section of every song. `Request.cache_system` marks it for prompt caching, and the
saving is only real while the prefix does not move. **Moving one word of a section's
briefing into `SYSTEM` drops the cache hit rate to zero** — not degrades it, zeroes it,
because a cache prefix either matches byte for byte or does not exist.

**`brief()`** is everything that changes: bars, key, feel, tempo, dynamics, tension and
the chart. It goes in the message, where it belongs.

The text of `TOOL` and `SYSTEM` is **verbatim** what `scripts/recipes/section_brief.py`
used to hold, and it must stay that way until somebody deliberately re-records: the four
cassettes in `cassettes/` carry a fingerprint of the whole request, and
`CassetteProvider` refuses to replay against a prompt that has moved. That refusal is a
feature — it is what stops a prompt change from being silently tested against answers to
a different question — but it means editing this file has a cost, and the cost is a
re-record.
"""

from __future__ import annotations

from typing import Final

from garagem.domain import Chart, Section
from garagem.llm import ToolSchema
from garagem.theory import render_chart, render_key

TOOL: Final = ToolSchema(
    name="write_section",
    description="Writes a complete section in the GARAGEM DSL.",
    input_schema={
        "type": "object",
        "properties": {
            "dsl": {
                "type": "string",
                "description": (
                    "GARAGEM/0.1 DSL. Emission order is mandatory: SEC, CHD, DRM, BAS, GTR, KEY."
                ),
            }
        },
        "required": ["dsl"],
        "additionalProperties": False,
    },
)

SYSTEM: Final = """You are the band in GARAGEM, a real-time music generation system.

Answer only through the write_section tool, in the GARAGEM/0.1 DSL.

Echo the SEC and CHD lines back exactly as given. They are the briefing, not a
suggestion: the clip has already been sized from them.

Section level:
    SEC verse bars=8 key=Em feel=straight8 bpm=132 dyn=3 tension=0.4
    CHD | Em | Em | C  | D  | Em | Em | C  | B7 |

Bar level, on a grid of exactly 16 characters where x is an attack and . is a rest.
Count them: every grid below is 16 long, and a grid of any other length is rejected.
The grid is always one bar of 16 sixteenths, whatever the feel. halftime moves the
backbeat to beat 3 and does not make the bar longer; shuffle swings the offbeats and
does not make it shorter. Never write 32 characters for a halftime bar.
    DRM K:x..x..x...x..x.. S:....x.......x... H:x.x.x.x.x.x.x.x.
    BAS deg=1 oct=2 rhy:x.x.x.x.x.x.x.x.
    GTR voi=pow rhy:xx.xxx.xxx.xx.x. palm=on
    KEY voi=sus2 rhy:x.......x....... reg=mid

voi= is one of exactly these six, and nothing else:
    pow     root and fifth, no third
    triad   root, third, fifth
    sus2    the second in place of the third
    sus4    the fourth in place of the third
    drop2   the second voice from the top, dropped an octave
    shell   root, third and seventh, no fifth
A chord quality such as min or maj7 is not a voicing. The chord comes from the CHD
line; voi= says how to spread it.

reg= is low, mid or high. palm= is on or off.

One bar-level line per instrument covers every bar of the section. Write more than one
only when the bars actually differ, and then write one per bar, in bar order.

Emit in this order and no other: SEC, CHD, DRM, BAS, GTR, KEY. The order is rhythmic
priority, and it lets the drums and bass be written into the clip while the rest is
still being generated."""


# The same block with the arrangement asked for. Kept as a whole second string rather
# than assembled from pieces, because it is a **cache prefix**: two variants that share a
# builder would share a bug, and one that interpolates would have no prefix at all.
#
# Two things it says that `SYSTEM` does not, both of them gaps the A/B exposed
# (`phase-3-findings.md` §10):
#
# - **Per-bar lines that actually differ.** Under `SYSTEM` the model wrote one line per
#   instrument in 28 of 28 sections, so every generated section was the same bar eight
#   times while the deterministic engine opened with a crash and closed with a fill. The
#   blind A/B compared a loop against an arrangement and the arrangement won 9 of 11.
# - **The crash voice exists.** `C:` has been in the parser since Phase 3 began and has
#   never appeared in an example, so no model has ever written one: 0 of 28.
#
# The first version of this block put those instructions in prose and left the example
# showing one line per instrument. The model followed the example: **0 of 28 sections came
# back with more than one DRM line, and not one carried a crash** — even with `C:` in the
# example. An instruction that contradicts the example beside it loses to the example, so
# the example here *is* a whole arranged section.
#
# Whether this fits the deadline is a measurement, not an opinion:
# `scripts/bench_sections.py --arranged`.
SYSTEM_ARRANGED: Final = """You are the band in GARAGEM, a real-time music generation system.

Answer only through the write_section tool, in the GARAGEM/0.1 DSL.

Echo the SEC and CHD lines back exactly as given. They are the briefing, not a
suggestion: the clip has already been sized from them.

**Write one bar-level line per bar, per instrument, in bar order.** A section is an
arrangement, not a loop: the bars differ where a band would make them differ.

Here is a whole two-bar section. Note that there are two DRM lines because there are two
bars, and that they are not the same: bar 1 opens with a crash and bar 2 ends with a fill.

    SEC verse bars=2 key=Em feel=straight8 bpm=132 dyn=3 tension=0.4
    CHD | Em | C |
    DRM K:x..x..x...x..x.. S:....x.......x... H:x.x.x.x.x.x.x.x. C:x...............
    DRM K:x..x..x......... S:....x...x.xxx.xx H:x.x.x.x.........
    BAS deg=1 oct=2 rhy:x.x.x.x.x.x.x.x.
    BAS deg=1 oct=2 rhy:x.x.x.x.x.x.x.x. ghost=14,16
    GTR voi=pow rhy:xx.xxx.xxx.xx.x. palm=on
    GTR voi=pow rhy:xx.xxx.xxx.xx.x. palm=on acc=1,9
    KEY voi=sus2 rhy:x.......x....... reg=mid
    KEY voi=sus2 rhy:x............... reg=mid

For an 8-bar section, write 8 DRM lines, 8 BAS lines, 8 GTR lines and 8 KEY lines.
Open bar 1 with a crash. Put a fill in the last bar — busier snare, hats dropping out.
Let the hats open up as the section builds and thin out where it breathes.

Every grid is exactly 16 characters, where x is an attack and . is a rest. Count them:
every grid above is 16 long, and a grid of any other length is rejected. The grid is
always one bar of 16 sixteenths, whatever the feel. halftime moves the backbeat to
beat 3 and does not make the bar longer; shuffle swings the offbeats and does not make
it shorter. Never write 32 characters for a halftime bar.

The DRM voices are K kick, S snare, H hi-hat and C crash. A voice you leave out is
silent for that bar.

voi= is one of exactly these six, and nothing else:
    pow     root and fifth, no third
    triad   root, third, fifth
    sus2    the second in place of the third
    sus4    the fourth in place of the third
    drop2   the second voice from the top, dropped an octave
    shell   root, third and seventh, no fifth
A chord quality such as min or maj7 is not a voicing. The chord comes from the CHD
line; voi= says how to spread it.

reg= is low, mid or high. palm= is on or off.

Emit in this order and no other: SEC, CHD, DRM, BAS, GTR, KEY. The order is rhythmic
priority, and it lets the drums and bass be written into the clip while the rest is
still being generated."""


# `SYSTEM` with one thing added: what `dyn` is for. A third whole string, for the reason
# the second one is whole — a cache prefix that shares a builder shares a bug.
#
# The gap it addresses is not the A/B's (`phase-3-findings.md` §13 corrected itself on
# that). It is simpler and it does not depend on anyone's ears: **`dyn` is a briefing
# field the system sends and the model does not act on.** Across 85 sections the model's
# drum density is a median of 14 attacks per bar at `dyn=2`, at `dyn=3` and at `dyn=4`.
# On the model's path `dyn` reaches the music only as velocity, so a chorus comes back as
# a verse played louder.
#
# The numbers below are the deterministic floor's own, measured rather than invented, and
# they are stated per feel because the floor's are not one curve: `groove_for` lifts hard
# in straight8 (12 -> 22) and barely at all in shuffle (12 -> 14). A single number here
# would be wrong for half the feels.
SYSTEM_DENSE: Final = (
    SYSTEM
    + """

dyn= is how full the bar is. It is not a volume: two sections at different dyn must not
come back with the same grids played harder. Counting the x's across K:, S: and H:
together in one bar, straight8 runs about 8 at dyn=1, 12 at dyn=2 and 22 at dyn=4 — a
chorus is audibly busier than a verse, not the verse louder. In straight16 the hat is
already busy at every level, so the lift belongs in the kick and the snare instead. In
shuffle and halftime the lift is smaller; do not force it."""
)


# `SYSTEM` with the bar written as attack positions instead of a fixed-width grid. A
# fourth whole string, for the reason the second and third are whole: a cache prefix that
# shares a builder shares a bug.
#
# **This is the only defect left.** After the alias and the measured deadline floor,
# conformance reached 93% and *both* remaining violations in 29 sections were a grid
# counted wrong by one character — 15 and 17 where 16 is required (`phase-3-findings.md`
# §15). Four prompt variants have failed to move it, which is unsurprising: counting
# sixteen characters of `x` and `.` is close to the worst thing a tokeniser can be asked
# to do, and it gets worse the busier the bar (§14 measured 8 miscounts under the density
# prompt against 3 under the static one).
#
# Positions remove the class rather than reducing it. There is no length to be wrong
# about; a slot outside 1..16 is *detectable* where a short grid silently shifts the bar;
# and a dropped item costs one note instead of the whole line.
#
# Against it, and the reason this is measured rather than adopted: the DSL's premise is
# that the model can *see* the grid, and §11's hypothesis — that a bar-level line reads as
# a pattern definition because that is what the notation looks like — was never tested.
# Positions may read as something else again. `bench_sections.py --positions` is the
# answer, at ~$0.10.
SYSTEM_POSITIONS: Final = SYSTEM.replace(
    """Bar level, on a grid of exactly 16 characters where x is an attack and . is a rest.
Count them: every grid below is 16 long, and a grid of any other length is rejected.
The grid is always one bar of 16 sixteenths, whatever the feel. halftime moves the
backbeat to beat 3 and does not make the bar longer; shuffle swings the offbeats and
does not make it shorter. Never write 32 characters for a halftime bar.
    DRM K:x..x..x...x..x.. S:....x.......x... H:x.x.x.x.x.x.x.x.
    BAS deg=1 oct=2 rhy:x.x.x.x.x.x.x.x.
    GTR voi=pow rhy:xx.xxx.xxx.xx.x. palm=on
    KEY voi=sus2 rhy:x.......x....... reg=mid""",
    """Bar level. A bar is 16 sixteenths, numbered 1 to 16, and you write the numbers of the
slots that are struck, separated by commas. Slot 1 is the downbeat. Nothing needs
counting: name the slots you want and leave the rest out.
The bar is always 16 sixteenths whatever the feel. halftime moves the backbeat to slot 9
and does not make the bar longer; shuffle swings the offbeats and does not make it
shorter. Never write a slot above 16.
    DRM K:1,4,7,11,14 S:5,13 H:1,3,5,7,9,11,13,15
    BAS deg=1 oct=2 rhy:1,3,5,7,9,11,13,15
    GTR voi=pow rhy:1,2,4,5,6,8,9,11,12,14,15 palm=on
    KEY voi=sus2 rhy:1,9 reg=mid
A voice with nothing in it is left out, not written empty. ghost= and acc= already use
these same slot numbers.""",
)


def system_for(*, arranged: bool = False, dense: bool = False, positions: bool = False) -> str:
    """Which stable block to send. Whole strings, so each is its own cache prefix."""
    if arranged:
        return SYSTEM_ARRANGED
    if positions:
        return SYSTEM_POSITIONS
    return SYSTEM_DENSE if dense else SYSTEM


def brief(section: Section, *, arranged: bool = False) -> str:
    """The one volatile message: what to play, this time.

    Every field of the `Section` appears, because every one of them is a constraint the
    model is going to be held to — `dsl/lines.check_sec` compares what comes back
    against exactly this, and a field we did not state is a field we cannot fairly
    refuse. The chart is rendered by `theory.render_chart`, so the pipes and the
    spelling are the same ones the parser will read back.
    """
    return (
        f"SEC {section.name} bars={section.bars} "
        f"key={render_key(section.key, section.scale)} "
        f"feel={section.feel} bpm={section.bpm:g} dyn={section.dyn} "
        f"tension={section.tension:g}\n"
        f"CHD {render_chart(_per_bar(section))}\n"
        + (
            f"Echo those two lines back unchanged, then write {section.bars} bars each of "
            "DRM, BAS, GTR and KEY, arranged."
            if arranged
            else "Echo those two lines back unchanged, then write DRM, BAS, GTR and KEY."
        )
    )


def _per_bar(section: Section) -> Chart:
    """The chart written out one chord per bar, for every bar of the section.

    A four-chord chart under an eight-bar section is ambiguous and a model reads it the
    way a musician would: two bars per chord. `Chart.at` wraps instead, so the two
    readings are different progressions — and the model's was counted as a
    `section_mismatch` for doing the reasonable thing. Measured at 15 of 30 sections
    before this line existed.

    Writing it out removes the question. It costs a few tokens and it is the only
    honest way to send a chart whose length does not match the section's.
    """
    return Chart(chords=tuple(section.chart.at(bar) for bar in range(section.bars)))
