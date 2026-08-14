"""TrjoLudus -- a lightweight 2D game engine by Trjo Development Studio.

This module is the public API of the engine. Games should import from
``trjoludus`` and should not reach into private modules, because everything
below this surface is free to change.

Import the names a game uses and then use them directly::

    from trjoludus import Game, GameObject, create, input, key, keyboard, run

    class MyGame(Game):
        def on_start(self):
            create.image(100, 100, "player.png", "player")
            self.player = GameObject("player")

        def on_update(self, dt):
            keyboard.wait(input.key)
            if key == "W":
                self.player.move.y(-50)

    run(MyGame())

``import trjoludus`` on its own binds only the name ``trjoludus``; that is what
an import statement does, so naming the pieces is how they reach a file. Every
name in :data:`__all__` is meant to be imported this way.
"""

from trjoludus import color, create, draw, input, keyboard, mouse, time
from trjoludus.app import Application, run
from trjoludus.errors import (
    PlatformError,
    TrjoLudusError,
    TrjoLudusWarning,
    UnsupportedPlatformError,
)
from trjoludus.events import (
    Event,
    KeyPressed,
    KeyReleased,
    MouseButtonPressed,
    MouseButtonReleased,
    MouseMoved,
    WindowCloseRequested,
    WindowResized,
)
from trjoludus.game import Game
from trjoludus.keyboard import key
from trjoludus.animation import AnimationError
from trjoludus.image import ImageError
from trjoludus.platform import PlatformName, detect_platform
from trjoludus.scene import GameObject, SceneError
from trjoludus.ui import UiError

__version__ = "0.0.1"

__all__ = [
    "__version__",
    # Running a game
    "Game",
    "run",
    "Application",
    # Game objects
    "create",
    "GameObject",
    # User interface
    "draw",
    "color",
    # Input
    "keyboard",
    "mouse",
    "input",
    "key",
    # Time
    "time",
    # Errors
    "TrjoLudusError",
    "TrjoLudusWarning",
    "PlatformError",
    "UnsupportedPlatformError",
    "ImageError",
    "AnimationError",
    "SceneError",
    "UiError",
    # Events
    "Event",
    "KeyPressed",
    "KeyReleased",
    "MouseMoved",
    "MouseButtonPressed",
    "MouseButtonReleased",
    "WindowCloseRequested",
    "WindowResized",
    # Platform
    "PlatformName",
    "detect_platform",
]
