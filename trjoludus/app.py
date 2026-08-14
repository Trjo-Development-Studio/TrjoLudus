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
    KeyReleased,
    MouseButtonPressed,
    MouseButtonReleased,
    MouseMoved,
)
from trjoludus.keyboard import KeyboardState
from trjoludus.mouse import MouseState
from trjoludus.render import Framebuffer
from trjoludus.scene import current_scene
from trjoludus.ui import current_ui

__all__ = ["Application", "PendingInput", "current_application", "run"]


class PendingInput:
    """One piece of input waiting to be read.

    Remembers which window it came from, so input is never attributed to the
    wrong one once there is more than a single window to confuse.
    """

    __slots__ = ("kind", "value", "window", "x", "y")

    def __init__(self, kind: str, value: str, window,
                 x: int = 0, y: int = 0) -> None:
        self.kind = kind
        self.value = value
        self.window = window
        self.x = x
        self.y = y

    def __repr__(self) -> str:
        return f"PendingInput({self.kind!r}, {self.value!r})"

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
        # One queue, in arrival order, holding every kind of input. Separate
        # queues per kind would lose the order between a key and a click,
        # which input.wait() has to preserve.
        self._input: deque[PendingInput] = deque()
        self._mouse_states: dict[object, MouseState] = {}
        # Which keys are held, per window. Kept up to date as key events
        # arrive, so asking is a set lookup rather than a scan of anything.
        self._key_states: dict[object, KeyboardState] = {}
        # Clicks that arrived during the current frame. UI asks about these
        # rather than taking them off the queue: "was I clicked" is a question
        # about what happened, not a wait that consumes the answer.
        self._frame_clicks: list[PendingInput] = []
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
            # A stop request belongs to one run. Clearing it here is what lets
            # the same game instance be run again after it quit.
            self._game._begin_run()
            # So does the timing. Without this a second run would open with a
            # delta measuring the gap between the two runs, and a frame count
            # carried over from the first.
            self._clock.reset()
            self._game.on_start()
            started = True
            # Show what on_start built before running a single frame. The loop
            # draws after on_update, so a game whose first update blocks --
            # waiting for a key, say -- would otherwise sit on an empty window
            # until the player pressed something, which looks broken.
            self._render(window)
            self._loop(window)
        finally:
            from trjoludus import keyboard as _keyboard
            from trjoludus.keyboard import key as _key

            _running = previous
            self._window = None
            self._input.clear()
            self._mouse_states.clear()
            # Nothing can still be held once the window is gone: there is no
            # release coming for a window that no longer exists, so a key held
            # at that moment would otherwise be held for good.
            for keys in self._key_states.values():
                keys.forget_everything()
            self._key_states.clear()
            _keyboard._reset()
            self._frame_clicks.clear()
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
            # A click belongs to the frame it arrived in, so what UI can ask
            # about starts empty each time round.
            self._frame_clicks.clear()
            # The whole batch is delivered even if a handler calls quit():
            # these events already happened, and dropping some of them would
            # make delivery depend on where in the batch quit() landed.
            self._deliver(window.poll_events())

            if game.quit_requested:
                break

            game.on_update(self._clock.tick())
            # After the update, so an animation started this frame shows its
            # first frame now; before the render, so what moves on is what
            # gets drawn. Paced by the same clock as everything else.
            current_scene().advance_animations(self._clock.delta)
            self._render(window)

    def _deliver(self, events, window=None) -> None:
        """Route one batch of events from ``window``.

        Input is queued for the waiting calls rather than delivered to
        ``on_event``. Sending it to both would show a game the same press
        twice and leave it unclear which one owned it.

        Every queued item remembers the window it came from, so input can
        never be attributed to the wrong one. Pointer movement is state rather
        than input: it updates where the mouse is in that window and queues
        nothing, so a wait is not ended by someone nudging the mouse.
        """
        window = self._window if window is None else window
        state = self.mouse_state(window)
        keys = self.keyboard_state(window)

        for event in events:
            if isinstance(event, KeyPressed):
                # Both: the press is input a wait can answer, *and* the key is
                # now held. They are separate questions about the same event,
                # so neither takes anything from the other.
                keys.key_down(event.key)
                self._input.append(PendingInput("key", event.key, window))
            elif isinstance(event, KeyReleased):
                # State only. A key coming up is the end of something rather
                # than new input, so nothing waits for it.
                keys.key_up(event.key)
            elif isinstance(event, MouseMoved):
                state.moved(event.x, event.y)
            elif isinstance(event, MouseButtonPressed):
                state.button_down(event.button, event.x, event.y)
                click = PendingInput("mouse", event.button, window,
                                     event.x, event.y)
                self._input.append(click)
                self._frame_clicks.append(click)
            elif isinstance(event, MouseButtonReleased):
                state.button_up(event.button, event.x, event.y)
            else:
                self._game.on_event(event)

    def clicks_this_frame(self, window=None) -> tuple[PendingInput, ...]:
        """Clicks that arrived this frame, in the window given.

        Asking does not consume them: several things may want to know about
        the same click, and a UI query is not a wait. They are dropped when
        the next frame begins.
        """
        window = self._window if window is None else window
        return tuple(
            click for click in self._frame_clicks if click.window is window
        )

    def keyboard_state(self, window=None) -> KeyboardState:
        """Which keys are held in one window, created on first use.

        Per window because a key is held *in* a window: one that is not
        focused is not receiving it. A game has one window today, so
        ``keyboard.button`` reads this; several windows would each have their
        own without the input system changing shape.
        """
        window = self._window if window is None else window
        state = self._key_states.get(window)
        if state is None:
            state = KeyboardState()
            self._key_states[window] = state
        return state

    def mouse_state(self, window=None) -> MouseState:
        """The pointer state for one window, created on first use.

        Per window because a position only means anything against a particular
        drawable area. A game has one window today, so the module-level
        :mod:`trjoludus.mouse` names read this; several windows would each
        have their own without the input system changing.
        """
        window = self._window if window is None else window
        state = self._mouse_states.get(window)
        if state is None:
            state = MouseState()
            self._mouse_states[window] = state
        return state

    def wait_for_input(self, kind: str | None = None) -> PendingInput | None:
        """Block until input arrives, and record it where a game reads it.

        Args:
            kind: ``"key"``, ``"mouse"``, or ``None`` for whichever comes
                first.

        Returns:
            The item taken, or ``None`` if the wait gave up.

        Input is queued in arrival order and handed out oldest first, each
        item taken exactly once. Asking for one kind leaves the other kind
        untouched in the queue rather than discarding it, so a key pressed
        while a game waits for a click is still there for the keyboard to
        read.

        Pumps the same window and delivers other events the way the main loop
        does, so a close request still reaches the game while a wait is in
        progress. Gives up -- returning ``None`` -- if the game quits or its
        last window disappears. A window can be destroyed without any close
        request being sent, and then the input being waited for can never
        arrive, so every blocking call has to stop for that as well.

        One implementation for every kind of waiting, so a new one cannot
        quietly miss a reason to stop.
        """
        if self._window is None:  # pragma: no cover -- run() sets it
            raise TrjoLudusError("waiting for input needs a running game.")

        while True:
            taken = self._take(kind)
            if taken is not None:
                self._record(taken)
                return taken
            if not self._keep_waiting(lambda: self._peek(kind)):
                break

        self._record(None, kind)
        return None

    def wait_for_seconds(self, seconds: float) -> bool:
        """Block for roughly ``seconds`` while keeping the window alive.

        Not a second game loop: it turns the same crank
        :meth:`wait_for_input` does, so events are still polled and delivered
        and a close request still reaches the game while the wait runs.

        Returns:
            ``True`` if the full time passed, ``False`` if the wait had to
            give up because the game quit or its last window disappeared.

        The pause between polls is never longer than the time remaining, so a
        wait shorter than the poll interval is still roughly the length it
        asked for rather than being rounded up to it.
        """
        if self._window is None:  # pragma: no cover -- run() sets it
            raise TrjoLudusError("waiting needs a running game.")

        deadline = self._clock.now() + seconds
        while True:
            remaining = deadline - self._clock.now()
            if remaining <= 0.0:
                return True
            if not self._keep_waiting(
                lambda: False, min(KEY_POLL_INTERVAL, remaining)
            ):
                return False

    def _keep_waiting(self, ready, pause: float = KEY_POLL_INTERVAL) -> bool:
        """One turn of a blocking wait. ``False`` when it has to give up.

        Every blocking call in the engine turns here, which is what stops a
        new kind of waiting from quietly missing a reason to stop: the game
        asking to quit, or its last window disappearing. A window can be
        destroyed without any close request being sent, and then whatever is
        being waited for can never arrive.

        Args:
            ready: Asked after polling whether the thing being waited for has
                arrived. When it has, the pause is skipped.
            pause: How long to sleep when nothing arrived. Pausing rather
                than spinning is pacing, not a wait for something that has
                already happened.
        """
        if self._game.quit_requested:
            return False
        if not self._backend.keeps_application_alive:
            return False
        self._deliver(self._window.poll_events())
        if ready() or self._game.quit_requested:
            return True
        sleep(pause)
        return True

    def _peek(self, kind: str | None) -> bool:
        """Whether the queue holds anything of the kind being waited for."""
        return any(kind is None or item.kind == kind for item in self._input)

    def _take(self, kind: str | None) -> "PendingInput | None":
        """Remove and return the oldest item of ``kind``, if there is one.

        Scans rather than popping the front, so waiting for one kind does not
        disturb the other. The queue holds a handful of items at most, and
        order is what matters here rather than the cost of looking.
        """
        for index, item in enumerate(self._input):
            if kind is None or item.kind == kind:
                del self._input[index]
                return item
        return None

    def _record(self, taken: "PendingInput | None",
                kind: str | None = None) -> None:
        """Put what was taken where a game reads it.

        A wait that gave up clears whatever it was waiting for, so a stale key
        or click cannot be acted on during shutdown.
        """
        from trjoludus.keyboard import key as key_value

        if taken is None:
            if kind in (None, "key"):
                key_value._set(None)
            if kind in (None, "mouse"):
                self.mouse_state().button = None
            return

        if taken.kind == "key":
            key_value._set(taken.value)
            return

        state = self.mouse_state(taken.window)
        state.button = taken.value
        # Report where the click happened. Several events can arrive in one
        # batch, so the pointer may already have moved on; the click's own
        # position is what a game acting on it means.
        state.moved(taken.x, taken.y)

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
                self._framebuffer.draw_image(obj.image, obj.x, obj.y,
                                            obj.scale)

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
