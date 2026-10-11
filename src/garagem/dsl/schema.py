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


# ---------------------------------------------------------------- the songwriter, offline
#
# **Everything below is bake-only** (ADR-026). None of it is ever sent from `jam.py`, none
# of the cassettes was recorded against it, and the four blocks above do not move — which
# is what ADR-025's freeze on live generation means in practice: the notation grew, the
# live request did not.
#
# It asks for two things the live prompt cannot ask for, because a 5.8 s deadline could
# not hold them: **pitches**, and **a song that comes back to something**. Offline there is
# no deadline, the call can be retried, and the answer can be as long as it needs to be.

TOOL_THEME: Final = ToolSchema(
    name="write_theme",
    description="Writes a song's musical material: a riff and a hook, in the GARAGEM DSL.",
    input_schema={
        "type": "object",
        "properties": {
            "dsl": {
                "type": "string",
                "description": (
                    "One or more BAS, GTR and LED bar lines. No SEC and no CHD: the theme "
                    "is material, not a section."
                ),
            }
        },
        "required": ["dsl"],
        "additionalProperties": False,
    },
)


# What a degree map is, written once and shared by both bake blocks below — but **pasted
# into each of them as text, not interpolated**. Two whole strings, for the reason
# `SYSTEM_ARRANGED` is whole: a cache prefix assembled from pieces is a cache prefix that
# moves when any piece does.
# **Rewritten on 2026-09-17, after the first paid bake returned the previous version's
# example almost verbatim for all three songs** (`phase-6-findings.md` §5). Two of three
# themes were byte-identical to it and the third differed in five slots — one riff and one
# hook for three feels and three keys.
#
# `phase-3-findings.md` §11 found that an instruction losing to its example is what happens
# when the two disagree, and the fix then was to make the example *be* the thing asked for.
# Here that fix is the defect: the example was a complete, valid, plausible answer, so
# returning it was both the cheapest move and a correct one. Nothing made a copy wrong.
#
# So this version shows **two** examples, says out loud that they belong to other songs,
# and asks for material this song's feel and key would produce and the other two would not.
# Whether that is enough is a measurement — `bake_setlist.py --themes-only` asks for the
# themes alone, three calls and about a cent.
SYSTEM_THEME: Final = """You are the songwriter in GARAGEM. You write the material a song
is built out of, before any of its sections exist.

Answer only through the write_theme tool, in the GARAGEM DSL.

A bar is 16 sixteenths, numbered 1 to 16. Slot 1 is the downbeat.

Write the song's material as bar lines, and nothing else. No SEC line and no CHD line:
this is not a section, it is what the sections will be made of.

deg: is a degree per struck slot. The slots you name are the slots that sound; there is
no separate rhythm to write. A degree is of whatever chord the bar is on, so the same riff
transposes through the whole song: 1 is the root, 3 the third, 5 the fifth. Degrees run 1
to 14, counted the way a musician counts them — 8 is the root an octave up, 9 the ninth,
13 the thirteenth — so a line can climb past the octave without changing oct=.

BAS is the bass, one note at a time, oct=1: a rock bass lives on its two low strings. LED
is the lead voice, oct=4, and it is the song's singer: hold= names the slots whose note
rings on until the next one. Only a slot that deg: strikes can be held, and every field is
written once.

Write exactly six lines, in this order:
    two BAS lines   the riff
    two LED lines   the verse melody, two bars of it
    two LED lines   the chorus melody, two bars of it

A verse melody is low and conversational. It comes in after the downbeat, moves mostly by
step, and leaves a breath at the end of its two bars. A chorus melody is higher and says its
line on the downbeat, with longer notes: it is the part of the song people sing back. Put a
chord tone (1, 3 or 5) on slots 1 and 9, and let the notes between them move through.

Here is the material of two **other** songs, so you can see the shape of an answer.

A straight-eight rock song in E minor:

    BAS oct=1 deg:1=1,4=1,7=5,11=1,14=5
    BAS oct=1 deg:1=1,4=1,7=5,11=3,14=1
    LED oct=4 deg:5=1,7=2,9=3,13=5
    LED oct=4 deg:3=3,5=2,9=1 hold=9
    LED oct=4 deg:1=5,7=6,9=8 hold=9
    LED oct=4 deg:1=10,5=8,9=5 hold=9

A halftime song in G major, where the bar is emptier and the notes are longer:

    BAS oct=1 deg:1=1,9=5
    BAS oct=1 deg:1=1,9=3,15=5
    LED oct=4 deg:5=3,9=5 hold=9
    LED oct=4 deg:3=4,5=3,9=1 hold=9
    LED oct=4 deg:1=8 hold=1
    LED oct=4 deg:1=10,9=8,13=5 hold=13

**Neither of those is your song, and your material must not be either of them.** Write
what this song's feel and key would produce and the other two would not. The feel decides
where the notes fall: a shuffle leans on the swung offbeats, halftime leaves the middle of
the bar open, straight eighths can push against the beat.

Make the riff and the melodies fit together: where the bass is busy the melody should be
sparse, and the other way round. This material comes back in every section of the song, so it
has to be worth hearing again — and it has to be recognisable as this song and not another
one."""


SYSTEM_SONGWRITER: Final = """You are the band in GARAGEM, playing a song somebody has
already written the material for.

Answer only through the write_section tool, in the GARAGEM DSL.

Echo the SEC and CHD lines back exactly as given. They are the briefing, not a
suggestion: the clip has already been sized from them.

**Write one bar-level line per bar, per instrument, in bar order.** A section is an
arrangement, not a loop: the bars differ where a band would make them differ.

Here is a whole two-bar section. There are two of every line because there are two bars,
and they are not the same: bar 1 opens with a crash and bar 2 ends with a fill.

    SEC verse bars=2 key=Em feel=straight8 bpm=132 dyn=3 tension=0.4
    CHD | Em | C |
    DRM K:1,4,7,11,14 S:5,13 H:1,3,5,7,9,11,13,15 C:1
    DRM K:1,4,7 S:5,9,11,12,13,15,16 H:1,3,5,7
    BAS oct=1 deg:1=1,4=1,7=5,11=1,14=5
    BAS oct=1 deg:1=1,4=1,7=5,11=3,14=1
    GTR voi=pow rhy:1,3,5,7,9,11,13,15 palm=on
    GTR voi=pow rhy:1,3,5,7,9,11,13,15 palm=on acc=1,9
    KEY voi=sus2 rhy:1 reg=mid
    KEY voi=sus2 rhy:1 reg=mid
    LED oct=4 deg:5=1,7=2,9=3,13=5
    LED oct=4 deg:3=3,5=2,9=1 hold=9

For an 8-bar section write 8 lines of each. Open bar 1 with a crash. Put a fill in the
last bar — busier snare, hats dropping out. Let the hats open up as the section builds.

A bar is 16 sixteenths, numbered 1 to 16, and you write the numbers of the slots that are
struck. Slot 1 is the downbeat. Never write a slot above 16. The bar is always 16
sixteenths whatever the feel: halftime moves the backbeat to slot 9 and does not make the
bar longer; shuffle swings the offbeats and does not make it shorter.

The DRM voices are K kick, S snare, H hi-hat and C crash. A voice you leave out is silent
for that bar.

BAS and LED write deg:, a degree per struck slot — the slots you name are the slots that
sound, and there is no rhy: beside them. A degree is of that bar's chord, so the material
transposes with the harmony, and degrees run 1 to 14: 8 is the root an octave up, 9 the
ninth, 13 the thirteenth. LED hold= names the slots that ring on; only a slot that deg:
strikes can be held, and every field is written once. BAS is oct=1.

**LED is the song's singer.** In a verse and a chorus it sings the song's melody in most
bars: in a verse softly and low, with a breath at the end of each two-bar phrase; in a
chorus higher and on the downbeat. Put a chord tone (1, 3 or 5) on slots 1 and 9. In the last
bar of a section, land on slot 1 and hold, and leave the rest of the bar to the drums' fill.
In an intro, a bridge or an outro the lead may sit out: a LED line with an empty deg: is a
bar it sits out.

**The band is a rock band.** GTR plays power chords, voi=pow: palm-muted eighths in a verse,
ringing and accented in a chorus. KEY is an organ under the guitars: one long chord a bar,
voi=sus2 or triad, and in a quiet verse it rests, which is a KEY line whose rhy: is all
dots.

**A solo section is the lead's.** In one, the LED line plays in every bar and the rest of the
band gets out of its way — thinner guitar, fewer keys, the drums holding the groove. The hook
becomes a line that moves rather than a figure that repeats, and it is the only section where
that is true.

**In a solo, write the LED line as `rel=key`.** A degree is normally of that bar's chord, which
is what you want for a hook: it transposes with the harmony. It is wrong for a solo, because the
chord root moves and the same degree then means a different note in every bar — degree 1 of `Em`
and degree 1 of `C` are a seventh apart at the same oct=, and a line that reads smoothly leaps
when it is played. With `rel=key` a degree is of the song's own scale, counted from its tonic,
and the same degree is the same note in every bar whatever is underneath it:

    LED oct=4 rel=key deg:1=1,3=2,5=3,8=5,11=3,13=2 hold=13

Then oct= is one register for the whole solo and you do not have to change it. Degrees still run
1 to 14 of the scale. The lead sounds between G3 and C6 — about degree 1 to degree 13 at oct=4 in
most keys — so stay inside that and the line comes back exactly as you wrote it. A degree that
would land above C6 comes back an octave lower.

Outside a solo, leave rel= out: a melody belongs to its chords.

GTR and KEY write voi= and rhy:, as before. voi= is one of exactly these six, and nothing
else:
    pow     root and fifth, no third
    triad   root, third, fifth
    sus2    the second in place of the third
    sus4    the fourth in place of the third
    drop2   the second voice from the top, dropped an octave
    shell   root, third and seventh, no fifth
A chord quality such as min or maj7 is not a voicing. The chord comes from the CHD line;
voi= says how to spread it.

reg= is low, mid or high. palm= is on or off. ghost= and acc= use the same slot numbers.

Emit in this order and no other: SEC, CHD, DRM, BAS, GTR, KEY, LED.

**Use the song's material.** It is given to you with the briefing: the riff, then the verse
melody, then the chorus melody. Sing the verse melody in a verse and the chorus melody in a
chorus, fitted to this section's chords, and repeat them across the section the way a song
repeats its lines. Play the riff where it belongs. A chorus should be where the melody is most
itself."""


def theme_brief(title: str, key: str, feel: str, bpm: float, form: str) -> str:
    """The one volatile message of the theme call: which song, in one short block."""
    return (
        f"Song: {title}\n"
        f"key={key} feel={feel} bpm={bpm:g}\n"
        f"form: {form}\n"
        "Write this song's material."
    )


def songwriter_brief(section: Section, theme: str) -> str:
    """One section's briefing with the song's own material above it.

    The material goes in the *message* rather than the system block, and that is not a
    detail: the block is the cache prefix (`Request.cache_system`), and a theme moved into
    it would change per song and zero the hit rate for every section of every song.
    """
    material = _labelled(theme.strip())
    return (
        (f"The song's material:\n{material}\n\n" if material else "")
        + _which_melody(section.name, material)
        + f"SEC {section.name} bars={section.bars} "
        f"key={render_key(section.key, section.scale)} "
        f"feel={section.feel} bpm={section.bpm:g} dyn={section.dyn} "
        f"tension={section.tension:g}\n"
        f"CHD {render_chart(_per_bar(section))}\n"
        f"Echo those two lines back unchanged, then write {section.bars} bars each of "
        "DRM, BAS, GTR, KEY and LED, arranged, using the material above where it fits."
    )


# The six lines `SYSTEM_THEME` asks for since ADR-028, in its order: what each pair is.
MATERIAL_PARTS: Final[tuple[tuple[str, str], ...]] = (
    ("riff", "BAS"),
    ("verse melody", "LED"),
    ("chorus melody", "LED"),
)


def _labelled(material: str) -> str:
    """The material with each pair of lines named, when it has the six-line shape.

    The first melody probe (ADR-028) gave the model the six lines bare, and it sang them as one
    four-bar tune: the verse melody and the chorus melody in turn, in a verse and in a chorus
    alike. Named, they are two tunes. A theme baked before ADR-028 — a riff and one hook — is
    passed through as it was.
    """
    lines = [line for line in material.splitlines() if line.strip()]
    tags = [line.split(maxsplit=1)[0] for line in lines]
    if tags != [tag for _, tag in MATERIAL_PARTS for _ in range(2)]:
        return material
    blocks = (
        f"{name}:\n{lines[2 * index]}\n{lines[2 * index + 1]}"
        for index, (name, _) in enumerate(MATERIAL_PARTS)
    )
    return "\n".join(blocks)


def _which_melody(kind: str, material: str) -> str:
    """One sentence saying which of the two tunes this section sings, and only that one."""
    if "verse melody:" not in material or kind not in ("verse", "chorus"):
        return ""
    other = "chorus" if kind == "verse" else "verse"
    return (
        f"This is a {kind}: sing only the {kind} melody, its two bars again and again, "
        f"fitted to the chords. The {other} melody belongs to the {other}.\n"
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
