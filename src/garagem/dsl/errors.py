"""DSL failures, classified by what the caller should do about them."""

from __future__ import annotations


class DslError(Exception):
    """Base for everything the DSL layer refuses."""


class StreamProtocolError(DslError):
    """The tool input is not the object the schema promised.

    A wrong key, an impossible escape, a second field. Never a musical problem: the model
    answered through a tool whose schema we wrote, and what came back does not fit it.
    Raised rather than counted, because there is no partial section to salvage — unlike a
    bad *line*, which is a `Violation` and leaves the rest of the section standing.
    """


class LineError(DslError):
    """One line of DSL that could not be read.

    Carries the line so the message can show it. The caller turns this into a
    `Violation`: the exit criterion counts these, so they must be countable rather than
    fatal, and a section with one bad line is still worth most of its notes.
    """
