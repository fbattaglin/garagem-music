"""The arithmetic behind the exit criteria, checked before a cent is spent.

Rates are easy to compute and easy to compute dishonestly, so what these tests pin down
is mostly the *definitions*: the denominator is every section asked for, "first pass"
means before the repairer, and a percentile is nearest-rank.

The rig itself is loaded with the `importlib` idiom from `test_bench_latency.py` and its
network half is never called — `--yes` is what sends, and nothing here passes it.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from garagem.obs import APPROVAL_TARGET, CONFORMANCE_TARGET, Shot, append_shot, load_shots
from garagem.obs.sections import percentile, render_report, summarise

ROOT = Path(__file__).resolve().parents[2]


def _load_rig() -> ModuleType:
    path = ROOT / "scripts" / "bench_sections.py"
    spec = importlib.util.spec_from_file_location("bench_sections", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_sections"] = module
    spec.loader.exec_module(module)
    return module


rig = _load_rig()


def a_shot(**extra: object) -> Shot:
    base: dict[str, object] = {
        "at": datetime.now(UTC),
        "model": "claude-sonnet-5",
        "section": "verse",
        "bars": 8,
        "bpm": 132.0,
        "deadline_s": 5.82,
        "ttft_s": 1.4,
        "total_s": 4.3,
        "parts": 4,
    }
    return Shot.model_validate(base | extra)


# ----------------------------------------------------------------------- one shot's verdict


def test_a_clean_shot_is_conformant_and_approved() -> None:
    shot = a_shot()
    assert shot.conformant
    assert shot.approved
    assert shot.usable
    assert shot.within_deadline


def test_a_shot_with_one_violation_is_not_conformant() -> None:
    """ "First pass" is the strictest reading, and the right one."""
    assert not a_shot(violations=("schema",)).conformant


def test_a_shot_the_repairer_rescued_is_not_approved_but_is_usable() -> None:
    """A section the repairer fixed is a section the model got wrong.

    Counting it as approved would make the repairer look like quality rather than like
    insurance — and P2 rests on `usable`, which is the number that says the music played.
    """
    shot = a_shot(violations=("range",), repaired=True)
    assert not shot.approved
    assert shot.usable


def test_a_truncated_shot_is_not_conformant_even_with_no_violation() -> None:
    assert not a_shot(truncated=True).conformant


def test_a_failed_call_is_not_usable_and_still_counts() -> None:
    shot = a_shot(ok=False, error="503", parts=0)
    assert not shot.usable
    assert not shot.within_deadline


def test_a_shot_that_could_not_be_repaired_is_not_usable() -> None:
    assert not a_shot(left_after_repair=("range",)).usable


def test_latency_is_measured_against_the_sections_own_deadline() -> None:
    """A 4-bar section at 180 BPM has half the budget of an 8-bar one at 132."""
    assert a_shot(total_s=2.91, deadline_s=5.82).deadline_fraction == pytest.approx(0.5)
    assert a_shot(total_s=2.91, deadline_s=2.91).deadline_fraction == pytest.approx(1.0)


def test_a_shot_over_its_deadline_is_named_as_such() -> None:
    assert not a_shot(total_s=7.0).within_deadline


# ------------------------------------------------------------------------------ the rates


def test_the_denominator_is_every_section_asked_for() -> None:
    """Including the ones that failed. A rate over what parsed is a fact about the parser."""
    report = summarise([a_shot(), a_shot(ok=False, parts=0), a_shot(violations=("schema",))])
    assert report.n == 3
    assert report.conformance == pytest.approx(1 / 3)
    assert report.failures == 1


def test_an_empty_run_has_no_rates_rather_than_zero_ones() -> None:
    report = summarise([])
    assert report.n == 0
    assert report.conformance is None
    assert not report.conformance_met


def test_the_targets_are_the_ones_adr_zero_states() -> None:
    assert CONFORMANCE_TARGET == 0.95
    assert APPROVAL_TARGET == 0.80


def test_a_run_at_the_target_meets_it() -> None:
    shots = [a_shot() for _ in range(19)] + [a_shot(violations=("schema",))]
    report = summarise(shots)
    assert report.conformance == pytest.approx(0.95)
    assert report.conformance_met


def test_a_run_just_under_the_target_does_not() -> None:
    shots = [a_shot() for _ in range(18)] + [a_shot(violations=("schema",)) for _ in range(2)]
    assert not summarise(shots).conformance_met


def test_the_rules_are_counted_and_ordered_by_how_often_they_broke() -> None:
    """A rule that dominates the table is usually a prompt that never stated it."""
    shots = [
        a_shot(violations=("schema",)),
        a_shot(violations=("schema",)),
        a_shot(violations=("range",)),
    ]
    assert list(summarise(shots).by_rule) == ["schema", "range"]


def test_cost_is_totalled_as_a_decimal() -> None:
    shots = [a_shot(cost_usd=Decimal("0.0055")) for _ in range(3)]
    assert summarise(shots).total_cost_usd == Decimal("0.0165")


# ------------------------------------------------------------------------- the percentile


def test_the_percentile_is_nearest_rank_and_never_interpolated() -> None:
    """With thirty samples, an interpolated p95 invents a number nobody observed."""
    values = [float(n) for n in range(1, 21)]
    assert percentile(values, 0.95) == 19.0
    assert percentile(values, 0.50) == 10.0


def test_the_percentile_of_one_value_is_that_value() -> None:
    assert percentile([4.2], 0.95) == 4.2


def test_a_percentile_of_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="no values"):
        percentile([], 0.95)


def test_p95_is_reported_as_a_fraction_of_the_deadline() -> None:
    """Two slow calls in twenty move the p95; one does not, and that is the point.

    Nearest-rank puts p95 at the 19th of 20 samples, so a single outlier stays out of it
    while `max` records it. An interpolated p95 would have smeared that one call across
    the number and made the tail look worse than it is — or better, depending on which
    side it fell. Phase 0 fought for this rule; this is what it buys.
    """
    one_slow = summarise([a_shot(total_s=2.0) for _ in range(19)] + [a_shot(total_s=11.0)])
    assert one_slow.p95_fraction is not None
    assert one_slow.p95_fraction < 1.0
    assert one_slow.max_fraction is not None
    assert one_slow.max_fraction > 1.0
    assert one_slow.over_deadline == 1
    assert one_slow.latency_met

    two_slow = summarise(
        [a_shot(total_s=2.0) for _ in range(18)] + [a_shot(total_s=11.0) for _ in range(2)]
    )
    assert two_slow.p95_fraction is not None
    assert two_slow.p95_fraction > 1.0
    assert not two_slow.latency_met


# ------------------------------------------------------------------------------ the report


def test_the_report_states_each_criterion_and_whether_it_is_met() -> None:
    text = render_report([a_shot() for _ in range(20)])
    assert "schema conformance" in text
    assert "validator approval" in text
    assert "p95 latency" in text
    assert "**yes**" in text


def test_the_report_says_no_when_a_criterion_is_missed() -> None:
    text = render_report([a_shot(violations=("schema",)) for _ in range(20)])
    assert "| no |" in text


def test_an_empty_report_says_so_rather_than_claiming_zero() -> None:
    assert "No samples yet" in render_report([])


def test_the_report_names_what_the_model_got_wrong() -> None:
    text = render_report([a_shot(violations=("schema",))])
    assert "`schema`" in text
    assert "Fix the prompt, not the parser" in text


# --------------------------------------------------------------------------------- the log


def test_a_shot_round_trips_through_the_log(tmp_path: Path) -> None:
    path = tmp_path / "sections.jsonl"
    original = a_shot(violations=("schema",), cost_usd=Decimal("0.0055"))
    append_shot(path, original)
    assert load_shots(path) == [original]


def test_the_log_is_append_only(tmp_path: Path) -> None:
    """Runs accumulate into one record, as the latency rig's do."""
    path = tmp_path / "sections.jsonl"
    append_shot(path, a_shot())
    append_shot(path, a_shot(section="chorus"))
    assert [shot.section for shot in load_shots(path)] == ["verse", "chorus"]


def test_reading_a_log_that_does_not_exist_gives_nothing(tmp_path: Path) -> None:
    assert load_shots(tmp_path / "never.jsonl") == []


# ----------------------------------------------------------------------------- the rig


def test_the_briefings_cover_the_space_the_system_generates() -> None:
    """A rate measured on one comfortable verse is a fact about that verse."""
    sections = rig.briefings(30, 7)
    assert len({section.name for section in sections}) >= 3
    assert len({section.feel for section in sections}) == 4
    assert len({section.bpm for section in sections}) >= 3


def test_the_deadline_floor_takes_a_little_off_the_sample_and_not_a_lot() -> None:
    """`worth_asking` removes the hardest briefings, so the size is worth watching.

    Not pinned to 30: `MIN_DEADLINE_S` is 5.0 s from measurement, and one four-bar intro
    in thirty now falls under it and is played by the deterministic engine instead. That
    is correct — asking would buy a cancelled stream. But the same filter at a careless
    value would quietly shrink the denominator until every rate looked excellent, so the
    bound is here rather than in a comment, and `render_report` prints both numbers.
    """
    drawn = 30
    sections = rig.briefings(drawn, 7)
    assert drawn - len(sections) <= 3, (
        f"{drawn - len(sections)} of {drawn} briefings are unaskable. A rate measured "
        "over what is left is a rate with a hidden denominator."
    )


def test_every_briefing_is_worth_asking_about() -> None:
    """No section so short that the deadline makes the call pointless."""
    from garagem.agents import worth_asking

    assert all(worth_asking(section) for section in rig.briefings(30, 7))


def test_the_briefings_are_reproducible() -> None:
    assert rig.briefings(10, 7) == rig.briefings(10, 7)
    assert rig.briefings(10, 7) != rig.briefings(10, 8)


def test_the_estimate_is_pessimistic_and_says_so() -> None:
    """It assumes every call fills `max_tokens`; a real section is about 340 tokens."""
    from garagem.agents import structural
    from garagem.llm import load_catalog

    model = structural(load_catalog(ROOT / "config" / "models.toml"))
    quoted = rig.estimate_usd(model, 30)
    realistic = 30 * (
        model.price.input_usd * Decimal(700) / Decimal(1_000_000)
        + model.price.output_usd * Decimal(340) / Decimal(1_000_000)
    )
    assert quoted > realistic


def test_a_run_without_yes_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default is an estimate. Nothing reaches the network without asking."""
    monkeypatch.setattr(
        sys, "argv", ["bench_sections.py", "--runs", "3", "--out", str(tmp_path / "r.md")]
    )
    assert rig.main() == 0
    assert "nothing sent" in capsys.readouterr().err


def test_a_run_over_budget_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bench_sections.py",
            "--runs",
            "30",
            "--yes",
            "--budget-usd",
            "0.01",
            "--out",
            str(tmp_path / "r.md"),
        ],
    )
    assert rig.main() == 1
    assert "over the" in capsys.readouterr().err


def test_report_only_renders_from_the_log_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = tmp_path / "sections.jsonl"
    append_shot(log, a_shot())
    out = tmp_path / "report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        ["bench_sections.py", "--report-only", "--log", str(log), "--out", str(out)],
    )
    assert rig.main() == 0
    assert "schema conformance" in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------- flags that reach nothing


def test_every_flag_a_script_defines_is_actually_read() -> None:
    """`--arranged` parsed for two whole runs and was thrown away. $0.20 and a wrong finding.

    `bench_sections.py` defined the flag, threaded `arranged=` through `one_shot` and
    `measure`, and then called `measure(...)` without it. Both "arranged" rounds sent the
    static prompt; `phase-3-findings.md` §11 concluded that the model will not write a
    per-bar section from three prompts that were one prompt. Nothing in the output said
    so — the input token counts were byte-identical across all 26 comparable rows, which
    is what eventually gave it away.

    A flag whose `args.<dest>` is never read is a flag that does nothing. This is cheap to
    check across every script and would have caught it before the first call went out.
    """
    import ast

    for script in sorted((ROOT / "scripts").glob("*.py")):
        tree = ast.parse(script.read_text(encoding="utf-8"))
        defined: dict[str, int] = {}
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
            ):
                continue
            dest = next(
                (
                    kw.value.value
                    for kw in node.keywords
                    if kw.arg == "dest" and isinstance(kw.value, ast.Constant)
                ),
                None,
            )
            if dest is None:
                flags = [
                    a.value
                    for a in node.args
                    if isinstance(a, ast.Constant) and str(a.value).startswith("--")
                ]
                if not flags:
                    continue
                dest = str(max(flags, key=lambda flag: len(str(flag))))
                dest = dest.removeprefix("--").replace("-", "_")
            defined[str(dest)] = node.lineno

        read = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
        }
        dead = sorted((name, line) for name, line in defined.items() if name not in read)
        assert not dead, (
            f"{script.name}: {[f'--{n} (line {ln})' for n, ln in dead]} "
            "parsed but never read. A flag that reaches nothing runs the default and "
            "reports as though it ran the flag."
        )


# ------------------------------------------------------- the cost of what we never priced


def test_a_cancelled_call_is_marked_unpriced(tmp_path: Path) -> None:
    """`Usage` rides the `done` event; a cancelled stream never sends one."""
    shot = Shot(
        at=datetime(2026, 9, 1, tzinfo=UTC),
        model="claude-sonnet-5",
        section="verse",
        bars=8,
        bpm=132.0,
        deadline_s=5.82,
        ok=False,
        error="DeadlineExceededError: exceeded the 5.82s deadline",
        ttft_s=1.64,
        total_s=5.82,
        unpriced=True,
    )
    assert summarise([shot]).unpriced == 1


def test_the_report_names_calls_it_could_not_price() -> None:
    """A round of thirty once booked $0.0000 while every one of them was billed."""
    shots = [
        Shot(
            at=datetime(2026, 9, 1, tzinfo=UTC),
            model="claude-sonnet-5",
            section="verse",
            bars=8,
            bpm=132.0,
            deadline_s=5.82,
            ok=False,
            ttft_s=1.6,
            total_s=5.82,
            unpriced=True,
        )
        for _ in range(3)
    ]
    out = render_report(shots, drawn=3)
    assert "3 were billed and could not be priced" in out


def test_a_priced_run_says_nothing_about_unpriced_calls() -> None:
    """The line appears when there is a hole, and not as boilerplate."""
    shot = Shot(
        at=datetime(2026, 9, 1, tzinfo=UTC),
        model="claude-sonnet-5",
        section="verse",
        bars=8,
        bpm=132.0,
        deadline_s=5.82,
        ttft_s=1.6,
        total_s=3.4,
        cost_usd=Decimal("0.0034"),
    )
    assert "could not be priced" not in render_report([shot], drawn=1)


def test_the_report_states_what_population_the_rates_are_over() -> None:
    """Raising `MIN_DEADLINE_S` improves every rate by shrinking the denominator."""
    shot = Shot(
        at=datetime(2026, 9, 1, tzinfo=UTC),
        model="claude-sonnet-5",
        section="verse",
        bars=8,
        bpm=132.0,
        deadline_s=5.82,
        ttft_s=1.6,
        total_s=3.4,
    )
    assert "**29 of 30**" in render_report([shot] * 29, drawn=30)


def test_a_report_that_cannot_name_its_population_says_so() -> None:
    """An accumulated log spans rounds with different floors. Silence would be a claim."""
    shot = Shot(
        at=datetime(2026, 9, 1, tzinfo=UTC),
        model="claude-sonnet-5",
        section="verse",
        bars=8,
        bpm=132.0,
        deadline_s=5.82,
        ttft_s=1.6,
        total_s=3.4,
    )
    assert "was not recorded" in render_report([shot], drawn=None)
