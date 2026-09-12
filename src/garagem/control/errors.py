"""What can go wrong between a person's hands and the scheduler."""

from __future__ import annotations


class ControlError(Exception):
    """Base for everything the controller layer raises."""


class ControllerSpecError(ControlError):
    """`controller.toml` says something that cannot be played. The message names the entry."""


class ControllerUnavailableError(ControlError):
    """The controller is not there. The message lists what is, so the fix is one read away."""
