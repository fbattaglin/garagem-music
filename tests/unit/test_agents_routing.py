"""Which model does what, checked against the catalogue that actually exists.

The test that earns its place is the last one: every ID this module routes to must be in
`config/models.toml`. A rename there would otherwise be found at the first live call,
which is the most expensive place to find it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from garagem.agents import (
    STRUCTURAL,
    TACTICAL,
    UnknownModelError,
    structural,
    tactical,
)
from garagem.agents.routing import _find
from garagem.llm import Effort, load_catalog

ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_catalog(ROOT / "config" / "models.toml")


def test_the_structural_model_is_the_one_measured_to_fit_the_deadline() -> None:
    """Phase 0: 0 of 16 calls over 5.8 s. The only model that managed it."""
    assert structural(CATALOG).id == "claude-sonnet-5"


def test_the_structural_model_thinks_hard() -> None:
    """§4.2's trade: effort buys quality and costs TTFT, and structure is worth it."""
    assert structural(CATALOG).effort is Effort.HIGH


def test_the_tactical_model_is_declared_so_phase_four_inherits_this_table() -> None:
    assert tactical(CATALOG).id == TACTICAL
    assert tactical(CATALOG).effort is None


def test_the_two_layers_are_different_models() -> None:
    """Strong for structure, fast for tactics (ADR-000 §7). One model would be neither."""
    assert structural(CATALOG) != tactical(CATALOG)


def test_an_id_that_is_not_in_the_catalogue_names_the_file_to_fix() -> None:
    with pytest.raises(UnknownModelError, match=re.escape("config/models.toml")):
        _find(CATALOG, "claude-imaginary-9")


def test_the_error_lists_what_the_catalogue_does_have() -> None:
    with pytest.raises(UnknownModelError, match="claude-sonnet-5"):
        _find(CATALOG, "nope")


def test_every_routed_id_exists_in_the_catalogue() -> None:
    """A rename in `config/models.toml` is caught here, not at the first live call."""
    available = {spec.id for spec in CATALOG}
    assert {STRUCTURAL, TACTICAL} <= available


def test_the_catalogue_still_carries_the_models_experiment_e2_compares() -> None:
    """E2 re-runs the routing comparison when Gemini billing is enabled."""
    available = {spec.id for spec in CATALOG}
    assert "claude-opus-5" in available
    assert any(spec.provider == "google" for spec in CATALOG)
