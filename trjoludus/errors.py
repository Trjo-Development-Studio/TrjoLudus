"""Exception hierarchy for TrjoLudus.

Every error raised by the engine derives from :class:`TrjoLudusError`, so a
game can always catch engine failures with a single ``except`` clause.
"""

__all__ = [
    "TrjoLudusError",
    "PlatformError",
    "UnsupportedPlatformError",
]


class TrjoLudusError(Exception):
    """Base class for all errors raised by TrjoLudus."""


class PlatformError(TrjoLudusError):
    """Raised when the underlying operating system layer fails."""


class UnsupportedPlatformError(PlatformError):
    """Raised when TrjoLudus is run on an operating system it does not support."""
