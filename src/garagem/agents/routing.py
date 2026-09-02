"""Which model does what, and the measurements that decided it.

A table with its reasons in it, not a heuristic. ADR-000 §7 asks for "per-layer routing:
strong for structure, fast for tactics", and a routing policy whose reasons are not
written down is one nobody can revisit — so the numbers live here, next to the choice
they justify.

**Structural: `claude-sonnet-5`.** Phase 0 measured five models against the 5.8 s section
deadline, 78 samples across three times of day. It is the only one whose *worst* call
fit: 16 calls, TTFT spread 260 ms, total time p50 4.29 s and max 4.52 s — **0 of 16 over
the deadline**. `claude-opus-5` has the same median and misses by 3.08 s at worst, which
at section granularity is a cancelled stream and a fallback, not a better section.

**Tactical: `claude-haiku-4-5-20251001`.** Declared here and unused until Phase 4, so
that the tactical layer inherits this table instead of inventing a second one. Phase 0
measured it at p50 1.08 s, which is what a 1-4 bar rewrite needs; its 13.3x tail is the
reason it is not the structural choice.

**Anthropic on both layers, for now.** Not a preference: Gemini 3.1 Pro is not served on
this key's free tier (429, `limit: 0`), so the strongest Google model available for
comparison is 3.6 Flash, which came back over the deadline on **9 of 9** completed calls.
That is a billing state rather than a verdict, and experiment E2 re-runs the comparison
when it changes. `config/models.toml` keeps every measured model so the re-run costs
nothing but the calls.

Model IDs are never written in the source outside this module, and even here they are
looked up in `config/models.toml` rather than constructed — the project rule is that a
model is referenced by an explicit ID coming from configuration.
"""

from __future__ import annotations

from typing import Final

from garagem.llm import ModelSpec

STRUCTURAL: Final = "claude-sonnet-5"
TACTICAL: Final = "claude-haiku-4-5-20251001"


class UnknownModelError(LookupError):
    """A routed ID that the catalogue does not carry.

    Always a configuration mistake and never a runtime condition: the catalogue is a file
    in the repository. The message names the file, because that is where the fix goes.
    """


def structural(catalog: list[ModelSpec]) -> ModelSpec:
    """The model that writes a whole section. Strong, and inside the deadline."""
    return _find(catalog, STRUCTURAL)


def tactical(catalog: list[ModelSpec]) -> ModelSpec:
    """The model that rewrites a bar or four. Fast. Unused until Phase 4."""
    return _find(catalog, TACTICAL)


def _find(catalog: list[ModelSpec], model_id: str) -> ModelSpec:
    for spec in catalog:
        if spec.id == model_id:
            return spec
    known = ", ".join(sorted(spec.id for spec in catalog))
    raise UnknownModelError(
        f"{model_id!r} is routed but not in the catalogue; it has {known}. "
        "Model IDs live in config/models.toml — add it there, with its prices."
    )
