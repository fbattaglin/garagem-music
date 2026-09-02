"""What we ask a model for, and the split that makes prompt caching real.

The test that matters most is the one about the cache prefix: `SYSTEM` must be
byte-identical across two different sections. A prompt cache either matches its prefix
exactly or does not exist, so a single per-section word leaking into the stable block
does not degrade the hit rate — it zeroes it, silently, and the only symptom is a bill.
"""

from __future__ import annotations

import pytest

from garagem.domain import Feel, Section
from garagem.dsl import SYSTEM, SYSTEM_ARRANGED, TOOL, brief, system_for
from garagem.dsl.schema import SYSTEM_POSITIONS
from garagem.theory import parse_chart


def a_section(**extra: object) -> Section:
    base: dict[str, object] = {
        "name": "verse",
        "bars": 8,
        "key": 4,
        "scale": "minor",
        "feel": Feel.STRAIGHT8,
        "bpm": 132.0,
        "dyn": 3,
        "tension": 0.4,
        "chart": parse_chart("| Em | C | G | D |"),
    }
    return Section.model_validate(base | extra)


# ---------------------------------------------------------------------------------- tool


def test_the_tool_requires_the_dsl_and_forbids_anything_else() -> None:
    """ADR-009: the model answers through the schema or not at all."""
    schema = TOOL.input_schema
    assert schema["required"] == ["dsl"]
    assert schema["additionalProperties"] is False
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == {"dsl"}


def test_the_tool_is_named_for_what_it_does() -> None:
    assert TOOL.name == "write_section"


# -------------------------------------------------------------------------------- system


def test_the_stable_block_states_the_mandated_order() -> None:
    assert "SEC, CHD, DRM, BAS, GTR, KEY" in SYSTEM


def test_the_stable_block_shows_a_grid_of_exactly_sixteen() -> None:
    """The example is the specification the model actually reads."""
    grids = [
        field.split(":", 1)[1]
        for line in SYSTEM.splitlines()
        for field in line.split()
        if ":" in field and set(field.split(":", 1)[1]) <= set("x.") and field.split(":", 1)[1]
    ]
    assert grids
    assert all(len(grid) == 16 for grid in grids)


def test_the_stable_block_carries_nothing_about_a_particular_section() -> None:
    """It is the cache prefix. Anything per-section in here zeroes the hit rate."""
    first = brief(a_section())
    second = brief(a_section(name="chorus", bars=4, tension=0.9, dyn=5))
    assert first != second
    # The block is a constant; asserting it here is asserting that nothing interpolates.
    assert SYSTEM is SYSTEM
    assert "chorus" not in SYSTEM


# --------------------------------------------------------------------------------- brief


def test_the_brief_states_every_constraint_the_model_will_be_held_to() -> None:
    """A field we did not state is a field we cannot fairly refuse."""
    text = brief(a_section())
    for field in ("bars=8", "key=Em", "feel=straight8", "bpm=132", "dyn=3", "tension=0.4"):
        assert field in text


def test_the_brief_renders_the_chart_the_way_the_parser_reads_it() -> None:
    assert "CHD | Em | C | G | D |" in brief(a_section())


def test_a_major_key_has_no_trailing_m() -> None:
    assert "key=C " in brief(a_section(key=0, scale="major"))


@pytest.mark.parametrize("scale", ["minor", "dorian", "blues"])
def test_a_minor_flavoured_scale_gets_the_m(scale: str) -> None:
    """`key=` carries a modality, not a mode — which is why the scale stays ours."""
    assert "key=Em" in brief(a_section(scale=scale))


def test_the_same_section_gives_the_same_brief_byte_for_byte() -> None:
    """The request fingerprint is a hash of the whole thing; instability breaks replay."""
    assert brief(a_section()) == brief(a_section())


# -------------------------------------------------------------------------------- recipes


def test_the_recording_recipe_uses_these_and_does_not_copy_them() -> None:
    """A copy in `scripts/` is exactly the drift that makes experiment E2 worthless."""
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "recipes" / "section_brief.py"
    spec = importlib.util.spec_from_file_location("section_brief", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["section_brief"] = module
    spec.loader.exec_module(module)

    assert module.TOOL is TOOL
    assert module.SYSTEM is SYSTEM


# ------------------------------------------------------------------- the arranged variant


def test_the_arranged_block_asks_for_one_line_per_bar() -> None:
    """What the blind A/B found missing: every generated section was a static loop."""
    assert "one bar-level line per bar, per instrument" in SYSTEM_ARRANGED
    assert "not a loop: the bars differ" in SYSTEM_ARRANGED
    assert "fill in the last bar" in SYSTEM_ARRANGED


def test_the_arranged_example_is_itself_arranged() -> None:
    """An instruction that contradicts the example beside it loses to the example.

    The first version put "one line per bar" in prose and showed one line per instrument.
    The model followed the example: 0 of 28 sections came back with more than one DRM
    line. The example is now a whole two-bar section, arranged.
    """
    drums = [line for line in SYSTEM_ARRANGED.splitlines() if line.strip().startswith("DRM")]
    assert len(drums) == 2
    assert drums[0] != drums[1]
    assert "C:" in drums[0]  # a crash on bar 1
    assert "C:" not in drums[1]

    static = [line for line in SYSTEM.splitlines() if line.strip().startswith("DRM")]
    assert len(static) == 1


def test_the_arranged_block_shows_the_crash_voice() -> None:
    """`C:` has been in the parser all along and no model has ever written one: 0 of 28.

    It was never in an example. A field the DSL has and the prompt never mentions is a
    field that does not exist as far as the model is concerned — the same class of defect
    as `voi=min`.
    """
    assert "C:x..............." in SYSTEM_ARRANGED
    assert "C:" not in SYSTEM


def test_the_two_blocks_are_separate_strings_and_not_built_from_pieces() -> None:
    """Each is a cache prefix. A prefix assembled at call time is not a prefix."""
    assert system_for() is SYSTEM
    assert system_for(arranged=True) is SYSTEM_ARRANGED


def test_the_arranged_brief_asks_for_the_section_length() -> None:
    text = brief(a_section(bars=8), arranged=True)
    assert "8 bars each" in text
    assert "arranged" in text


def test_the_static_brief_is_unchanged() -> None:
    """Off by default: the measured baseline has to stay reachable to compare against."""
    assert "bars each" not in brief(a_section())


def test_both_briefs_state_every_constraint() -> None:
    for text in (brief(a_section()), brief(a_section(), arranged=True)):
        for field in ("bars=8", "key=Em", "feel=straight8", "bpm=132", "dyn=3", "tension=0.4"):
            assert field in text


def test_the_positions_block_actually_differs_from_the_static_one() -> None:
    """`SYSTEM_POSITIONS` is built by `str.replace`, and a replace that misses is a no-op.

    That failure mode has already cost this project two rounds of measurement: `--arranged`
    was parsed and thrown away and §11 concluded something from three runs of one prompt.
    A silent no-op here would send the static block under a flag named `--positions` and
    the result would look like an answer.
    """
    assert SYSTEM_POSITIONS != SYSTEM
    assert "1,4,7,11,14" in SYSTEM_POSITIONS
    assert "x..x..x...x..x.." not in SYSTEM_POSITIONS
    assert "16 characters" not in SYSTEM_POSITIONS


def test_every_bar_line_in_the_positions_block_parses() -> None:
    """An example the parser rejects is a prompt teaching output we refuse."""
    from garagem.dsl.lines import parse_bar_line

    examples = [
        line.strip()
        for line in SYSTEM_POSITIONS.splitlines()
        if line.strip().startswith(("DRM ", "BAS ", "GTR ", "KEY "))
    ]
    assert len(examples) == 4
    for example in examples:
        parse_bar_line(example)


def test_every_bar_line_in_the_static_block_parses() -> None:
    """The same guard on the block that has been in production all phase."""
    from garagem.dsl.lines import parse_bar_line

    examples = [
        line.strip()
        for line in SYSTEM.splitlines()
        if line.strip().startswith(("DRM ", "BAS ", "GTR ", "KEY "))
    ]
    assert len(examples) == 4
    for example in examples:
        parse_bar_line(example)
