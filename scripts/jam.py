"""Plays a whole song into the open Live Set, with no network call of any kind.

    uv run python scripts/jam.py --seconds 180 --seed 7
    uv run python scripts/jam.py --dry-run            # print the form, touch nothing
    uv run python scripts/jam.py --seconds 30 --log bench/jam.jsonl
    uv run python scripts/jam.py --generate           # ask a model; needs ANTHROPIC_API_KEY
    uv run python scripts/jam.py --generate --provider cassette:path.jsonl   # no network
    uv run python scripts/jam.py --plain              # no transitions, no climax: Phase 3
    uv run python scripts/jam.py --controller minilab # log every pad and knob (ADR-021)
    uv run python scripts/jam.py --setlist setlists/first.json --song 2   # from disk (ADR-024)

This is Phase 2's exit criterion as a command. It arranges a form, generates every
section with the deterministic engines, writes them into alternating scenes and fires
each one a bar before its boundary — for as long as the form lasts, with the transport
running, and without ever asking anything of the internet. That last part is the point:
the band has to sound like a band before an LLM is added to it (P2).

Four rules, each of them load-bearing:

- **It refuses to start against a Set that does not match `session.toml`.** The check is
  `diff_session`, the same one `bootstrap_set.py` uses — re-implementing it here would be
  two definitions of "the right Set" and eventually two answers.
- **It stops the transport on the way out**, in a `finally`, including after Ctrl-C.
  Leaving Live playing a loop nobody is driving is not a tidy end to a performance.
- **It makes no network call unless `--generate` is passed.** Off is the default, and
  deliberately: Phase 2's behaviour stays byte-for-byte reachable, which is what makes the
  two comparable and what stops the offline path from quietly rotting. Even with the flag,
  nothing in `domain/`, `theory/`, `engines/` or `transport/` may reach the network — the
  producer owns the call, on its own thread (ADR-016), and
  `tests/unit/test_architecture.py` is what keeps that true rather than merely intended.
- **It writes the event log**, which is where the "zero glitches" claim is read from:
  every write and every fire, stamped with the beat it happened at.

**Sections hand over to each other** (ADR-020): a build into a chorus, a stop before the
last one, a final chord at the end, and the last chorus lifted above the others. `--plain`
turns all of it off and plays the form exactly as every listening before Phase 4 heard it,
which is what makes the two comparable by ear.

**The MiniLab conducts** (`--controller minilab`, ADR-021, ADR-022). Every pad strike and
knob position is logged as `cue_received`, with the beat it arrived at. **"chorus now" is
acted on:** the chorus candidate, written into the `CHORUS` scene before the downbeat, is
fired for the next bar and the rest of the song is re-planned from it. **Stop, fill and drums
and bass are acted on too** (Stage 4): variants of each section are written ahead into the
`STOP` and `FILL` scenes and fired per track for the next bar, and guitar and keys stop until
the next section. **"Next bridge" and "end" re-plan the song from the next section that can
still change, and the knobs move it** around its plan (Stage 5). The legend is printed
before the downbeat, and after the last bar a count of what was heard, how many bars each
cue took to land, and why any was declined.

**With `--generate`, the run ends by reading Phase 4's exit criteria back from its own log**
(Stage 6): continuous play, deadlines, metrics, cost against `config/budget.toml`, cue
latency and staleness, each with the numbers it was decided on. The spend is written into
the log as `session_ended`, so the same verdict can be read again later.

**With `--setlist`, a baked song plays from disk** (ADR-024). The song's stored form, endings
and seed replace the flags, and the model's takes answer through `BakedProvider`, with no
network and no key, so it plays the same with the Wi-Fi off. The producer asks only for the
briefings the bake holds; a jump or a knob that moves the song elsewhere gets the floor, as a
missed call does live. Nothing printed while it plays says who wrote a section.

`--dry-run` prints the form and exits without opening a socket, which makes it the
cheapest way to see what a seed produces. `--provider cassette:<path>` replays a recording
instead of calling out, so the whole generated path can be exercised against a real Live
with no network and no money.

Exit code 0 means the performance ran to the end of its form. A transport stopped from
outside — Live itself, or a controller Live listens to — is exit code 1, with the bar it
stopped at.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

from garagem.agents import (
    Producer,
    Route,
    by_id,
    deadline_for,
    everything,
    only,
    structural,
    worth_asking,
)
from garagem.control import (
    ControllerPort,
    ControllerSpec,
    ControllerSpecError,
    ControllerUnavailableError,
    MidoController,
    load_controller,
)
from garagem.daw import (
    AbletonOSCAdapter,
    DawError,
    DawPort,
    DawUnavailableError,
    OscSettings,
    diff_session,
    load_session,
    observe,
    render_divergences,
)
from garagem.daw.errors import SessionSpecError
from garagem.daw.live_log import control_surfaces, latest_log, listening_to
from garagem.daw.session import SessionSpec
from garagem.domain import Feel, Instrument, Section
from garagem.engines import Ending, SongBrief, arrange, endings_for, with_climax
from garagem.engines.arranger import CHORUS
from garagem.llm import (
    AnthropicAdapter,
    BakedProvider,
    BreakerPolicy,
    CassetteProvider,
    CircuitBreaker,
    Governor,
    GuardedProvider,
    LLMProvider,
    ModelSpec,
    ProviderError,
    SessionBudget,
    load_budget,
    load_catalog,
    prices_of,
)
from garagem.obs import (
    EventLog,
    model_share,
    performance_checks,
    render_checks,
    setlist_checks,
)
from garagem.setlist import (
    Setlist,
    SetlistError,
    Song,
    answers,
    briefings,
    drifted,
    load_setlist,
)
from garagem.transport import (
    BAR_TIMEOUT_S,
    BarClock,
    CueQueue,
    FormPlan,
    Scheduler,
    ScoreBuffer,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSION = ROOT / "session.toml"
DEFAULT_LOG = ROOT / "bench" / "jam.jsonl"
DEFAULT_CATALOG = ROOT / "config" / "models.toml"
DEFAULT_BUDGET = ROOT / "config" / "budget.toml"
DEFAULT_CONTROLLER = ROOT / "controller.toml"
CHORUS_SCENE = "CHORUS"
# ADR-022's variant scenes, by the names session.toml gives them, paired with main scenes A, B.
MAIN_SCENES = ("A", "B")
VARIANT_SCENES: dict[str, tuple[str, str]] = {
    "stop": ("STOP A", "STOP B"),
    "fill": ("FILL A", "FILL B"),
}

CASSETTE_PREFIX = "cassette:"

# How long to let the producer fill the buffer before the transport rolls. Without this
# the first section is always a fallback — `Scheduler.begin` writes and fires before any
# generation can finish, which is a race the music always wins. A band does not hit play
# before it knows the first song.
#
# The wait is the section's own deadline plus a margin, not a number somebody picked: a
# model that has not answered by its deadline is not going to (§4.2), and the margin
# covers the parse, the realise and the repair. Bounded, and falling through is not a
# failure — the deterministic engine plays section one, which is P2 working as designed.
PRIME_MARGIN_S = 1.0
PRIME_POLL_S = 0.05

# `session.toml` names roles; the engines name instruments. This is the one place the two
# vocabularies meet, and it is a table rather than a convention so a renamed track cannot
# quietly send the bass to the drum machine.
ROLE_TO_INSTRUMENT: dict[str, Instrument] = {
    "drums": Instrument.DRUMS,
    "bass": Instrument.BASS,
    "guitar": Instrument.GUITAR,
    "keys": Instrument.KEYS,
}


def build_adapter(host: str, timeout_s: float) -> DawPort:
    return AbletonOSCAdapter(settings=OscSettings(host=host, timeout_s=timeout_s))


def build_provider(
    spec: str | None, catalog: list[ModelSpec], budget: SessionBudget
) -> LLMProvider:
    """The model, behind the guards that `.claude/rules/llm-calls.md` makes unavoidable.

    `cassette:<path>` replays a recording instead of calling out — the same provider port,
    so the wiring under test is the real one. It is still wrapped in the governor and the
    breaker, because a rule with an exception for tests is a rule with an exception.
    """
    inner: LLMProvider
    if spec is not None and spec.startswith(CASSETTE_PREFIX):
        inner = CassetteProvider(Path(spec[len(CASSETTE_PREFIX) :]))
    else:
        inner = AnthropicAdapter.from_env()
    return GuardedProvider(
        inner,
        governor=Governor(budget.fuse(prices_of(catalog))),
        breaker=CircuitBreaker(BreakerPolicy()),
    )


def build_setlist_provider(
    setlist: Setlist, song: Song, catalog: list[ModelSpec], budget: SessionBudget
) -> LLMProvider:
    """The song's takes behind the same guards as a model: nothing here reaches a network."""
    return GuardedProvider(
        BakedProvider(answers(song), name=setlist.name),
        governor=Governor(budget.fuse(prices_of(catalog))),
        breaker=CircuitBreaker(BreakerPolicy()),
    )


def pick_song(setlist: Setlist, number: int) -> Song | str:
    """The song `--song` names, counting from 1, or why there is none."""
    if not 1 <= number <= len(setlist.songs):
        return f"--song {number}: {setlist.name} has songs 1 to {len(setlist.songs)}"
    return setlist.songs[number - 1]


def spend_of(provider: LLMProvider | None, budget: SessionBudget | None) -> dict[str, str | bool]:
    """What the governor settled, beside what the budget declared. Empty without a model.

    Written into the log rather than only printed: the cost criterion is judged against
    `target_usd`, and a verdict that lives in a terminal's scrollback cannot be read again.
    """
    if not isinstance(provider, GuardedProvider) or budget is None:
        return {}
    spent = provider.governor.snapshot()
    return {
        "spent_usd": str(spent.spent_usd),
        "estimated_usd": str(spent.estimated_usd),
        "target_usd": str(budget.target_usd),
        "cap_usd": str(budget.session_usd),
        "killed": spent.killed,
    }


def build_controller(spec: ControllerSpec) -> ControllerPort:
    return MidoController(spec)


def find_live_log() -> Path | None:
    return latest_log()


def surfaces_in_the_way(port: str) -> str | None:
    """Why the band should not start, if a Live control surface listens to the cue port.

    Both would hear every pad, and Live's surface acts on some of them — the likeliest way
    the arrangement loop that stalled the first MiniLab gates got switched on
    (`phase-4-findings.md` §8). Read from Live's own log, the only place the table exists;
    `None` when nothing is in the way *or* the log cannot be read, and the second case says
    so.
    """
    log = find_live_log()
    if log is None:
        sys.stderr.write("could not find Live's Log.txt to check its control surfaces\n")
        return None
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        sys.stderr.write(f"could not read {log} to check Live's control surfaces: {exc}\n")
        return None
    clashing = listening_to(control_surfaces(text), port)
    if not clashing:
        return None
    rows = ", ".join(f"slot {surface.slot} ({surface.name})" for surface in clashing)
    return (
        f"Live's control surface {rows} listens to {clashing[0].input}, the port the band's "
        "cues come from. Both would hear every pad and button, and Live's surface acts on "
        "them — it can move the transport or switch the loop on. In Live: Settings -> Link, "
        "Tempo & MIDI -> Control Surface, set that row's Input and Output to None, then run "
        "this again.\n"
    )


def stopped_early(scheduler: Scheduler, sections: int, bar: int) -> str:
    """Why the form was not played to its end, in terms of what to go and look at in Live."""
    where = f"the performance stopped at bar {bar}, section {scheduler.index + 1} of {sections}"
    if scheduler.stopped_because == "position_went_back":
        return (
            f"{where}: Live kept playing, but its song position went back before the next "
            f"bar for {BAR_TIMEOUT_S:g}s. The arrangement loop is the usual cause — "
            "run scripts/bootstrap_set.py, which checks it.\n"
        )
    return (
        f"{where}: Live sent no beat for {BAR_TIMEOUT_S:g}s. The transport was stopped outside "
        "GARAGEM — from Live itself, or by a controller Live listens to.\n"
    )


def render_cues(log: EventLog) -> str:
    """What the controller asked for, and how each jump landed. The gates read this."""
    received = log.of_kind("cue_received")
    if not received:
        return "no cue was received\n"
    heard = Counter(str(event.detail.get("cue", event.detail.get("macro"))) for event in received)
    listed = ", ".join(f"{name} x{count}" for name, count in sorted(heard.items()))
    lines = [f"{len(received)} controls received: {listed}"]
    applied = log.of_kind("cue_applied")
    fired = [event for event in applied if "fired_bar" in event.detail]
    if fired:
        landed = Counter(
            int(str(event.detail["fired_bar"])) - int(str(event.detail["cue_bar"]))
            for event in fired
        )
        bars = ", ".join(
            f"{gap} bar{'s' if gap != 1 else ''} x{n}" for gap, n in sorted(landed.items())
        )
        lines.append(f"{len(fired)} cues landed after: {bars}")
    # A boundary cue fires nothing; it re-plans from a section, and that section is its landing.
    for event in applied:
        if "fired_bar" not in event.detail:
            lines.append(
                f"{event.detail['cue']} at bar {event.detail['cue_bar']} re-planned from "
                f"section {event.detail['section']}"
            )
    moved = log.of_kind("macro_changed")
    if moved:
        last = moved[-1].detail
        lines.append(
            f"knobs moved the plan {len(moved)} times; last: "
            f"dyn {int(str(last['dyn_offset'])):+d}, "
            f"tension {float(str(last['tension_offset'])):+.2f}"
        )
    marked = log.of_kind("take_marked")
    if marked:
        kinds = Counter(str(event.detail["mark"]) for event in marked)
        # Never who wrote what was marked: the next time the song plays is blind too (ADR-024).
        lines.append(
            "marked: "
            + ", ".join(f"{kind} x{count}" for kind, count in sorted(kinds.items()))
            + " — scripts/curate_setlist.py applies them to the setlist"
        )
    declined = log.of_kind("cue_declined")
    if declined:
        reasons = Counter(str(event.detail["reason"]) for event in declined)
        lines.append("declined: " + ", ".join(f"{r} x{n}" for r, n in sorted(reasons.items())))
    return "\n".join(lines) + "\n"


def candidate_scenes(spec: SessionSpec) -> dict[str, int]:
    """Which scene each jump's candidate is written into, found by name in `session.toml`."""
    named = {scene.name: scene.index for scene in spec.scenes}
    if CHORUS_SCENE not in named:
        raise SessionSpecError(
            f"session.toml names no {CHORUS_SCENE!r} scene; ADR-022 writes the chorus candidate "
            "there"
        )
    return {CHORUS: named[CHORUS_SCENE]}


def variant_scenes(spec: SessionSpec) -> dict[str, dict[int, int]]:
    """Variant kind -> main scene -> the scene its variants are written into, by name."""
    named = {scene.name: scene.index for scene in spec.scenes}
    wanted = [*MAIN_SCENES, *(name for pair in VARIANT_SCENES.values() for name in pair)]
    missing = [name for name in wanted if name not in named]
    if missing:
        raise SessionSpecError(
            f"session.toml names no scene {missing}; ADR-022 writes bar-cue variants there"
        )
    return {
        kind: {named[main]: named[variant] for main, variant in zip(MAIN_SCENES, pair, strict=True)}
        for kind, pair in VARIANT_SCENES.items()
    }


def tracks_of(spec: SessionSpec) -> dict[Instrument, int]:
    """Which Live track each instrument plays on, from the Set spec."""
    return {
        ROLE_TO_INSTRUMENT[track.role]: track.index
        for track in spec.tracks
        if track.role in ROLE_TO_INSTRUMENT
    }


def pitches_of(spec: SessionSpec) -> dict[Instrument, dict[int, int]]:
    """What each instrument's Live device answers to, from the Set spec (ADR-013)."""
    return {
        ROLE_TO_INSTRUMENT[track.role]: dict(track.pitches)
        for track in spec.tracks
        if track.role in ROLE_TO_INSTRUMENT and track.pitches
    }


def brief_of(spec: SessionSpec, seconds: float, feel: Feel, key: int, scale: str) -> SongBrief:
    """The song, from the Set's tempo and the flags. Tempo is the Set's, not a flag's.

    Taking the bpm from `session.toml` rather than from an argument means the arrangement
    and the Live Set cannot disagree about how long a bar is — which is what every slack
    calculation in the scheduler depends on.
    """
    return SongBrief(key=key, scale=scale, bpm=spec.tempo_bpm, feel=feel, minimum_seconds=seconds)


def plan(
    brief: SongBrief, seed: int, *, plain: bool
) -> tuple[tuple[Section, ...], tuple[Ending, ...] | None]:
    """The song and how its sections hand over. `plain` is the form before Phase 4."""
    form = arrange(brief, seed)
    if plain:
        return form, None
    form = with_climax(form)
    return form, endings_for(form)


def render_setlist(setlist: Setlist, song: Song, number: int) -> str:
    """What is about to play, and nothing about which of its sections the model wrote."""
    lines = [
        f"playing {song.title}, song {number} of {len(setlist.songs)} of {setlist.name}, "
        f"from disk: no network"
    ]
    if setlist.provider == "fake":
        lines.append("this is a fake bake: every take is the floor's own music")
    changed = drifted(song)
    if changed:
        lines.append(
            f"{len(changed)} take(s) now play differently from when they were baked; "
            "the code that realises them has changed since"
        )
    return "\n".join(lines) + "\n"


def render_form(form: tuple[Section, ...], endings: tuple[Ending, ...] | None = None) -> str:
    lines = [
        f"{index:>3}  {section.name:<8} {section.bars:>2} bars  dyn={section.dyn} "
        f"tension={section.tension:.2f}  {section.total_seconds():5.1f}s"
        + ("" if endings is None else f"  -> {endings[index]}")
        for index, section in enumerate(form)
    ]
    total = sum(section.total_seconds() for section in form)
    lines.append(f"     {len(form)} sections, {total:.0f}s")
    return "\n".join(lines) + "\n"


def prime(buffer: ScoreBuffer, first: Section, *, margin_s: float = PRIME_MARGIN_S) -> float:
    """Wait for the first section, or give up. Returns how long it took, in seconds.

    The one place in this script that sleeps, and it is before the music starts rather
    than during it — nothing here runs on the bar loop.

    **Returns immediately when the first section was never going to be asked for.** A
    4-bar intro at 132 BPM has a 2.91 s deadline, under `MIN_DEADLINE_S`, so the producer
    declines it and plays the floor — and waiting 3.9 s for an answer nobody requested
    delayed the downbeat of every performance for nothing. Found in `bench/jam-phase3.jsonl`
    on 2026-09-01, one run after the floor was raised from 1.5 s to a measured 5.0 s.
    """
    if not worth_asking(first):
        return 0.0
    timeout_s = deadline_for(first) + margin_s
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        if buffer.take(0) is not None:
            break
        time.sleep(PRIME_POLL_S)
    return time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=180.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--timeout-s", type=float, default=0.5)
    parser.add_argument("--key", type=int, default=4, help="pitch class; 4 is E")
    parser.add_argument("--scale", default="minor")
    parser.add_argument("--feel", default=Feel.STRAIGHT8, choices=[str(f) for f in Feel])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the form and exit. Opens no socket and writes nothing.",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="no transitions and no climax: the form as it played before Phase 4.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="ask a model for each section. Off by default: without it this is Phase 2, "
        "byte for byte, which is what makes the two comparable.",
    )
    parser.add_argument(
        "--provider",
        help="cassette:<path> to replay a recording instead of calling out. "
        "Anything else, or omitted, uses the Anthropic adapter and ANTHROPIC_API_KEY.",
    )
    parser.add_argument(
        "--controller",
        choices=["minilab"],
        help="listen to the controller in --controller-spec and log every cue it sends.",
    )
    parser.add_argument("--controller-spec", type=Path, default=DEFAULT_CONTROLLER)
    parser.add_argument(
        "--setlist",
        type=Path,
        help="a baked setlist (setlists/<name>.json): play a song from disk, with no network",
    )
    parser.add_argument("--song", type=int, default=1, help="which song of --setlist, from 1")
    parser.add_argument(
        "--share",
        type=int,
        help="with --setlist: how many sections must play from the setlist's takes (ADR-025). "
        "Fixed from an offline rehearsal before the session, and reported at the end",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--budget", type=Path, default=DEFAULT_BUDGET)
    args = parser.parse_args()

    spec = load_session(args.session)
    setlist: Setlist | None = None
    song: Song | None = None
    form: tuple[Section, ...]
    endings: tuple[Ending, ...] | None
    seed: int = args.seed
    seconds: float = args.seconds
    if args.setlist is not None:
        if args.generate or args.plain or args.provider:
            sys.stderr.write(
                "--setlist plays a baked song: it takes no --generate, --plain or --provider\n"
            )
            return 1
        try:
            setlist = load_setlist(args.setlist)
        except SetlistError as exc:
            sys.stderr.write(f"{exc}\n")
            return 1
        picked = pick_song(setlist, args.song)
        if isinstance(picked, str):
            sys.stderr.write(f"{picked}\n")
            return 1
        song = picked
        if setlist.bpm != spec.tempo_bpm:
            sys.stderr.write(
                f"{args.setlist} was baked at {setlist.bpm:g} BPM and the Set is at "
                f"{spec.tempo_bpm:g}. Bake it again, or set session.toml's tempo back.\n"
            )
            return 1
        form, endings = song.form, song.endings
        seed, seconds = song.seed, song.total_seconds()
    else:
        brief = brief_of(spec, args.seconds, Feel(args.feel), args.key, args.scale)
        form, endings = plan(brief, args.seed, plain=args.plain)

    controls: ControllerSpec | None = None
    if args.controller is not None:
        try:
            controls = load_controller(args.controller_spec)
        except ControllerSpecError as exc:
            sys.stderr.write(f"{exc}\n")
            return 1

    if args.dry_run:
        sys.stderr.write(render_form(form, endings))
        if controls is not None:
            sys.stderr.write(controls.legend())
        return 0

    if controls is not None and (blocked := surfaces_in_the_way(controls.port)) is not None:
        sys.stderr.write(blocked)
        return 1

    # Before anything opens a socket to Live: a missing key should not cost a Set check.
    provider: LLMProvider | None = None
    model: ModelSpec | None = None
    budget: SessionBudget | None = None
    route: Route = everything
    if setlist is not None and song is not None:
        catalog = load_catalog(args.catalog)
        budget = load_budget(args.budget)
        model = by_id(catalog, setlist.model)
        provider = build_setlist_provider(setlist, song, catalog, budget)
        route = only(briefings(song))
    elif args.generate:
        catalog = load_catalog(args.catalog)
        budget = load_budget(args.budget)
        model = structural(catalog)
        try:
            provider = build_provider(args.provider, catalog, budget)
        except ProviderError as exc:
            sys.stderr.write(f"{exc}\n")
            return 1

    tracks = tracks_of(spec)
    if len(tracks) != len(ROLE_TO_INSTRUMENT):
        missing = sorted(set(ROLE_TO_INSTRUMENT) - {track.role for track in spec.tracks})
        sys.stderr.write(f"{args.session.name} has no track for {missing}. Nothing to play on.\n")
        return 1

    daw = build_adapter(args.host, args.timeout_s)
    log = EventLog(args.log)
    clock = BarClock(daw)
    buffer = ScoreBuffer()
    producer: Producer | None = None
    scheduler: Scheduler | None = None
    controller = build_controller(controls) if controls is not None else None
    # One form, shared: a jump re-plans it on the scheduler's thread, and the producer
    # must ask the model for what replaced it (ADR-022).
    shared = FormPlan(form, endings)
    jumps = candidate_scenes(spec) if controller is not None else {}
    variants = variant_scenes(spec) if controller is not None else {}
    # Stamped with the beat Live last reported, read on the controller's own thread.
    cues = CueQueue(stamp=lambda: clock.beat) if controller is not None else None
    try:
        try:
            daw.warm()
        except DawUnavailableError as exc:
            # Expected, and the message already says what to do (P7: no retry).
            sys.stderr.write(f"{exc}\n")
            return 1

        divergences = diff_session(spec, observe(daw))
        if divergences:
            sys.stderr.write(render_divergences(divergences))
            sys.stderr.write("Run scripts/bootstrap_set.py before playing.\n")
            return 1

        sys.stderr.write(render_form(form, endings))
        if controller is not None and controls is not None and cues is not None:
            try:
                controller.start(cues.offer)
            except ControllerUnavailableError as exc:
                sys.stderr.write(f"{exc}\n")
                return 1
            sys.stderr.write(controls.legend())
            sys.stderr.write(
                "chorus_now, stop, fill and drums_and_bass act on the next bar; next_bridge, "
                "end and the knobs act from the next section that can still change\n"
            )
        if provider is not None and model is not None:
            if setlist is not None and song is not None:
                sys.stderr.write(render_setlist(setlist, song, args.song))
                log.record(
                    "setlist_loaded",
                    0.0,
                    setlist=setlist.name,
                    provider=setlist.provider,
                    model=setlist.model,
                    song=args.song,
                    title=song.title,
                    takes=len(song.playable()),
                    # What answered the producer. No adapter was built and no key was read,
                    # which is the Wi-Fi-off criterion's machine half (ADR-025).
                    serving="baked",
                )
            else:
                sys.stderr.write(f"generating with {model.id}\n")
            producer = Producer(provider, buffer, log, shared, model=model, seed=seed, route=route)
            producer.start()
            waited = prime(buffer, form[0])
            if setlist is not None:
                pass  # Nothing about who wrote the first section: curation listens blind.
            elif buffer.take(0) is not None:
                sys.stderr.write(f"first section ready in {waited:.1f}s\n")
            elif worth_asking(form[0]):
                sys.stderr.write(
                    f"first section not ready after {waited:.1f}s — playing the floor\n"
                )
            else:
                sys.stderr.write(
                    f"first section is {form[0].bars} bars at {form[0].bpm:g} — "
                    f"{deadline_for(form[0]):.1f}s is under the deadline floor, so it is "
                    "played by the engine and nothing is waited for\n"
                )

        clock.start()
        daw.start_playing()
        scheduler = Scheduler(
            daw,
            clock,
            buffer,
            tracks,
            log,
            seed=seed,
            cues=cues,
            candidates=jumps,
            plan=shared,
            variants=variants,
            pitches=pitches_of(spec),
        )
        scheduler.run(form, endings=endings)
        if not scheduler.finished:
            sys.stderr.write(stopped_early(scheduler, len(form), clock.bar))
            return 1
        return 0
    finally:
        # A Ctrl-C during a performance must still stop the transport and still leave the
        # log on disk. Every step here is best-effort and none may raise: if Live has
        # gone away, it cannot be told to stop, and a teardown that threw would replace
        # the message explaining why with one about the teardown.
        if producer is not None:
            producer.stop()
        if controller is not None:
            controller.stop()
        if scheduler is not None:
            log.record(
                "session_ended",
                float(max(clock.beat, 0)),
                finished=scheduler.finished,
                bpm=spec.tempo_bpm,
                **spend_of(provider, budget),
            )
        for step, action in (
            ("stop listening", clock.stop),
            ("stop the transport", daw.stop_playing),
        ):
            try:
                action()
            except DawError as exc:
                sys.stderr.write(f"could not {step}: {exc}\n")
        log.flush()
        daw.close()
        if controller is not None:
            sys.stderr.write(render_cues(log))
        if scheduler is not None and setlist is not None:
            sys.stderr.write(
                render_checks(
                    setlist_checks(log.events, share_floor=args.share),
                    model_share(log.events),
                    phase="Phase 5",
                    wrote="from the setlist:",
                )
            )
        elif scheduler is not None and args.generate:
            checks = performance_checks(log.events, minimum_seconds=seconds)
            sys.stderr.write(render_checks(checks, model_share(log.events)))
        sys.stderr.write(f"{len(log)} events -> {args.log}\n")


if __name__ == "__main__":
    raise SystemExit(main())
