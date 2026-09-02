"""DAW failures, classified by what the caller should do about them."""

from __future__ import annotations


class DawError(Exception):
    """Base for everything that can go wrong behind the DAW port."""


class DawUnavailableError(DawError):
    """Live is not reachable: closed, the control surface is off, or the port is taken.

    The degradation path, not a retry: the transport keeps playing whatever is already
    in the Set. Nothing below this layer waits or tries again (P7).
    """


class DawTimeoutError(DawUnavailableError):
    """Live said nothing before the deadline.

    A subclass of `DawUnavailableError` on purpose, and not of `TimeoutError`.
    AbletonOSC replies with *nothing at all* when a handler raises — there is no
    `/live/error` — so a dropped datagram, a closed Live and a malformed request are
    a single observable event down here. All three mean the same thing to the caller:
    degrade, do not retry. Distinguishing them is a job for the AbletonOSC log, which
    the message points at.
    """


class DawProtocolError(DawError):
    """A reply arrived and did not mean what the address promised.

    A truncated note list, a reply to another address, an unparseable datagram. Never
    an availability problem: Live is alive and we are wrong about the wire format.
    Failing loudly here is what keeps a short reply from being read as a short section.
    """


class DawWriteNotConfirmedError(DawError):
    """The write went out, the confirming read came back different.

    Every setter on this path is write-then-read, because OSC over UDP has no
    acknowledgement. A Set that did not take the write is a Set that will play
    something other than what was generated — worse than an outright failure.
    """


class SessionSpecError(DawError):
    """`session.toml` cannot be honoured. Fix the file, not the Set."""


class SessionDivergenceError(DawError):
    """The open Set does not match the spec, and the LOM cannot repair the difference.

    A missing track or a track with no instrument is the human's job: no LOM call
    loads an instrument, so a track created from code would be silent (ADR-013).
    `render_divergences` says what to do in Live.
    """
