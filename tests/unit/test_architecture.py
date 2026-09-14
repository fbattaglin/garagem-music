"""Architecture test: the pure layers must not depend on infrastructure.

The analysis is static (via `ast`), not import-based: it executes no module, works
with still-empty packages, and also sees imports hidden inside functions — which a
runtime `import` check would let through.

Two rules are checked, both from `.claude/rules/domain-purity.md`:

1. **Direction.** `domain/`, `theory/` and `engines/` never import `llm/`, `daw/`,
   `transport/` or `obs/`. They receive what they need as arguments.
2. **I/O purity.** Those same layers open no socket, read no file, consult no
   environment variable and never touch the global RNG. This is what makes them the part
   of the system that runs in CI with no network, no Ableton and no API key — and what
   makes invariant 7 checkable at all, because a module that can read the clock is a
   module whose output is not a function of its seed.

There is no exception list, and adding one would be how the rule dies. If this test flags
a module, fix the module.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = "garagem"
ROOT = Path(__file__).resolve().parents[2] / "src" / PACKAGE

INFRASTRUCTURE = frozenset({"llm", "daw", "transport", "obs", "control"})

# layer -> layers it must not import
FORBIDDEN: dict[str, frozenset[str]] = {
    "domain": INFRASTRUCTURE,
    "theory": INFRASTRUCTURE,
    # `domain-purity.md` has always covered engines/; until Phase 2 the test did not.
    "engines": INFRASTRUCTURE,
    # ADR-016, added in Phase 3. `transport/` legitimately talks to `daw/` and `obs/` —
    # it is the layer that drives Live — but it may never reach the network. A model call
    # takes seconds; the bar loop has milliseconds. The producer owns that call, on its
    # own thread, and the two meet at the `ScoreBuffer` (invariant 1).
    "transport": frozenset({"llm", "control"}),
    # ADR-022: a controller hears a person and hands over a `Control`; it knows nothing of
    # Live, the model, the scheduler or the log. `transport/` never imports it either —
    # the two meet at the `CueQueue`, wired by `scripts/jam.py` (invariant 1).
    "control": frozenset({"llm", "daw", "transport", "obs"}),
    # ADR-024: a setlist is music written ahead of time, not the way it is fetched or played.
    # The bake script brings the model and `jam.py` brings Live; the format knows neither.
    "setlist": frozenset({"llm", "daw", "transport", "control", "obs"}),
}

# The layers `domain-purity.md` governs: no I/O of any kind, and no unseeded randomness.
# `transport/` is deliberately not among them — it opens a socket for a living.
PURE_LAYERS: tuple[str, ...] = ("domain", "theory", "engines")

# What `realtime.md` forbids on the musical path, as import names. Narrower than
# `IMPURE_MODULES` on purpose: `transport/` may read a clock and touch a thread, and the
# rule it is under is about *waiting*, not about purity.
NETWORK_MODULES: frozenset[str] = frozenset(
    {"asyncio", "http", "httpx", "requests", "urllib", "socket"}
)

# Modules the pure layers may not import at all, whatever the layer they sit in.
IMPURE_MODULES: frozenset[str] = frozenset(
    {
        "asyncio",
        "http",
        "httpx",
        "mido",
        "os",
        "pathlib",
        "pythonosc",
        "requests",
        "socket",
        "subprocess",
        "tomllib",
        "urllib",
    }
)

# Names that reach the outside world without an import statement to point at.
IMPURE_CALLS: frozenset[str] = frozenset({"open", "input", "print", "eval", "exec"})

# The global RNG. `Random` received as a parameter is the rule; `random.random()` and its
# siblings are a hidden second generator, and invariant 7 dies quietly the moment one
# appears.
IMPURE_ATTRIBUTES: frozenset[str] = frozenset(
    {"random.random", "random.randint", "random.choice", "random.shuffle", "random.uniform"}
)


def _module(file: Path) -> str:
    """Dotted module name, e.g. `garagem.domain.chart`."""
    parts = (PACKAGE, *file.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_of(file: Path) -> str:
    """The package containing the module, the base for resolving relative imports."""
    module = _module(file)
    if file.name == "__init__.py":
        return module
    return module.rpartition(".")[0]


def _resolve_relative(package: str, level: int, module: str | None) -> str:
    parts = package.split(".")
    base = parts[: len(parts) - (level - 1)] if level > 1 else parts
    return ".".join([*base, module] if module else base)


def _targets_in_source(source: str, package: str, name: str = "<memory>") -> list[tuple[int, str]]:
    """Every module the source imports, as (line, dotted name)."""
    tree = ast.parse(source, filename=name)
    found: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            origin = (
                node.module or ""
                if node.level == 0
                else _resolve_relative(package, node.level, node.module)
            )
            found.append((node.lineno, origin))
            # `from garagem import llm` — the real target is the imported name.
            found += [(node.lineno, f"{origin}.{alias.name}") for alias in node.names]

    return found


def _targets(file: Path) -> list[tuple[int, str]]:
    return _targets_in_source(
        file.read_text(encoding="utf-8"),
        _package_of(file),
        str(file),
    )


def _files(layer: str) -> list[Path]:
    return sorted((ROOT / layer).rglob("*.py"))


def _violates(target: str, forbidden: frozenset[str]) -> bool:
    return any(
        target == f"{PACKAGE}.{layer}" or target.startswith(f"{PACKAGE}.{layer}.")
        for layer in forbidden
    )


def test_pure_layers_do_not_import_infrastructure() -> None:
    violations: list[str] = []

    for layer, forbidden in FORBIDDEN.items():
        for file in _files(layer):
            for line, target in _targets(file):
                if _violates(target, forbidden):
                    where = f"{file.relative_to(ROOT.parents[1])}:{line}"
                    violations.append(f"  {where} -> imports {target}")

    assert not violations, (
        "Pure layers depending on infrastructure:\n"
        + "\n".join(violations)
        + "\n\ndomain/ and theory/ receive what they need as arguments; they do not fetch it."
    )


def _impure_uses_in_source(source: str, name: str = "<memory>") -> list[tuple[int, str]]:
    """Every I/O or global-randomness escape hatch the source reaches for."""
    tree = ast.parse(source, filename=name)
    found: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [
                (node.lineno, alias.name)
                for alias in node.names
                if alias.name.split(".")[0] in IMPURE_MODULES
            ]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            root = (node.module or "").split(".")[0]
            if root in IMPURE_MODULES:
                found.append((node.lineno, node.module or ""))
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in IMPURE_CALLS:
                found.append((node.lineno, f"{node.func.id}()"))
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                dotted = f"{node.func.value.id}.{node.func.attr}"
                if dotted in IMPURE_ATTRIBUTES:
                    found.append((node.lineno, f"{dotted}()"))

    return found


def test_pure_layers_do_no_io_and_use_no_global_randomness() -> None:
    violations: list[str] = []

    for layer in PURE_LAYERS:
        for file in _files(layer):
            for line, use in _impure_uses_in_source(file.read_text(encoding="utf-8"), str(file)):
                where = f"{file.relative_to(ROOT.parents[1])}:{line}"
                violations.append(f"  {where} -> {use}")

    assert not violations, (
        "Pure layers reaching outside themselves:\n"
        + "\n".join(violations)
        + "\n\nIf a value comes from outside — the time, a file, a seed — receive it as an "
        "argument. Do not go and fetch it, and do not add an exception here."
    )


def test_the_transport_never_reaches_the_network() -> None:
    """ADR-016, made mechanical rather than remembered.

    `realtime.md` forbids network calls and `await` on I/O here. A rule kept by
    discipline is kept until the first inconvenient afternoon; this one is checked.
    """
    violations: list[str] = []

    for file in _files("transport"):
        for line, use in _impure_uses_in_source(file.read_text(encoding="utf-8"), str(file)):
            if use.split(".")[0] in NETWORK_MODULES:
                violations.append(f"  {file.relative_to(ROOT.parents[1])}:{line} -> {use}")

    assert not violations, (
        "The musical path reaching the network:\n"
        + "\n".join(violations)
        + "\n\nThe producer owns the call (ADR-016). The scheduler reads a ScoreBuffer."
    )


def test_the_producer_is_where_the_network_is_allowed_to_live() -> None:
    """The other half of the same claim: `agents/` may do what `transport/` may not.

    Without this, the rule above would be satisfied by a system that makes no model call
    anywhere — which is Phase 2, and is not what Phase 3 is for.
    """
    assert "agents" not in FORBIDDEN
    assert "agents" not in PURE_LAYERS


IMPURE_SOURCE = """
import os
import socket
from pathlib import Path
import random


def generate(seed):
    rng = random.Random(seed)          # legitimate: a Random of our own
    noise = random.random()            # not legitimate: the global generator
    text = open("notes.txt").read()
    return rng, noise, text, os, socket, Path
"""


def test_the_purity_detector_tells_a_seeded_random_from_the_global_one() -> None:
    """`random.Random(seed)` is the rule; `random.random()` is the thing being banned."""
    flagged = {use for _, use in _impure_uses_in_source(IMPURE_SOURCE)}
    assert flagged == {"os", "socket", "pathlib", "random.random()", "open()"}


GUILTY_SOURCE = """
import garagem.llm.governor
from garagem.daw import DawPort
from garagem import obs
from garagem.transport.clock import BarClock


def generate():
    from garagem.obs.eventlog import log  # import hidden inside a function

    return log


from .fake_adapter import Fake  # relative, resolved against garagem.domain
"""


def test_the_detector_catches_every_import_form() -> None:
    """If the scanner breaks, the main test passes in silence. This one catches that."""
    targets = _targets_in_source(GUILTY_SOURCE, package=f"{PACKAGE}.domain")
    flagged = {target for _, target in targets if _violates(target, INFRASTRUCTURE)}

    assert flagged == {
        "garagem.llm.governor",
        "garagem.daw",
        "garagem.daw.DawPort",
        "garagem.obs",
        "garagem.obs.eventlog",
        "garagem.obs.eventlog.log",
        "garagem.transport.clock",
        "garagem.transport.clock.BarClock",
    }
    # The relative import resolved inside domain/ — legitimate, so not flagged.
    assert any(target == "garagem.domain.fake_adapter" for _, target in targets)


def test_the_scanner_actually_finds_files() -> None:
    """Guards against the test above passing vacuously if the layout changes."""
    empty = [layer for layer in (*FORBIDDEN, *PURE_LAYERS) if not _files(layer)]
    assert not empty, f"No .py found in {empty} — did the layout change under the test?"
