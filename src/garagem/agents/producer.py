"""The thread where the network lives. ADR-016 in code.

The scheduler runs a bar loop that must not wait; a section-shot takes four seconds. The
two meet at the `ScoreBuffer` and nowhere else — the producer offers sections into it,
the scheduler takes them out or plays the deterministic floor, and neither calls the
other. That is invariant 1: *separated by a data structure, never by a function call.*

Four rules this module exists to keep:

**No `DawPort`, ever.** The producer generates; the scheduler plays. A producer that
could write a clip would be a second thread with an opinion about Live's state, and
invariant 6 would have two enforcers instead of one.

**No retry** (P7, and ADR-000 §4.2 verbatim): *"If it overruns → cancel, log, use the
deterministic engine, and do not try again for that section."* An overrun is a
cancellation, not a timeout noticed afterwards, and `_attempted` is what makes "do not
try again" true rather than merely intended.

**Nothing escapes into the scheduler's thread.** Every failure here is an event in the
log. The scheduler's contract is that a missing section is `None`, and it has no code for
an exception because it should never see one.

**What reaches the buffer is always a whole band.** §4.3: *"if the stream is cut short,
write what arrived and complete the rest locally."* A two-part score offered as-is would
be worse than nothing — the scheduler writes only the instruments a score contains, so
the guitar and keys clips would still hold the *previous* section's notes and play them
under the new one. So a partial section is completed from `engines.band` before it is
offered, and the log says which parts were the model's.

`produce()` is separate from the loop for the same reason `Scheduler.tick()` is separate
from `run()`: it makes the whole thing testable against a cassette with no thread, no
clock and no sleeping.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from typing import Final

from garagem.agents.section import request_for, worth_asking
from garagem.domain import Instrument, Part, Section, SectionScore
from garagem.dsl import ParsedSection, SectionStream, realise
from garagem.dsl.errors import DslError
from garagem.engines import play_section
from garagem.llm import LLMProvider, ModelSpec, ProviderError, Request, Usage
from garagem.obs import EventLog
from garagem.theory import repair, validate
from garagem.transport import ScoreBuffer

# How long the loop waits before looking at the buffer again when there is nothing to do.
# A section lasts ten seconds or more, so a quarter of a second is far finer than the
# music needs and cheap enough not to matter.
IDLE_S: Final = 0.25

# How long `stop()` waits for the thread. Daemon, so a stuck join cannot hold the
# interpreter open — this only decides how long we are polite about it.
JOIN_TIMEOUT_S: Final = 2.0


class Producer:
    """Fills a `ScoreBuffer` from a model, on its own thread, without ever blocking one."""

    def __init__(
        self,
        provider: LLMProvider,
        buffer: ScoreBuffer,
        log: EventLog,
        sections: Sequence[Section],
        *,
        model: ModelSpec,
        seed: int = 0,
    ) -> None:
        self._provider = provider
        self._buffer = buffer
        self._log = log
        self._sections = tuple(sections)
        self._model = model
        self._seed = seed

        # Attempted once and never again, whatever the outcome (P7). A section that came
        # back malformed is not more likely to come back well the second time, and the
        # deterministic floor is already playing.
        self._attempted: set[int] = set()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Begin filling the buffer. Idempotent."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="producer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop, and wait briefly. Safe to call without `start`."""
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(JOIN_TIMEOUT_S)
            self._thread = None

    @property
    def attempted(self) -> frozenset[int]:
        """Which sections have had their one shot."""
        return frozenset(self._attempted)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ----------------------------------------------------------------------------- loop

    def _run(self) -> None:
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            index = self._next_wanted()
            if index is None:
                await asyncio.sleep(IDLE_S)
                continue
            await self.produce(index)

    def _next_wanted(self) -> int | None:
        """The first gap in the window that has not had its shot, in play order."""
        for index in self._buffer.wanted():
            if index < len(self._sections) and index not in self._attempted:
                return index
        return None

    # ------------------------------------------------------------------------ one shot

    async def produce(self, index: int) -> bool:
        """One section-shot. True when a score reached the buffer.

        Never raises. Every failure is an event, because the scheduler on the other side
        of the buffer has no code for an exception and should not need any.
        """
        if index >= len(self._sections):
            return False
        self._attempted.add(index)
        section = self._sections[index]
        request = request_for(section, self._model)

        if not worth_asking(section):
            # Not enough musical time for any model to answer inside the deadline.
            # Spending the call would buy a cancelled stream and the fallback we already
            # have for free.
            self._log.record(
                "fallback",
                0.0,
                section=index,
                reason="no_time",
                deadline_s=round(request.deadline_s, 2),
            )
            return False

        self._log.record(
            "section_requested",
            0.0,
            section=index,
            model=self._model.id,
            deadline_s=round(request.deadline_s, 2),
        )

        try:
            parsed, usage = await asyncio.wait_for(
                self._stream(section, request), timeout=request.deadline_s
            )
        except TimeoutError:
            # The deadline *is* a cancellation (§4.2). `wait_for` cancelled the stream;
            # the section is already in `_attempted`, so it will not be asked again.
            self._log.record(
                "deadline_missed",
                0.0,
                section=index,
                model=self._model.id,
                deadline_s=round(request.deadline_s, 2),
            )
            return False
        except (ProviderError, DslError) as error:
            self._log.record(
                "fallback",
                0.0,
                section=index,
                model=self._model.id,
                reason=type(error).__name__,
                detail=str(error)[:200],
            )
            return False

        return self._publish(index, parsed, usage)

    async def _stream(self, section: Section, request: Request) -> tuple[ParsedSection, Usage]:
        """Drive the stream through the incremental parser. Cancellable at every await."""
        stream = SectionStream(section)
        usage = Usage()
        async for event in self._provider.stream(request):
            stream.feed(event)
            if event.type == "done":
                usage = event.usage
        return stream.result(), usage

    # ----------------------------------------------------------------------- publishing

    def _publish(self, index: int, parsed: ParsedSection, usage: Usage) -> bool:
        """Realise, complete, repair, offer. What lands in the buffer is a whole band."""
        seed = self._seed + index
        section = self._sections[index]

        for violation in parsed.violations:
            self._log.record(
                "schema_violation",
                0.0,
                section=index,
                model=self._model.id,
                rule=violation.rule,
                instrument=str(violation.instrument),
                detail=violation.detail[:160],
            )

        score = realise(parsed, seed)
        if not score.parts:
            self._log.record("fallback", 0.0, section=index, reason="nothing_parsed")
            return False

        from_model = sorted(str(instrument) for instrument in score.instruments())
        score = self._completed(score, section, seed)

        repaired, left = repair(score)
        if repaired != score:
            self._log.record(
                "violation_repaired",
                0.0,
                section=index,
                rules=",".join(sorted({violation.rule for violation in validate(score)})),
            )
        if left:
            self._log.record(
                "fallback",
                0.0,
                section=index,
                reason="irreparable",
                rules=",".join(sorted({violation.rule for violation in left})),
            )
            return False

        accepted = self._buffer.offer(index, repaired)
        # `section_parsed`, not `section_generated`: the scheduler logs the latter when it
        # *takes* a section, and one kind meaning two things makes every rate computed
        # from it wrong. This one is the numerator of "did the model deliver"; the
        # scheduler's is "what actually played".
        self._log.record(
            "section_parsed" if accepted else "fallback",
            0.0,
            section=index,
            model=self._model.id,
            seed=seed,
            source="model",
            parts=",".join(from_model),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            **({} if accepted else {"reason": "too_late"}),
        )
        return accepted

    def _completed(self, score: SectionScore, section: Section, seed: int) -> SectionScore:
        """Fill whatever the model did not send from the deterministic engine.

        §4.3, verbatim: *"if the stream is cut short, write what arrived and complete the
        rest locally."* The scheduler writes only the instruments a score contains, so an
        incomplete score would leave the previous section still sounding underneath this
        one — a partial section offered as-is is worse than no section at all.
        """
        missing = [instrument for instrument in Instrument if instrument not in score.instruments()]
        if not missing:
            return score
        floor = play_section(section, seed)
        filled: list[Part] = [floor.part(instrument) for instrument in missing]
        return score.model_copy(
            update={
                "parts": tuple(
                    sorted(
                        (*score.parts, *filled),
                        key=lambda part: list(Instrument).index(part.instrument),
                    )
                )
            }
        )
