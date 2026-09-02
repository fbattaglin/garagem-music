"""Record a cassette from a recipe. Run by hand — never in CI.

A recipe is a Python file exposing `build() -> tuple[LLMProvider, Request]`. It is the
only place in the project where a real API call is intentional: the test later replays
the cassette, offline.

    uv run python scripts/record_cassette.py scripts/recipes/example_section.py \
        --out cassettes/example_section.jsonl --note "rock section, 8 bars"
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

from garagem.llm import (
    Budget,
    CircuitBreaker,
    Governor,
    GuardedProvider,
    LLMProvider,
    Request,
    load_catalog,
    prices_of,
    record,
)

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "config" / "models.toml"

# One recording, one section. Wide enough that a slow response still lands, narrow
# enough that a recipe with a loop in it stops at the price of a coffee.
BUDGET_USD = Decimal("0.25")


class Recipe(Protocol):
    def build(self) -> tuple[LLMProvider, Request]: ...


def load(path: Path) -> Recipe:
    # Put the recipe's own directory on the path so recipes can share a briefing
    # between them instead of each keeping a copy that quietly drifts.
    folder = str(path.resolve().parent)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"unreadable recipe: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "build"):
        raise SystemExit(f"{path} does not define build() -> (LLMProvider, Request)")
    return cast(Recipe, module)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    provider, request = load(args.recipe).build()
    # Even here - especially here. A recording script is exactly the "test script" the
    # project rule names: every call goes through the governor and the breaker, and a
    # model with no price in the catalogue does not get called at all.
    governor = Governor(
        Budget(
            session_usd=BUDGET_USD,
            per_minute_usd=BUDGET_USD,
            max_in_flight=1,
            prices=prices_of(load_catalog(CATALOG)),
        )
    )
    guarded = GuardedProvider(provider, governor=governor, breaker=CircuitBreaker())
    events = asyncio.run(record(guarded, request, args.out, note=args.note, name=provider.name))
    sys.stderr.write(
        f"{args.out}: {len(events)} event(s) from {provider.name} "
        f"({request.model}, fingerprint {request.fingerprint()})\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
