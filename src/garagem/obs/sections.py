"""The arithmetic behind Phase 3's exit criteria. Pure, so the suite checks it for free.

Three of the four criteria are *rates*:

> ≥95% schema conformance on the first pass; ≥80% validator approval without repair;
> p95 section latency < 40% of the available musical time.

Rates are easy to compute and easy to compute *dishonestly*, so this module fixes the
definitions in one place:

- **The denominator is every section asked for**, including the ones that failed, timed
  out or came back as prose. A conformance rate over "the responses we could parse" is a
  fact about the parser.
- **"First pass" means before the repairer runs.** A section the repairer rescued is a
  section the model got wrong, and counting it as conformant would make the repairer look
  like quality instead of like insurance.
- **Percentiles are nearest-rank**, never interpolated — the same rule `obs/latency.py`
  fought for in Phase 0. With thirty samples, an interpolated p95 invents a number that
  was never observed.
- **Latency is measured against the section's own deadline**, not against a constant. A
  four-bar section at 180 BPM has half the budget of an eight-bar one at 132, and a p95
  in seconds would hide that.

Split like `obs/latency.py`: everything here is arithmetic over values somebody else
measured, so the default suite tests it with no network and no key.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

FROZEN = ConfigDict(frozen=True, extra="forbid")

# ADR-000 §7. Written here so the report can say "met" or "not met" rather than leaving
# the reader to compare against a document.
CONFORMANCE_TARGET: Final = 0.95
APPROVAL_TARGET: Final = 0.80
LATENCY_TARGET: Final = 1.0  # p95 as a fraction of the section's own deadline


class Shot(BaseModel):
    """One section-shot, measured. What the rig appends to its JSONL, one per line."""

    model_config = FROZEN

    at: datetime
    model: str
    # The briefing, so a bad row can be reproduced rather than guessed at.
    section: str
    bars: int
    bpm: float

    ok: bool = True
    error: str = ""
    # Billed but unpriced. `Usage` rides the `done` event and a stream cancelled at its
    # deadline never sends one, so a timed-out call books $0.0000 while Anthropic bills
    # for every token it generated. Thirty such calls once recorded a round as free
    # (`phase-3-findings.md` §14). The estimate is not recoverable from the stream, but
    # the *hole* is, and a cost report that does not name it is a wrong cost report.
    unpriced: bool = False

    # Timing, against this section's own deadline.
    deadline_s: float = Field(gt=0)
    ttft_s: float | None = None
    total_s: float | None = None

    # Conformance, before the repairer runs. `violations` is every rule the parser and
    # the validator raised; `repaired` says whether what was left could be fixed.
    violations: tuple[str, ...] = ()
    # What the violations actually said. A rule name tells you a rate; only the detail
    # tells you what to write in the prompt, and diagnosing without it means paying for
    # the same thirty calls twice.
    details: tuple[str, ...] = ()
    # The DSL exactly as it arrived. It is what makes a run re-scorable offline: a parser
    # fix can be tested against thirty real responses for nothing instead of for another
    # thirty calls. Learned by not having it — the first two runs of this rig each had to
    # be repeated because the row said `schema` and not which line.
    dsl: str = ""
    parts: int = 0
    truncated: bool = False
    repaired: bool = False
    left_after_repair: tuple[str, ...] = ()

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)

    @property
    def conformant(self) -> bool:
        """No violation at all, first pass. The strictest reading, and the right one."""
        return self.ok and not self.violations and not self.truncated

    @property
    def approved(self) -> bool:
        """Playable without the repairer touching it."""
        return self.conformant and not self.repaired

    @property
    def usable(self) -> bool:
        """Reached the buffer at all, repaired or not. What P2 actually needs."""
        return self.ok and not self.left_after_repair and self.parts > 0

    @property
    def within_deadline(self) -> bool:
        return self.ok and self.total_s is not None and self.total_s <= self.deadline_s

    @property
    def deadline_fraction(self) -> float | None:
        """Latency as a fraction of this section's own budget. 1.0 is exactly on time.

        `None` for a call that failed, and that is not a detail: a call cancelled *at*
        its deadline has an elapsed time of exactly the deadline, so counting it as a
        latency sample pins the percentile to 1.00x whatever the successful calls did.
        The first run of this rig reported `p95 1.00x, max 1.00x, over deadline 0/30`,
        which is incoherent on its face — three failures were setting the number.

        Failures are counted; `failures` and `over_deadline` are where they show up.
        """
        if self.total_s is None or not self.ok:
            return None
        return self.total_s / self.deadline_s


class Report(BaseModel):
    """The three rates, their sample size, and whether each clears its bar."""

    model_config = FROZEN

    n: int
    # How many briefings were drawn against how many survived `worth_asking`. Raising
    # `MIN_DEADLINE_S` improves every rate below by removing the hardest cases from the
    # denominator, so a run that does not publish both numbers is publishing a rate it
    # quietly narrowed. `None` when the caller did not say.
    drawn: int | None = None
    failures: int
    unpriced: int = 0
    conformance: float | None
    approval: float | None
    usable: float | None
    p50_fraction: float | None
    p95_fraction: float | None
    max_fraction: float | None
    over_deadline: int
    total_cost_usd: Decimal
    by_rule: dict[str, int]

    @property
    def conformance_met(self) -> bool:
        return self.conformance is not None and self.conformance >= CONFORMANCE_TARGET

    @property
    def approval_met(self) -> bool:
        return self.approval is not None and self.approval >= APPROVAL_TARGET

    @property
    def latency_met(self) -> bool:
        return self.p95_fraction is not None and self.p95_fraction <= LATENCY_TARGET


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank, never interpolated. `obs/latency.py`'s rule, and for its reason."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-q * len(ordered) // 1))))
    return ordered[rank - 1]


def summarise(shots: Iterable[Shot], *, drawn: int | None = None) -> Report:
    """The whole measurement, from the raw rows. Pure.

    `drawn` is how many briefings the rig started from, before `worth_asking`
    filtered them. Pass it whenever it is known: without it the report can state a
    conformance rate but cannot say what population it was measured over, and
    `MIN_DEADLINE_S` moves that population.
    """
    rows = list(shots)
    if not rows:
        return Report(
            n=0,
            drawn=drawn,
            failures=0,
            conformance=None,
            approval=None,
            usable=None,
            p50_fraction=None,
            p95_fraction=None,
            max_fraction=None,
            over_deadline=0,
            total_cost_usd=Decimal(0),
            by_rule={},
        )

    fractions = [f for shot in rows if (f := shot.deadline_fraction) is not None]
    by_rule: dict[str, int] = {}
    for shot in rows:
        for rule in shot.violations:
            by_rule[rule] = by_rule.get(rule, 0) + 1

    return Report(
        n=len(rows),
        drawn=drawn,
        failures=sum(1 for shot in rows if not shot.ok),
        unpriced=sum(1 for shot in rows if shot.unpriced),
        conformance=sum(1 for shot in rows if shot.conformant) / len(rows),
        approval=sum(1 for shot in rows if shot.approved) / len(rows),
        usable=sum(1 for shot in rows if shot.usable) / len(rows),
        p50_fraction=percentile(fractions, 0.50) if fractions else None,
        p95_fraction=percentile(fractions, 0.95) if fractions else None,
        max_fraction=max(fractions) if fractions else None,
        over_deadline=sum(1 for shot in rows if not shot.within_deadline and shot.ok),
        total_cost_usd=sum((shot.cost_usd for shot in rows), Decimal(0)),
        by_rule=dict(sorted(by_rule.items(), key=lambda item: (-item[1], item[0]))),
    )


def render_report(shots: Sequence[Shot], *, drawn: int | None = None) -> str:
    """Markdown, stating each criterion and whether it is met. No hedging."""
    report = summarise(shots, drawn=drawn)
    if not report.n:
        return "# Section-shot conformance\n\nNo samples yet.\n"

    lines = [
        "# Section-shot conformance",
        "",
        f"Samples: **{report.n}** · failures: {report.failures} · "
        f"spent: ${report.total_cost_usd:.4f}"
        + (
            f" over {report.n - report.unpriced} priced call(s) — "
            f"**{report.unpriced} were billed and could not be priced**"
            if report.unpriced
            else ""
        ),
        "",
        "Rates are over every section asked for, including the ones that failed. "
        "Conformance and approval are measured **before the repairer runs**: a section "
        "the repairer rescued is a section the model got wrong.",
        "",
        *_population(report),
        "| criterion | measured | target | met |",
        "|---|---|---|---|",
        _row("schema conformance, first pass", report.conformance, CONFORMANCE_TARGET, ">="),
        _row("validator approval, no repair", report.approval, APPROVAL_TARGET, ">="),
        _row("p95 latency / section deadline", report.p95_fraction, LATENCY_TARGET, "<="),
        "",
        f"Reached the buffer at all (repaired or not): {_percent(report.usable)} — "
        "this is the number P2 actually rests on.",
        "",
        "## Latency, as a fraction of each section's own deadline",
        "",
        f"p50 {_fraction(report.p50_fraction)} · p95 {_fraction(report.p95_fraction)} · "
        f"max {_fraction(report.max_fraction)} · over deadline: "
        f"{report.over_deadline}/{report.n}",
        "",
        "Nearest-rank percentiles over the successful calls, never interpolated. "
        "A fraction rather than seconds, because a 4-bar section at 180 BPM has half the "
        "budget of an 8-bar one at 132.",
    ]

    if report.by_rule:
        lines += [
            "",
            "## What the model got wrong",
            "",
            "| rule | times |",
            "|---|---|",
            *[f"| `{rule}` | {count} |" for rule, count in report.by_rule.items()],
            "",
            "A rule that dominates this table is usually a prompt that never stated it. "
            "Fix the prompt, not the parser.",
        ]

    return "\n".join(lines) + "\n"


def _population(report: Report) -> list[str]:
    """What the rates are measured *over*, whenever the caller can say.

    `worth_asking` removes briefings whose deadline is under `MIN_DEADLINE_S`, and those
    are the hardest ones. Raising that constant therefore improves every rate below it by
    shrinking the denominator, which is indistinguishable in the numbers from the model
    getting better. So the report says both, or says that it cannot.
    """
    if report.drawn is None:
        return [
            "The askable fraction was not recorded for this run, so these rates cannot "
            "be compared against one that raised `MIN_DEADLINE_S`.",
            "",
        ]
    asked = report.n
    return [
        f"Measured over **{asked} of {report.drawn}** briefings drawn "
        f"({asked / report.drawn:.0%} askable). The rest fell under `MIN_DEADLINE_S` and "
        "were played by the deterministic engine, which is P2 and costs nothing — but "
        "they are the hardest sections, so a rate that does not name this number is a "
        "rate with a hidden denominator.",
        "",
    ]


def _row(name: str, value: float | None, target: float, sense: str) -> str:
    met = "—" if value is None else ("**yes**" if _meets(value, target, sense) else "no")
    return f"| {name} | {_percent(value)} | {sense} {target:.0%} | {met} |"


def _meets(value: float, target: float, sense: str) -> bool:
    return value >= target if sense == ">=" else value <= target


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def _fraction(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}x"


def append_shot(path: Path, shot: Shot) -> None:
    """Append-only: runs accumulate into one record, as the latency rig's do."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(shot.model_dump_json() + "\n")


def load_shots(path: Path) -> list[Shot]:
    if not path.exists():
        return []
    return [
        Shot.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
