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

from collections import deque
from time import sleep

from trjoludus.clock import DEFAULT_MAX_FPS, Clock
from trjoludus.errors import TrjoLudusError
from trjoludus.game import Game
from trjoludus.platform import create_backend
from trjoludus.platform.base import PlatformBackend
from trjoludus.events import (
    KeyPressed,
    MouseButtonPressed,
    MouseButtonReleased,
    MouseMoved,
)
from trjoludus.render import Framebuffer
from trjoludus.scene import current_scene
from trjoludus.ui import current_ui

__all__ = ["Application", "current_application", "run"]

#: How long to pause between polls while waiting for a key, in seconds. Small
#: enough to feel instant, large enough that waiting does not spin a CPU core.
KEY_POLL_INTERVAL = 0.001

_running: "Application | None" = None


def current_application() -> "Application | None":
    """The application currently running, or ``None``.

    How :func:`trjoludus.keyboard.wait` reaches the loop it has to pump. Only
    one game runs at a time, so one reference is enough.
    """
    return _running

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
        self._framebuffer = Framebuffer(*self._size)
        self._keys: deque[str] = deque()
        self._clicks: deque[tuple[str, int, int]] = deque()
        self._window = None
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
        global _running

        if self._backend is None:
            self._backend = create_backend()

        window = None
        started = False
        previous, _running = _running, self
        try:
            width, height = self._size
            window = self._backend.create_window(self._title, width, height)
            self._window = window
            self._game.on_start()
            started = True
            # Show what on_start built before running a single frame. The loop
            # draws after on_update, so a game whose first update blocks --
            # waiting for a key, say -- would otherwise sit on an empty window
            # until the player pressed something, which looks broken.
            self._render(window)
            self._loop(window)
        finally:
            from trjoludus.keyboard import key as _key

            from trjoludus import mouse as _mouse

            _running = previous
            self._window = None
            self._keys.clear()
            self._clicks.clear()
            _mouse._reset()
            # Unread input belonged to this run, and so did the last key. A
            # second game must not start out holding the first one's press.
            _key._set(None)
            try:
                if started:
                    self._game.on_stop()
            finally:
                # Each step gets its own finally so a failure in one cannot
                # skip the next. Closing the window and shutting the backend
                # down release different resources -- an X display connection
                # and a registered window class outlive the window that used
                # them -- so a raising close() must not leak the backend.
                try:
                    if window is not None:
                        window.close()
                finally:
                    try:
                        self._backend.shutdown()
                    finally:
                        # The objects and the UI belonged to this run.
                        # Leaving them would make a second run inherit the
                        # first game's scene and menus, and every name in
                        # them would then collide.
                        current_scene().clear()
                        current_ui().clear()

    def _loop(self, window) -> None:
        """Run frames until the game asks to stop."""
        game = self._game
        while not game.quit_requested and self._backend.keeps_application_alive:
            # The whole batch is delivered even if a handler calls quit():
            # these events already happened, and dropping some of them would
            # make delivery depend on where in the batch quit() landed.
            self._deliver(window.poll_events())

            if game.quit_requested:
                break

            game.on_update(self._clock.tick())
            self._render(window)

    def _deliver(self, events) -> None:
        """Route one batch of events.

        Input goes into queues for the waiting calls rather than to
        ``on_event``. Delivering it to both would show a game the same press
        twice and leave it unclear which one owned it.

        Pointer movement is state, not input: it updates where the mouse is
        and queues nothing, so a wait is not ended by someone nudging the
        mouse.
        """
        from trjoludus import mouse

        for event in events:
            if isinstance(event, KeyPressed):
                self._keys.append(event.key)
            elif isinstance(event, MouseMoved):
                mouse._moved(event.x, event.y)
            elif isinstance(event, MouseButtonPressed):
                mouse._button_down(event.button, event.x, event.y)
                self._clicks.append((event.button, event.x, event.y))
            elif isinstance(event, MouseButtonReleased):
                mouse._button_up(event.button, event.x, event.y)
            else:
                self._game.on_event(event)

    def _wait_for_key(self) -> str | None:
        """Block until a key press is available, and return its name."""
        return self._wait_for(self._keys, "keyboard.wait()")

    def _wait_for_mouse(self) -> tuple[str, int, int] | None:
        """Block until a mouse button is pressed.

        Returns ``(button, x, y)`` -- the position is the one the click
        happened at, not wherever the pointer has drifted to since, so a game
        acting on a click acts on the right place.
        """
        return self._wait_for(self._clicks, "mouse.wait()")

    def _wait_for(self, queue: deque, called: str) -> str | None:
        """Block until ``queue`` has something in it, and take the oldest.

        Input is queued and handed out oldest first, each item returned
        exactly once. Something that arrived earlier and has not been answered
        yet comes back immediately -- that is a new event, not a repeat of the
        last one.

        Pumps the same window and delivers other events the way the main loop
        does, so a close request still reaches the game while a wait is in
        progress. Returns ``None`` rather than waiting forever if the game
        quits, or if its last window disappears -- a window can be destroyed
        without a close request ever being sent, and then the input being
        waited for can never arrive.

        One implementation for every kind of waiting, so a new one cannot
        quietly miss a reason to stop.
        """
        if self._window is None:  # pragma: no cover -- run() sets it
            raise TrjoLudusError(f"{called} needs a running game.")

        while True:
            if queue:
                return queue.popleft()
            if self._game.quit_requested:
                return None
            if not self._backend.keeps_application_alive:
                return None
            self._deliver(self._window.poll_events())
            if queue or self._game.quit_requested:
                continue
            # Nothing arrived. Pause briefly rather than spin: this is pacing,
            # not a wait for something that has already happened.
            sleep(KEY_POLL_INTERVAL)

    def _render(self, window) -> None:
        """Draw the scene and hand the finished frame to the backend.

        Rendering happens after the update so a frame shows the state the game
        just produced, rather than the previous one.
        """
        width, height = window.size
        self._framebuffer.resize(width, height)
        self._framebuffer.clear()

        for obj in current_scene().objects():
            if obj.visible:
                self._framebuffer.draw_image(obj.image, obj.x, obj.y)

        # UI last, so it sits on top of the game rather than behind it.
        current_ui().render(self._framebuffer)

        window.present(
            self._framebuffer.pixels,
            self._framebuffer.width,
            self._framebuffer.height,
        )


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
