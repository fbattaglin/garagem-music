"""The stage: what a person runs to play the band (ADR-028).

The application layer. It wires the Set (`daw/`), the band (`engines/`, `transport/`), the
controllers (`control/`) and the setlist together, which nothing beneath it is allowed to do.
`scripts/` stay as thin wrappers over it.
"""

from garagem.stage.roles import (
    OPTIONAL_ROLES,
    ROLE_TO_INSTRUMENT,
    missing_roles,
    palms_of,
    pitches_of,
    tracks_of,
)

__all__ = [
    "OPTIONAL_ROLES",
    "ROLE_TO_INSTRUMENT",
    "missing_roles",
    "palms_of",
    "pitches_of",
    "tracks_of",
]
