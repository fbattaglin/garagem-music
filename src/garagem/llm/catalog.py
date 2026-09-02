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
