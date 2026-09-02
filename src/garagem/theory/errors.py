"""Theory failures, classified by what the caller should do about them."""

from __future__ import annotations


class TheoryError(Exception):
    """Base for everything the musical knowledge layer refuses."""


class UnknownScaleError(TheoryError):
    """A scale name that is not in `SCALES`.

    Always a programming or parsing mistake, never a runtime condition: the vocabulary
    is a closed table. The message lists the known names, because the caller is usually
    a person who guessed one.
    """


class UnvoiceableError(TheoryError):
    """The chord cannot be placed inside the instrument's range.

    Raised rather than clipped. A voicing squeezed into a range it does not fit is a
    chord with the wrong notes in it, which sounds like a bug in the engine and is
    impossible to trace back to here.
    """


class ValidationFailedError(TheoryError):
    """A score that the repairer could not make legal.

    The caller falls back to the deterministic engine and logs the event — the DSL skill
    is explicit that a bar is never discarded. Carries the surviving violations so the
    log can say which rule gave up.
    """
