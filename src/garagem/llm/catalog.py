"""The model catalogue: which models exist, what they cost, how they are addressed.

`.claude/rules/llm-calls.md`: "Models are referenced by explicit ID coming from
configuration, never by an alias such as 'the fast model' hard-coded in the source."
This is that configuration, and it is deliberately the *only* place a model ID or a
price appears. The governor needs prices, the latency rig needs the list, and the
cassette recorder needs both - three consumers, one file, no drift.

Prices are USD per million tokens, from section 4.4 of ADR-000.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from garagem.llm.governor import Budget, ModelPrice
from garagem.llm.port import Effort


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: str
    id: str
    # None for a model with no effort knob at all - see `Effort` in the port. Haiku 4.5
    # rejects the parameter with a 400 rather than ignoring it.
    effort: Effort | None
    max_tokens: int
    price: ModelPrice
    # False for a model that rejects a forced `tool_choice` with a 400. The tool is then
    # offered rather than forced, and the prompt is what names it.
    forced_tool: bool = True
    # A job the configuration gives this model, such as "composer". The live layers are
    # routed by measured ID in `agents/routing.py` and carry none.
    role: str | None = None


def _effort(name: str) -> Effort | None:
    """`effort = "none"` in the configuration means the model has no such parameter."""
    return None if name == "none" else Effort(name)


def load_catalog(path: Path) -> list[ModelSpec]:
    raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    specs = [
        ModelSpec(
            provider=entry["provider"],
            id=entry["id"],
            effort=_effort(entry.get("effort", "high")),
            max_tokens=int(entry.get("max_tokens", 2048)),
            price=ModelPrice(
                input_usd=Decimal(str(entry["input_usd"])),
                output_usd=Decimal(str(entry["output_usd"])),
                cache_read_usd=Decimal(str(entry["cache_read_usd"])),
            ),
            forced_tool=bool(entry.get("forced_tool", True)),
            role=entry.get("role"),
        )
        for entry in raw.get("model", [])
    ]
    if not specs:
        raise ValueError(f"{path} declares no [[model]]")
    return specs


def prices_of(specs: list[ModelSpec]) -> dict[str, ModelPrice]:
    return {spec.id: spec.price for spec in specs}


@dataclass(frozen=True, slots=True)
class SessionBudget:
    """What one performance may spend, read from `config/budget.toml`.

    The caps are the fuse; `target_usd` is what an ordinary session is expected to cost.
    Phase 4's exit criterion is measured against the target, and the fuse is what stops a
    runaway loop before the target stops mattering.
    """

    session_usd: Decimal
    per_minute_usd: Decimal
    max_in_flight: int
    target_usd: Decimal

    def fuse(self, prices: dict[str, ModelPrice]) -> Budget:
        return Budget(
            session_usd=self.session_usd,
            per_minute_usd=self.per_minute_usd,
            max_in_flight=self.max_in_flight,
            prices=prices,
        )


def load_budget(path: Path) -> SessionBudget:
    raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    session = raw.get("session")
    if not session:
        raise ValueError(f"{path} declares no [session]")
    return SessionBudget(
        session_usd=Decimal(str(session["session_usd"])),
        per_minute_usd=Decimal(str(session["per_minute_usd"])),
        max_in_flight=int(session.get("max_in_flight", 3)),
        target_usd=Decimal(str(session["target_usd"])),
    )


def load_studio_cap(path: Path) -> Decimal:
    """What one sitting in the studio may spend on the songwriter (ADR-030).

    Its own figure, beside the performance's and never shared with it: preparing a concert
    must not spend the evening's gig, which is the reason the bake had its own cap too.
    """
    raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    studio = raw.get("studio")
    if not studio or "session_usd" not in studio:
        raise ValueError(f"{path} declares no [studio] session_usd")
    cap = Decimal(str(studio["session_usd"]))
    if cap <= 0:
        raise ValueError(f"{path}: [studio] session_usd must be more than nothing")
    return cap
