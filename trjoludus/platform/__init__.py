"""Platform detection.

This package is the *only* place in TrjoLudus that is allowed to know which
operating system the engine is running on, or to talk to OS libraries. Every
other subsystem must go through the interfaces defined here.

Right now that surface is deliberately tiny: identifying the host platform.
Windowing, input and rendering backends are added in later steps.
"""

import sys
from enum import Enum

from trjoludus.errors import UnsupportedPlatformError

__all__ = ["PlatformName", "detect_platform"]


class PlatformName(Enum):
    """An operating system supported by TrjoLudus."""

    WINDOWS = "windows"
    LINUX = "linux"

    def __str__(self) -> str:
        return self.value


def detect_platform() -> PlatformName:
    """Return the :class:`PlatformName` for the host operating system.

    Raises:
        UnsupportedPlatformError: if the host is not Windows or Linux.
    """
    if sys.platform == "win32":
        return PlatformName.WINDOWS
    if sys.platform.startswith("linux"):
        return PlatformName.LINUX
    raise UnsupportedPlatformError(
        f"TrjoLudus supports Windows and Linux; got sys.platform={sys.platform!r}."
    )
