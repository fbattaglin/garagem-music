"""The blind A/B's machinery, with a fake Live and nobody listening.

What these tests protect is the *blindness*. A comparison whose answer leaks before the
vote is not a comparison, and the three ways it could leak here each have a test: the
order must not be printed, the tally must not be computable mid-run, and a resumed run
must not re-ask a pair whose answer is already on disk.

The listening itself is Fabiano's, and no test can stand in for it.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path
from types import ModuleType

import pytest

from garagem.agents import worth_asking
from garagem.daw import FakeDawAdapter
from garagem.domain import Feel, Instrument, Section
from garagem.engines import play_section
from garagem.theory import parse_chart

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "ab_section.py"
    spec = importlib.util.spec_from_file_location("ab_section", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ab_section"] = module
    spec.loader.exec_module(module)
    return module


ab = _load()

SECTION = Section(
    name="verse",
    bars=8,
    key=4,
    scale="minor",
    feel=Feel.STRAIGHT8,
    bpm=132.0,
    dyn=3,
    tension=0.4,
    chart=parse_chart("| Em | C | G | D |"),
)


def a_pair(index: int = 0, first: str = "model", name: str = "verse") -> object:
    section = SECTION.model_copy(update={"name": name})
    return ab.Pair(
        index=index,
        section=section,
        model=play_section(section, 1),
        floor=play_section(section, 2),
        first=first,
        seed=1,
        model_dsl="DRM K:1,5,9,13",
    )


# ------------------------------------------------------------------------- the threshold


def test_the_threshold_is_the_one_agreed_before_any_number_existed() -> None:
    """8 of 12. ADR-000 §7 asks for ≥65%; this is 67%, fixed on 2026-08-30."""
    assert ab.THRESHOLD == 8
    assert ab.DEFAULT_PAIRS == 12
    assert ab.THRESHOLD / ab.DEFAULT_PAIRS >= 0.65


# ------------------------------------------------------------------------- the blindness


def test_the_vote_is_recorded_with_what_each_side_actually_was(tmp_path: Path) -> None:
    """Recoverable and auditable — but written only after the answer is in."""
    log = tmp_path / "ab.jsonl"
    ab.record(log, a_pair(first="model"), "A", 14.5)
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert row["first"] == "model"
    assert row["vote"] == "A"
    assert row["winner"] == "model"


def test_choosing_b_when_a_was_the_model_credits_the_floor(tmp_path: Path) -> None:
    log = tmp_path / "ab.jsonl"
    ab.record(log, a_pair(first="model"), "B", 14.5)
    assert json.loads(log.read_text(encoding="utf-8"))["winner"] == "floor"


def test_choosing_a_when_a_was_the_floor_credits_the_floor(tmp_path: Path) -> None:
    """The half of the mapping that a sloppy implementation gets backwards."""
    log = tmp_path / "ab.jsonl"
    ab.record(log, a_pair(first="floor"), "A", 14.5)
    assert json.loads(log.read_text(encoding="utf-8"))["winner"] == "floor"


def test_choosing_b_when_a_was_the_floor_credits_the_model(tmp_path: Path) -> None:
    log = tmp_path / "ab.jsonl"
    ab.record(log, a_pair(first="floor"), "B", 14.5)
    assert json.loads(log.read_text(encoding="utf-8"))["winner"] == "model"


def test_a_skip_credits_nobody(tmp_path: Path) -> None:
    log = tmp_path / "ab.jsonl"
    ab.record(log, a_pair(), "skip", 14.5)
    assert json.loads(log.read_text(encoding="utf-8"))["winner"] == "skip"


def test_the_prompt_never_names_which_side_is_which() -> None:
    """A comparison whose answer is on screen is not a comparison.

    Read out of the AST rather than out of the text, so the docstring is free to explain
    where the mapping lives while the code is held to never touching it.
    """
    import ast

    source = (ROOT / "scripts" / "ab_section.py").read_text(encoding="utf-8")
    asking = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "ask"
    )
    read = {
        node.attr
        for node in ast.walk(asking)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "pair"
    }
    assert read == {"index", "section"}


# ------------------------------------------------------------------------------ the tally


def test_the_tally_counts_the_model_and_states_the_verdict(tmp_path: Path) -> None:
    log = tmp_path / "ab.jsonl"
    for index in range(12):
        ab.record(log, a_pair(index, first="model"), "A" if index < 8 else "B", 14.5)
    text = ab.tally(log)
    assert "8 of 12" in text
    assert "MET" in text
    assert "NOT MET" not in text


def test_a_run_under_the_threshold_says_not_met(tmp_path: Path) -> None:
    """The result this phase most needs to be able to report."""
    log = tmp_path / "ab.jsonl"
    for index in range(12):
        ab.record(log, a_pair(index, first="model"), "A" if index < 5 else "B", 14.5)
    assert "NOT MET" in ab.tally(log)


def test_an_incomplete_run_is_not_met_however_it_is_going(tmp_path: Path) -> None:
    """Eight of eight is not eight of twelve, and stopping early is not a result."""
    log = tmp_path / "ab.jsonl"
    for index in range(8):
        ab.record(log, a_pair(index, first="model"), "A", 14.5)
    text = ab.tally(log)
    assert "NOT MET" in text
    assert "4 pairs still to judge" in text


def test_skipped_pairs_are_out_of_the_denominator(tmp_path: Path) -> None:
    log = tmp_path / "ab.jsonl"
    ab.record(log, a_pair(0, first="model"), "A", 14.5)
    ab.record(log, a_pair(1, first="model"), "skip", 14.5)
    assert "1 of 1" in ab.tally(log)


def test_the_tally_reveals_the_mapping_only_at_the_end(tmp_path: Path) -> None:
    log = tmp_path / "ab.jsonl"
    ab.record(log, a_pair(0, first="floor"), "B", 14.5)
    text = ab.tally(log)
    assert "A was floor" in text
    assert "now that voting is over" in text


def test_an_empty_log_has_no_result(tmp_path: Path) -> None:
    log = tmp_path / "ab.jsonl"
    log.write_text("", encoding="utf-8")
    assert "No votes" in ab.tally(log)


# ------------------------------------------------------------------------------ resuming


def test_a_resumed_run_knows_which_pairs_are_done(tmp_path: Path) -> None:
    log = tmp_path / "ab.jsonl"
    ab.record(log, a_pair(0), "A", 14.5)
    ab.record(log, a_pair(3), "B", 14.5)
    assert ab.done_pairs(log) == {0, 3}


def test_nothing_done_when_there_is_no_log(tmp_path: Path) -> None:
    assert ab.done_pairs(tmp_path / "never.jsonl") == set()


def test_a_second_run_over_an_existing_log_refuses_without_resume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two runs appending to one file would double-count the same pair."""
    log = tmp_path / "ab.jsonl"
    ab.record(log, a_pair(0), "A", 14.5)
    monkeypatch.setattr(ab, "build_adapter", lambda host, timeout_s: pytest.fail("opened Live"))
    monkeypatch.setattr(ab, "build_provider", lambda catalog: object())
    monkeypatch.setattr(sys, "argv", ["ab_section.py", "--log", str(log)])

    assert ab.main() == 1
    assert "--resume" in capsys.readouterr().err


class _NoTerminal:
    def isatty(self) -> bool:
        return False


def test_a_run_without_a_terminal_refuses_before_anything_is_generated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The vote is typed; with no stdin the first pair would be paid for and never judged."""
    monkeypatch.setattr(ab, "build_adapter", lambda host, timeout_s: pytest.fail("opened Live"))
    monkeypatch.setattr(ab, "build_provider", lambda catalog: object())
    monkeypatch.setattr(sys, "stdin", _NoTerminal())
    monkeypatch.setattr(sys, "argv", ["ab_section.py", "--log", str(tmp_path / "ab.jsonl")])

    assert ab.main() == 1
    assert "terminal" in capsys.readouterr().err


# --------------------------------------------------------------------------- the pairing


def test_the_order_is_reproducible_from_the_seed() -> None:
    """Recoverable after the fact, so a suspicious result can be audited."""
    import random

    first = [random.Random(7).choice(("model", "floor")) for _ in range(1)]
    second = [random.Random(7).choice(("model", "floor")) for _ in range(1)]
    assert first == second


def test_the_briefings_are_varied_and_reproducible() -> None:
    sections = ab.briefings(12, 7)
    assert len(sections) == 12
    assert len({str(section.feel) for section in sections}) >= 3
    assert ab.briefings(12, 7) == sections


def test_writing_a_score_reaches_every_track() -> None:
    daw = FakeDawAdapter(scenes=4)
    tracks = {
        Instrument.DRUMS: 0,
        Instrument.BASS: 1,
        Instrument.GUITAR: 2,
        Instrument.KEYS: 3,
    }
    ab.write(daw, play_section(SECTION, 7), 0, tracks)
    assert daw.calls.count("write_notes") == 4


def test_the_two_sides_go_into_different_scenes() -> None:
    """Scene 0 and scene 1, and the listener is told neither which nor why."""
    assert ab.SCENES == (0, 1)
    assert len(set(ab.SCENES)) == 2


# ------------------------------------------------------------------- one loop, not twelve


def test_the_run_holds_one_event_loop_across_every_pair() -> None:
    """`asyncio.run()` in the pair loop killed the adapter's HTTP pool on pair 2.

    The pool is persistent by design (ADR-000 §7 asks for a warm HTTP/2 one) and a pool
    belongs to the loop that created it. A fresh loop per pair closes the previous one
    under it, and the failure is `RuntimeError: Event loop is closed` — on the *second*
    call, never the first.

    Checked structurally because the real reproduction needs a real socket: `FakeProvider`
    has no pool to strand. A one-pair smoke test could not have caught this and did not.
    """
    import ast

    source = (ROOT / "scripts" / "ab_section.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
    ]
    assert not calls, "asyncio.run() in this script strands the adapter's pool; use Runner"
    assert "asyncio.Runner()" in source


def test_every_script_that_streams_more_than_once_reuses_its_loop() -> None:
    """The same hazard, checked across the scripts rather than in the one that hit it.

    A call to `asyncio.run` is fine where it wraps the *whole* run — `bench_sections.py`
    and `record_cassette.py` each make exactly one. It is a bug where it sits inside a
    loop that shares a provider, which is what this looks for.
    """
    import ast

    for script in sorted((ROOT / "scripts").glob("*.py")):
        tree = ast.parse(script.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.For | ast.While):
                continue
            inside = [
                child
                for child in ast.walk(node)
                if isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "run"
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "asyncio"
            ]
            assert not inside, (
                f"{script.name}:{node.lineno} calls asyncio.run inside a loop. "
                "A persistent HTTP pool belongs to the loop that made it — use "
                "asyncio.Runner and keep one."
            )


# ------------------------------------------------------------------- why, not just which


def test_a_reason_is_recorded_beside_the_vote(tmp_path: Path) -> None:
    """A bare vote says the floor won; only the reason says what it had."""
    log = tmp_path / "ab.jsonl"
    ab.record(log, a_pair(first="model"), "B", 14.5, "more energy")
    row = json.loads(log.read_text(encoding="utf-8"))
    assert row["winner"] == "floor"
    assert row["reason"] == "more energy"


def test_the_row_carries_enough_to_rebuild_both_sides(tmp_path: Path) -> None:
    """The defect that cost Phase 3 its calibration set, as a test.

    Twelve verdicts survived and the music they were about did not. The floor is a pure
    function of `(section, seed)` and comes back exactly; the model's DSL cannot be
    regenerated by anything, so it is kept verbatim.
    """
    log = tmp_path / "ab.jsonl"
    ab.record(log, a_pair(first="model"), "A", 14.5, "cleaner, less messy")
    row = json.loads(log.read_text(encoding="utf-8"))

    assert row["model_dsl"] == "DRM K:1,5,9,13"
    assert row["seed"] == 1
    rebuilt = Section.model_validate(row["briefing"])
    assert rebuilt == SECTION
    assert play_section(rebuilt, row["seed"]) == play_section(SECTION, 1)


def test_a_reason_is_optional() -> None:
    """Never required: a judge with no words for it must still be able to vote."""
    signature = inspect.signature(ab.record)
    assert signature.parameters["reason"].default == ""


def test_a_menu_key_becomes_its_words_and_anything_else_is_kept_verbatim() -> None:
    """`REASONS` is a shorthand, not a vocabulary the answer has to be inside."""
    assert ab.REASONS["1"] == "more energy"
    assert ab.REASONS.get("sounds thin", "sounds thin") == "sounds thin"


def test_the_menu_says_nothing_a_listener_would_have_to_look_up() -> None:
    """The judge of this test is not a musician and the criterion does not ask them to be.

    `phase-3-findings.md` §13: the reason the chorus lost took a post-hoc hypothesis and
    a pass over 85 logged sections to find. One keystroke on the night would have said it,
    but only if the words on offer are ones a listener already owns.
    """
    jargon = ("swing", "shuffle", "voicing", "syncop", "ghost", "grid", "bar", "16th", "8th")
    for text in ab.REASONS.values():
        assert not any(term in text.lower() for term in jargon), text


def test_the_tally_groups_the_reasons(tmp_path: Path) -> None:
    """One reason repeated across five losses is a diagnosis; five losses alone are not."""
    log = tmp_path / "ab.jsonl"
    for index in range(6):
        ab.record(log, a_pair(index, first="model"), "B", 14.5, "more energy")
    for index in range(6, 12):
        ab.record(log, a_pair(index, first="model"), "A", 14.5, "just sounds nicer")
    out = ab.tally(log)
    assert "why, grouped:" in out
    assert "more energy" in out and "floor won 6" in out


def test_a_log_written_before_reasons_existed_still_tallies(tmp_path: Path) -> None:
    """`bench/ab-sections.jsonl` and `ab-composed.jsonl` have no `reason` field."""
    log = tmp_path / "ab.jsonl"
    log.write_text(
        json.dumps(
            {
                "at": "2026-08-31T00:00:00Z",
                "pair": 0,
                "section": "verse",
                "bars": 8,
                "bpm": 132.0,
                "feel": "straight8",
                "first": "model",
                "vote": "A",
                "winner": "model",
                "seconds": 14.5,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert "model preferred in 1 of 1" in ab.tally(log)


# --------------------------------------------------------------- the pre-registered design


def test_all_four_feels_are_in_twelve_pairs() -> None:
    """halftime was not unlucky in two rounds — it was arithmetically unreachable.

    The old rule was `feel=list(Feel)[(index // 4) % 4]`, which over twelve pairs only
    ever reaches indices 0, 1 and 2. Two A/B rounds covered three feels of four and the
    finding "the model is weak at straight16" was a fact about the sample
    (`phase-3-findings.md` §10, §13).
    """
    sections = ab.briefings(12, 7)
    assert {section.feel for section in sections} == set(Feel)
    counts = Counter(section.feel for section in sections)
    assert set(counts.values()) == {3}, f"unbalanced: {dict(counts)}"


def test_six_of_the_twelve_pairs_are_choruses() -> None:
    """§13 found the chorus split *after* the vote, which makes it a hypothesis."""
    sections = ab.briefings(12, 7)
    assert sum(1 for section in sections if section.name == "chorus") == ab.CHORUS_PAIRS
    assert ab.CHORUS_PAIRS == 6
    assert ab.CHORUS_THRESHOLD == 4


def test_choruses_and_the_rest_alternate() -> None:
    """A run of six choruses would let the listener settle into one kind of section."""
    kinds = [section.name == "chorus" for section in ab.briefings(12, 7)]
    assert all(a != b for a, b in pairwise(kinds))


def test_tempo_is_not_a_second_name_for_feel() -> None:
    """The §4 confound, which this plan reproduced once before the table was written out.

    `bpm=TEMPOS[index % 4]` beside a feel that also cycles with period four put straight8
    and shuffle at 110/132 and straight16 and halftime at 96/150 — so "worse at
    sixteenths" and "worse when the deadline is short" would have been one column.
    """
    sections = ab.briefings(12, 7)
    by_feel: dict[Feel, set[float]] = {}
    for section in sections:
        by_feel.setdefault(section.feel, set()).add(section.bpm)
    for feel, tempos in by_feel.items():
        assert len(tempos) == 3, f"{feel} only ever appears at {sorted(tempos)}"
    assert set(Counter(section.bpm for section in sections).values()) == {3}


def test_every_pair_has_time_for_a_call() -> None:
    """A pair the producer declines is a pair judged against a floor on both sides."""
    assert all(worth_asking(section) for section in ab.briefings(12, 7))


def test_the_pre_registration_is_printed_before_any_listening() -> None:
    """Announced afterwards it is a rationalisation; announced first it is a commitment."""
    source = (ROOT / "scripts" / "ab_section.py").read_text(encoding="utf-8")
    announcement = source.index("pre-registered: chorus pairs")
    first_play = source.index("def play(")
    voting = source.index("def ask(")
    assert announcement < voting or "sys.stderr.write" in source[:announcement]
    assert first_play > 0


def test_the_tally_reports_the_chorus_split_separately(tmp_path: Path) -> None:
    log = tmp_path / "ab.jsonl"
    # Six choruses, of which the model wins five; six others, of which it wins none.
    # Overall 5 of 12 fails the criterion while the pre-registered split passes — which is
    # exactly the case the two numbers exist to tell apart.
    for index in range(12):
        chorus = index % 2 == 0
        pair = a_pair(index, first="model", name="chorus" if chorus else "verse")
        ab.record(log, pair, "A" if chorus and index < 10 else "B", 14.5)
    out = ab.tally(log)
    assert "pre-registered: chorus pairs" in out
    assert f"measured: 5 of {ab.CHORUS_PAIRS} — MET" in out
    assert "everything else: 0 of 6" in out
    assert "model preferred in 5 of 12" in out
    assert "criterion: NOT MET" in out
