"""TrjoLudus -- a lightweight 2D game engine by Trjo Development Studio.

This module is the public API of the engine. Games should import from
``trjoludus`` (and, later, its documented subpackages) and should not reach
into private modules, because everything below this surface is free to change.

    import trjoludus

    print(trjoludus.__version__)
    print(trjoludus.detect_platform())
"""

from trjoludus.app import Application, run
from trjoludus.errors import (
    PlatformError,
    TrjoLudusError,
    UnsupportedPlatformError,
)
from trjoludus.events import Event, WindowCloseRequested, WindowResized
from trjoludus.game import Game
from trjoludus.platform import PlatformName, detect_platform

__version__ = "0.0.1"

__all__ = [
    "__version__",
    # Running a game
    "Game",
    "run",
    "Application",
    # Errors
    "TrjoLudusError",
    "PlatformError",
    "UnsupportedPlatformError",
    # Events
    "Event",
    "WindowCloseRequested",
    "WindowResized",
    # Platform
    "PlatformName",
    "detect_platform",
]
