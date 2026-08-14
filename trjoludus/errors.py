"""Exception hierarchy for TrjoLudus.

Every error raised by the engine derives from :class:`TrjoLudusError`, so a
game can always catch engine failures with a single ``except`` clause.
"""

__all__ = [
    "TrjoLudusError",
    "TrjoLudusWarning",
    "PlatformError",
    "UnsupportedPlatformError",
]


class TrjoLudusError(Exception):
    """Base class for all errors raised by TrjoLudus."""


class TrjoLudusWarning(UserWarning):
    """Warned when a game asks for something that cannot be done as asked.

    Not an error: the game keeps running, and the engine does the most
    reasonable thing it can. It exists so that "this did nothing" and "this
    did something other than what you wrote" are audible instead of silent --
    playing an animation that is already playing, or stopping one that is not.

    Warnings are raised once rather than every frame, because the calls that
    cause them are usually in ``on_update``.
    """


class PlatformError(TrjoLudusError):
    """Raised when the underlying operating system layer fails."""


class UnsupportedPlatformError(PlatformError):
    """Raised when TrjoLudus is run on an operating system it does not support."""
