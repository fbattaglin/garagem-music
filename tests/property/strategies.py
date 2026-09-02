"""Strategies and settings shared by the property tests.

Not a `conftest.py`: there is no `__init__.py` under `tests/`, so a second conftest is a
second module called `conftest` and `mypy --strict` refuses the collision. A plain module
in the same directory is imported by name — pytest's default import mode puts that
directory on `sys.path` — and says what it is.

`derandomize=True` is not a preference. A property test that picks its own examples each
run fails on somebody else's machine and passes on yours, which is worse than no test:
it makes the suite look flaky and trains everyone to re-run it. Fixed examples mean a
failure here is a bug in the music, reproducible from the same command.
"""

from __future__ import annotations

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

from garagem.domain import Chart, Chord, Feel, Quality, Section
from garagem.theory.scales import DEGREES, SCALES

settings.register_profile(
    "garagem",
    max_examples=60,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("garagem")

# Only seven-note scales: a chart is stacked thirds, and a pentatonic has no fourth to
# stack on. `arrange` refuses the others outright.
HEPTATONIC = sorted(name for name, steps in SCALES.items() if len(steps) == DEGREES)

feels = st.sampled_from(Feel)

chords = st.builds(
    Chord,
    root=st.integers(min_value=0, max_value=11),
    quality=st.sampled_from(Quality),
)

charts = st.builds(
    Chart,
    chords=st.lists(chords, min_size=1, max_size=8).map(tuple),
)

# The whole legal briefing space, bar tempo: `Section` allows up to 999 BPM, and while
# the engines cope with that, generating it spends the budget on music nobody will play.
sections = st.builds(
    Section,
    name=st.sampled_from(["intro", "verse", "chorus", "bridge", "outro"]),
    bars=st.integers(min_value=1, max_value=16),
    key=st.integers(min_value=0, max_value=11),
    scale=st.sampled_from(HEPTATONIC),
    feel=st.sampled_from(Feel),
    bpm=st.floats(min_value=50.0, max_value=260.0, allow_nan=False, allow_infinity=False),
    dyn=st.integers(min_value=1, max_value=5),
    tension=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    chart=charts,
)

seeds = st.integers(min_value=0, max_value=2**31 - 1)
