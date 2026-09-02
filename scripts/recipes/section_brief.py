"""The section-shot briefing, shared by every recording recipe.

`TOOL` and `SYSTEM` now live in `garagem.dsl.schema` — this module re-exports them so
that a recipe and the production path cannot drift apart. That was always the intent:
E2 compares model routing across providers, and the comparison is worth nothing if the
briefings differ.

`USER` stays a literal here, and deliberately. It is the probe string the four cassettes
in `cassettes/` were recorded against, and `CassetteProvider` refuses to replay against a
request whose fingerprint has moved. Production builds its message with
`garagem.dsl.brief(section)` instead; when a cassette of the *production* request is
needed, `section_fixture.py` makes one with no network at all.
"""

from __future__ import annotations

from garagem.dsl.schema import SYSTEM, TOOL

__all__ = ["SYSTEM", "TOOL", "USER"]

USER = "An 8-bar rock verse in Em at 132 BPM. Straight eights, medium tension."
