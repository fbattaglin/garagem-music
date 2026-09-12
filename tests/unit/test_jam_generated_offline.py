"""A whole performance with a model in it, against a fake Live and a fake provider.

Phase 2's Step 34 with the LLM wired in. It asserts on the event log rather than on the
audio, and it costs milliseconds: `Scheduler.tick` and `Producer.produce` are both
separate from their loops, so three minutes of music is a for-loop.

**If this does not pass, do not spend money on `bench_sections.py`.** The same rule that
made Phase 1 close on its first live attempt and Phase 2 on its first three-minute run.

The test that matters most is the last one: a provider that dies mid-performance must
leave the music playing. That is P2 — *an API failure degrades the music, it never
silences it* — as a mechanical check rather than an aspiration.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from garagem.agents import Producer, structural, worth_asking
from garagem.daw import FakeDawAdapter
from garagem.domain import Cue, CueKind, Feel, Instrument, Section
from garagem.dsl import brief, serialize_section
from garagem.engines import SongBrief, arrange, endings_for, play_section, with_climax
from garagem.llm import (
    FakeProvider,
    FakeResponse,
    LLMProvider,
    ProviderUnavailableError,
    Request,
    StopReason,
    StreamEvent,
    Usage,
    load_catalog,
)
from garagem.obs import Event, EventLog, rate_of
from garagem.transport import BarClock, CueQueue, FormPlan, Scheduler, ScoreBuffer

ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_catalog(ROOT / "config" / "models.toml")
MODEL = structural(CATALOG)

THREE_MINUTES = 180.0
BPM = 132.0
SEED = 7

TRACKS = {
    Instrument.DRUMS: 0,
    Instrument.BASS: 1,
    Instrument.GUITAR: 2,
    Instrument.KEYS: 3,
}

BRIEF = SongBrief(key=4, scale="minor", bpm=BPM, feel=Feel.STRAIGHT8, minimum_seconds=THREE_MINUTES)


def perfect_response(section: Section, seed: int) -> FakeResponse:
    """What a perfectly conformant model would send: our own serializer's output."""
    return FakeResponse(
        tool_name="write_section",
        tool_input=json.dumps({"dsl": serialize_section(play_section(section, seed))}),
        stop=StopReason.TOOL_USE,
        usage=Usage(input_tokens=1200, output_tokens=340),
    )


class Jam:
    """A whole performance: producer, scheduler, fake Live, simulated musical time."""

    def __init__(
        self, provider: LLMProvider | None = None, seed: int = SEED, *, arranged: bool = False
    ) -> None:
        self.form = with_climax(arrange(BRIEF, seed)) if arranged else arrange(BRIEF, seed)
        self.endings = endings_for(self.form) if arranged else None
        self.daw = FakeDawAdapter(scenes=4)
        self.clock = BarClock(self.daw)
        self.clock.start()
        self.buffer = ScoreBuffer()
        self.log = EventLog(None)
        # One response per section the producer will actually **ask** about, in the order
        # it will ask. `FakeProvider` serves a positional queue, so a section skipped by
        # `worth_asking` shifts every later answer onto the wrong briefing — which is
        # exactly what happened when `MIN_DEADLINE_S` rose to 5.0 s and the 4-bar intro
        # and outro stopped being asked: 49 `section_mismatch` violations out of a
        # provider that only ever sends perfect output. The filter belongs here, not in
        # an assertion further down.
        self.provider = provider or FakeProvider(
            [
                perfect_response(section, seed + index)
                for index, section in enumerate(self.form)
                if worth_asking(section)
            ]
        )
        self.producer = Producer(
            self.provider, self.buffer, self.log, self.form, model=MODEL, seed=seed
        )
        self.scheduler = Scheduler(self.daw, self.clock, self.buffer, TRACKS, self.log, seed=seed)
        self.beats = 0

    def play(self, limit: int = 20_000, *, prime: bool = True) -> Jam:
        """Generate ahead, then advance the music a beat at a time. No threads, no sleep.

        The producer is driven synchronously between beats rather than on its thread: the
        thread is tested in `test_producer.py`, and what this file is about is what the
        two halves do to each other through the buffer.

        `prime` fills the buffer before the transport rolls, which is what `scripts/jam.py`
        does with a bounded wait. Without it the first section is always a fallback — the
        scheduler writes and fires before any generation can finish.
        """
        if prime:
            self._generate_ahead()
        self.scheduler.begin(self.form, endings=self.endings)
        while not self.scheduler.finished and self.beats < limit:
            self._generate_ahead()
            self.daw.push_beat(self.beats)
            self.scheduler.tick()
            self.beats += 1
        self.clock.stop()
        return self

    def _generate_ahead(self) -> None:
        index = self.producer._next_wanted()
        if index is not None:
            asyncio.run(self.producer.produce(index))

    def of_kind(self, kind: str) -> list[Event]:
        return list(self.log.of_kind(kind))

    def sources(self) -> list[str]:
        return [str(event.detail.get("source", "floor")) for event in self.of_kind("fallback")]

    @property
    def asked(self) -> list[Section]:
        """The sections there was musical time to ask about. The real denominator.

        `MIN_DEADLINE_S` is 5.0 s from measurement, so a 4-bar intro at 132 BPM — 2.91 s
        of budget — is played by the deterministic engine without a call being spent.
        That is P2 working, not the model failing, and every rate below counts it as such.
        """
        return [section for section in self.form if worth_asking(section)]


# ------------------------------------------------------------------- the model played it


def test_the_model_wrote_every_section_there_was_time_to_ask_about() -> None:
    """The buffer is finally being filled. In Phase 2 this was zero out of fourteen."""
    jam = Jam().play()
    parsed = jam.of_kind("section_parsed")
    assert len(parsed) == len(jam.asked)
    assert all(event.detail["source"] == "model" for event in parsed)


def test_the_sections_not_asked_about_are_declared_rather_than_failed() -> None:
    """The distinction the whole rate rests on: declining is not failing.

    A 4-bar intro leaves 2.91 s, under the 5.0 s that 57 measured calls say is needed.
    Asking would spend money on a cancelled stream and produce the fallback we get free.
    So it is not asked — and the log has to say *that*, not report a model that lost.
    """
    jam = Jam().play()
    declined = [
        event for event in jam.of_kind("fallback") if event.detail.get("reason") == "no_time"
    ]
    assert len(declined) == len(jam.form) - len(jam.asked)
    assert declined, "the fixture's form no longer contains a short section; this proves nothing"


def test_the_scheduler_took_them_out_of_the_buffer_rather_than_generating() -> None:
    jam = Jam().play()
    from_buffer = [
        event
        for event in jam.of_kind("section_generated")
        if event.detail.get("source") == "buffer"
    ]
    assert len(from_buffer) == len(jam.asked)


def test_the_floor_played_only_where_we_chose_not_to_ask() -> None:
    """Every fallback is accounted for by a decision, never by a failure.

    The scheduler logs `not_in_buffer` when a section it needs is not there. That is
    fine when we deliberately never asked for it and a defect when we did — so the two
    counts have to match, and any excess is the model losing a section silently.
    """
    jam = Jam().play()
    reasons = [str(event.detail.get("reason")) for event in jam.of_kind("fallback")]
    declined = reasons.count("no_time")
    assert reasons.count("not_in_buffer") == declined
    assert set(reasons) <= {"no_time", "not_in_buffer"}, (
        f"a fallback happened for a reason nobody chose: {sorted(set(reasons))}"
    )


def test_without_priming_the_first_section_is_always_the_floor() -> None:
    """A race the music always wins, so `scripts/jam.py` waits before it starts.

    `Scheduler.begin` writes and fires section 0 immediately; a four-second generation
    cannot beat that. Stated here as the property it is rather than fixed in the
    scheduler, because the scheduler starting late would be a worse bug than the floor
    playing one section.
    """
    jam = Jam().play(prime=False)
    reasons = [
        str(event.detail.get("reason"))
        for event in jam.of_kind("fallback")
        if event.detail.get("section") == 0
    ]
    assert "not_in_buffer" in reasons


def test_the_conformance_rate_over_a_whole_performance_is_perfect() -> None:
    """Against a provider that sends our own serializer's output, it has to be."""
    jam = Jam().play()
    assert rate_of(jam.log, "schema_violation") == 0.0
    assert rate_of(jam.log, "section_parsed") == 1.0


def test_the_two_similar_kinds_count_different_things() -> None:
    """`section_parsed` is the model delivering; `section_generated` is the scheduler
    taking. While they shared a name the computed rate ran over 100%."""
    jam = Jam().play()
    assert rate_of(jam.log, "section_parsed") == 1.0
    assert len(jam.of_kind("section_generated")) == len(jam.asked)


# ------------------------------------------------------ still everything Phase 2 proved


def test_the_run_is_still_three_minutes_with_four_section_changes() -> None:
    jam = Jam().play()
    assert jam.beats * 60.0 / BPM >= THREE_MINUTES
    assert len(jam.of_kind("scene_fired")) - 1 >= 4


def test_no_write_landed_in_the_scene_that_was_playing() -> None:
    """Invariant 6 does not get a discount because a model is involved."""
    jam = Jam().play()
    playing: object = None
    for event in jam.log:
        if event.kind == "section_written" and playing is not None:
            assert event.detail["scene"] != playing
        elif event.kind == "scene_fired":
            playing = event.detail["scene"]


def test_every_transition_still_had_a_bar_of_slack() -> None:
    jam = Jam().play()
    transitions = [e for e in jam.of_kind("scene_fired") if not e.detail["first"]]
    assert transitions
    assert all(int(str(event.detail["slack_bars"])) >= 1 for event in transitions)


def test_every_section_reaching_live_is_a_whole_band() -> None:
    """A partial score would leave the previous section still sounding underneath."""
    jam = Jam().play()
    for index in range(len(jam.form)):
        score = jam.buffer.take(index)
        if score is not None:
            assert score.instruments() == frozenset(Instrument)


# --------------------------------------------------------------------------- no network


def test_the_run_makes_no_network_call() -> None:
    """The fuse is autouse, so this is free — asserted so the claim is visible."""
    import socket

    assert socket.socket.connect.__name__ == "refuse"
    assert socket.socket.sendto.__name__ == "refuse_datagram"
    Jam().play()


# ---------------------------------------------------------------------------- P2 itself


def test_a_provider_that_dies_midway_leaves_the_music_playing() -> None:
    """P2, mechanically: an API failure degrades the music, it never silences it.

    The provider answers twice and then refuses everything. The performance must still
    run to the end of its form, with every remaining section played by the deterministic
    engine and every failure in the log.
    """
    form = arrange(BRIEF, SEED)
    provider = FakeProvider(
        [perfect_response(section, SEED + index) for index, section in enumerate(form)],
        fail_with=ProviderUnavailableError("the network went away"),
        fail_after=0,
    )
    jam = Jam(provider=provider).play()

    assert jam.scheduler.finished
    assert len(jam.of_kind("scene_fired")) == len(jam.form)
    assert jam.of_kind("fallback")
    assert jam.beats * 60.0 / BPM >= THREE_MINUTES


def test_a_failed_section_is_never_retried() -> None:
    """§4.2. A retry would spend the next section's deadline on the last one's mistake."""
    provider = FakeProvider(
        [perfect_response(arrange(BRIEF, SEED)[0], SEED)],
        fail_with=ProviderUnavailableError("gone"),
        fail_after=0,
    )
    jam = Jam(provider=provider).play()
    requested = [event.detail["section"] for event in jam.of_kind("section_requested")]
    assert len(requested) == len(set(requested))


# ------------------------------------------------------------------------ reproducibility


def test_the_whole_generated_run_is_reproducible() -> None:
    """Invariant 7 at the scale of a performance, with a model in the loop."""

    def shape(jam: Jam) -> list[tuple[str, float, dict[str, object]]]:
        return [
            (event.kind, event.at_beats, {k: v for k, v in event.detail.items() if k != "ms"})
            for event in jam.log
        ]

    assert shape(Jam().play()) == shape(Jam().play())


def test_a_different_seed_is_a_different_performance() -> None:
    first = Jam(seed=7).play()
    second = Jam(seed=11).play()
    assert [e.detail.get("name") for e in first.of_kind("scene_fired")] != [
        e.detail.get("name") for e in second.of_kind("scene_fired")
    ] or first.buffer.take(0) != second.buffer.take(0)


# ------------------------------------------------------------------------------ Phase 4


def test_every_section_is_measured_whoever_wrote_it() -> None:
    """The metrics criterion with the model in the loop: buffer and floor alike."""
    jam = Jam(arranged=True).play()
    written = [event.detail["section"] for event in jam.of_kind("section_written")]
    measured = [event.detail["section"] for event in jam.of_kind("section_measured")]
    assert measured == written
    assert len(set(measured)) == len(jam.form)


def test_the_models_sections_get_the_same_endings_as_the_floors() -> None:
    """ADR-020: the form does not depend on who wrote the groove."""
    jam = Jam(arranged=True).play()
    assert jam.endings is not None
    written = [str(event.detail["ending"]) for event in jam.of_kind("section_written")]
    assert written == [str(ending) for ending in jam.endings]
    assert jam.of_kind("transition_declined") == []
    from_buffer = [
        event
        for event in jam.of_kind("section_generated")
        if event.detail.get("source") == "buffer"
    ]
    assert len(from_buffer) == len(jam.asked)


# ------------------------------------------------------------------- a jump with the model in


class Answering:
    """A perfect model for whatever briefing it is sent, including ones a jump created."""

    name = "answering"

    def __init__(self, plan: FormPlan, seed: int) -> None:
        self.plan = plan
        self.seed = seed
        self.asked: list[str] = []

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        content = request.messages[0].content
        self.asked.append(content)
        section = next(s for s in self.plan.sections() if brief(s) == content)
        response = perfect_response(section, self.seed)
        async for event in FakeProvider([response]).stream(request):
            yield event


def a_jam_with_a_jump(cue_beat: int) -> tuple[Scheduler, EventLog, Answering, FormPlan]:
    form = with_climax(arrange(BRIEF, SEED))
    plan = FormPlan(form, endings_for(form))
    daw = FakeDawAdapter(scenes=4)
    clock = BarClock(daw)
    clock.start()
    buffer = ScoreBuffer()
    log = EventLog(None)
    queue = CueQueue(stamp=lambda: clock.beat)
    provider = Answering(plan, SEED)
    producer = Producer(provider, buffer, log, plan, model=MODEL, seed=SEED)
    scheduler = Scheduler(
        daw, clock, buffer, TRACKS, log, seed=SEED, cues=queue, candidates={"chorus": 2}, plan=plan
    )
    scheduler.begin(form, endings=endings_for(form))
    beat = 0
    while not scheduler.finished and beat < 20_000:
        index = producer._next_wanted()
        if index is not None:
            asyncio.run(producer.produce(index))
        daw.push_beat(beat)
        if beat == cue_beat:
            queue.offer(Cue(kind=CueKind.CHORUS_NOW))
        scheduler.tick()
        beat += 1
    return scheduler, log, provider, plan


def test_after_a_jump_the_model_is_asked_for_the_section_that_follows_the_chorus() -> None:
    """ADR-021's second new criterion, offline: the re-planned briefing reaches the model."""
    scheduler, log, provider, plan = a_jam_with_a_jump(cue_beat=25)
    (applied,) = log.of_kind("cue_applied")
    target = int(str(applied.detail["section"]))
    following = plan.at(target + 1)
    assert following is not None
    assert brief(following) in provider.asked
    assert scheduler.finished


def test_a_stale_section_never_plays_across_a_jump() -> None:
    """Every section written after the jump is the plan's own briefing, whoever wrote it."""
    scheduler, log, _, plan = a_jam_with_a_jump(cue_beat=25)
    written = [int(str(event.detail["section"])) for event in log.of_kind("section_written")]
    generated = {
        int(str(event.detail["section"])): event
        for event in log.of_kind("section_generated")
        if event.detail.get("source") == "buffer"
    }
    assert written[-1] == len(plan) - 1
    assert generated, "the model's sections never reached the buffer; this proves nothing"
    assert all(index < len(plan) for index in generated)
    assert scheduler.sections == plan.sections()
