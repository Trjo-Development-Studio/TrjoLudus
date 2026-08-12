"""The application and the engine-owned game loop.

:class:`Application` wires a :class:`~trjoludus.game.Game` to a platform
backend: it creates the window, runs the loop, dispatches events, drives the
:class:`~trjoludus.clock.Clock` and guarantees cleanup. Games reach it through
:func:`run`.

This module is platform-neutral. It knows about the backend *contracts* in
``trjoludus.platform.base``, never about X11, Win32 or Wayland.

**Loop order.** Each frame runs::

    poll events -> dispatch to on_event -> clock.tick() -> on_update(dt)

The pacing sleep therefore sits between dispatch and update. The alternative
-- ticking first, so events are sampled as late as possible -- would shave up
to one frame of latency off the gap between an event arriving and the update
that reacts to it. That difference is not observable until there is a renderer,
and this order matches the lifecycle documented in ARCHITECTURE.md, so it is
what the engine does for now.

**Backend.** The backend is chosen by
:func:`trjoludus.platform.create_backend` when :meth:`Application.run` starts,
so constructing an application never opens a display. On Linux that means a
real X11 window; setting ``TRJOLUDUS_BACKEND=null`` runs headless instead.
"""

from trjoludus.clock import DEFAULT_MAX_FPS, Clock
from trjoludus.game import Game
from trjoludus.platform import create_backend
from trjoludus.platform.base import PlatformBackend

__all__ = ["Application", "run"]

#: Title used when a game does not ask for one.
DEFAULT_TITLE = "TrjoLudus"

#: Client-area size, in pixels, used when a game does not ask for one.
DEFAULT_SIZE = (1280, 720)


def _validate_title(title: str) -> str:
    if not isinstance(title, str):
        raise TypeError(f"title must be a string, got {type(title).__name__}")
    return title


def _validate_size(size: tuple[int, int]) -> tuple[int, int]:
    try:
        width, height = size
    except (TypeError, ValueError):
        raise ValueError(
            f"size must be a (width, height) pair, got {size!r}"
        ) from None
    for name, value in (("width", width), ("height", height)):
        if not isinstance(value, int):
            raise TypeError(f"{name} must be an int, got {type(value).__name__}")
        if value <= 0:
            raise ValueError(f"{name} must be positive, got {value}")
    return (width, height)


class Application:
    """Owns the window, the loop and the clock for one :class:`Game`.

    Args:
        game: The game to run.
        title: Window title.
        size: ``(width, height)`` of the client area, in pixels.
        max_fps: Target frame rate, or ``None`` to run unpaced. Passed
            straight to :class:`~trjoludus.clock.Clock`, which validates it.
        backend: Backend to run on. Defaults to whatever
            :func:`~trjoludus.platform.create_backend` selects when
            :meth:`run` starts. Supplying one explicitly is how tests pin the
            backend, and it overrides both the platform default and
            ``TRJOLUDUS_BACKEND``.

    Raises:
        TypeError: If ``title``, ``width`` or ``height`` has the wrong type.
        ValueError: If ``size`` is not a pair, if either dimension is not
            positive, or if ``max_fps`` is not positive.
    """

    def __init__(
        self,
        game: Game,
        *,
        title: str = DEFAULT_TITLE,
        size: tuple[int, int] = DEFAULT_SIZE,
        max_fps: float | None = DEFAULT_MAX_FPS,
        backend: PlatformBackend | None = None,
    ) -> None:
        self._game = game
        self._title = _validate_title(title)
        self._size = _validate_size(size)
        self._clock = Clock(max_fps=max_fps)
        # Deliberately not selected here: constructing an Application must not
        # open a display, so an unset backend is resolved when run() starts.
        self._backend = backend

    @property
    def game(self) -> Game:
        """The game this application runs."""
        return self._game

    @property
    def clock(self) -> Clock:
        """The clock driving the loop.

        The application has no timing of its own; every ``dt`` a game sees
        comes from this object.
        """
        return self._clock

    @property
    def backend(self) -> PlatformBackend | None:
        """The backend this application runs on.

        ``None`` until :meth:`run` selects one, unless one was supplied.
        """
        return self._backend

    def run(self) -> None:
        """Run the game to completion.

        Creates the window, calls
        :meth:`~trjoludus.game.Game.on_start`, runs the loop until the game
        calls :meth:`~trjoludus.game.Game.quit`, then calls
        :meth:`~trjoludus.game.Game.on_stop`, closes the window and shuts the
        backend down.

        The window is closed and the backend shut down even if a callback
        raises, and the exception is re-raised rather than swallowed.
        :meth:`~trjoludus.game.Game.on_stop` runs only when
        :meth:`~trjoludus.game.Game.on_start` completed, so a game is never
        asked to tear down state it never built.

        Raises:
            PlatformError: If no backend could be started -- for example when
                no X display is reachable. Nothing has been created at that
                point, so there is nothing to clean up.
        """
        if self._backend is None:
            self._backend = create_backend()

        window = None
        started = False
        try:
            width, height = self._size
            window = self._backend.create_window(self._title, width, height)
            self._game.on_start()
            started = True
            self._loop(window)
        finally:
            try:
                if started:
                    self._game.on_stop()
            finally:
                if window is not None:
                    window.close()
                self._backend.shutdown()

    def _loop(self, window) -> None:
        """Run frames until the game asks to stop."""
        game = self._game
        while not game.quit_requested:
            # The whole batch is delivered even if a handler calls quit():
            # these events already happened, and dropping some of them would
            # make delivery depend on where in the batch quit() landed.
            for event in window.poll_events():
                game.on_event(event)

            if game.quit_requested:
                break

            game.on_update(self._clock.tick())


def run(
    game: Game,
    *,
    title: str = DEFAULT_TITLE,
    size: tuple[int, int] = DEFAULT_SIZE,
    max_fps: float | None = DEFAULT_MAX_FPS,
) -> None:
    """Run a game. This is the entry point to TrjoLudus.

    ::

        import trjoludus as tl

        class MyGame(tl.Game):
            def on_update(self, dt):
                ...

        tl.run(MyGame(), title="My Game", size=(800, 600))

    Args:
        game: The game to run.
        title: Window title.
        size: ``(width, height)`` of the client area, in pixels.
        max_fps: Target frame rate, or ``None`` to run unpaced.

    Raises:
        TypeError: If ``title``, ``width`` or ``height`` has the wrong type.
        ValueError: If ``size`` is not a pair, if either dimension is not
            positive, or if ``max_fps`` is not positive.
    """
    Application(game, title=title, size=size, max_fps=max_fps).run()
