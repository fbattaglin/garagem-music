"""The model catalogue - the one place a model ID or a price is written down."""

from __future__ import annotations

from pathlib import Path

import pytest

from garagem.llm import Effort, load_catalog, prices_of

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "config" / "models.toml"


def test_the_shipped_catalogue_loads_and_every_model_is_priced() -> None:
    specs = load_catalog(CATALOG)
    assert specs, "config/models.toml declares no model"
    assert {s.provider for s in specs} == {"anthropic", "google"}
    for spec in specs:
        assert spec.price.input_usd > 0
        assert spec.price.output_usd > 0
        assert spec.max_tokens > 0


def test_every_model_the_governor_could_be_asked_about_has_a_price() -> None:
    """An unpriced model is refused outright, so the catalogue is the governor's map."""
    specs = load_catalog(CATALOG)
    assert set(prices_of(specs)) == {s.id for s in specs}


def test_effort_none_means_the_model_has_no_such_knob(tmp_path: Path) -> None:
    path = tmp_path / "models.toml"
    path.write_text(
        """
[[model]]
provider = "anthropic"
id = "claude-haiku-4-5-20251001"
effort = "none"
input_usd = 1.0
cache_read_usd = 0.1
output_usd = 5.0

[[model]]
provider = "anthropic"
id = "claude-opus-5"
effort = "high"
input_usd = 5.0
cache_read_usd = 0.5
output_usd = 25.0
""",
        encoding="utf-8",
    )
    haiku, opus = load_catalog(path)
    assert haiku.effort is None
    assert opus.effort is Effort.HIGH


def test_a_catalogue_with_no_models_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "models.toml"
    empty.write_text("# nothing here\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"no \[\[model\]\]"):
        load_catalog(empty)
