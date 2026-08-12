"""Headless backend.

A complete implementation of the platform contracts that talks to no operating
system at all. It needs no display, no X11, no Wayland, no Win32, no ``ctypes``
and no third-party packages, so it runs anywhere Python does -- including in CI
and over SSH with every ``DISPLAY``-style variable unset.

Its purpose is to make the engine testable. The game loop, timing and lifecycle
can be exercised end to end against this backend, so that when a real backend
lands, any failure is unambiguously in that backend rather than in the engine.

Tests drive it through :meth:`NullWindow.simulate_event`, which stands in for
the operating system delivering a message. That method exists on this class
only -- it is deliberately absent from
:class:`~trjoludus.platform.base.PlatformWindow`, so no game-facing API can
inject events.
"""

from collections.abc import Iterable

from trjoludus.errors import PlatformError
from trjoludus.events import Event
from trjoludus.platform.base import PlatformBackend, PlatformWindow

__all__ = ["NullBackend", "NullWindow"]

#: Identifier for this backend. Matches the value the ``TRJOLUDUS_BACKEND``
#: override will accept once backend selection exists.
BACKEND_NAME = "null"


class NullWindow(PlatformWindow):
    """A simulated window that draws nothing and touches no operating system.

    Args:
        title: Initial window title.
        width: Client-area width, in pixels.
        height: Client-area height, in pixels.
    """

    def __init__(self, title: str, width: int, height: int) -> None:
        self._title = title
        self._size = (width, height)
        self._pending: list[Event] = []
        self._closed = False

    @property
    def size(self) -> tuple[int, int]:
        """Current ``(width, height)`` of the client area, in pixels.

        Fixed for the lifetime of a null window: there is no window manager to
        resize it. See :meth:`simulate_event` for the consequences.
        """
        return self._size

    @property
    def title(self) -> str:
        """The window's title text."""
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value

    @property
    def is_closed(self) -> bool:
        """Whether :meth:`close` has been called.

        Specific to this backend. :class:`PlatformWindow` does not declare it,
        because nothing in the engine needs it yet; it exists so that closing
        is observable in tests.
        """
        return self._closed

    def poll_events(self) -> Iterable[Event]:
        """Drain and return the events queued since the last call.

        Returns an empty list when nothing is queued, and always after the
        window has been closed.
        """
        events, self._pending = self._pending, []
        return events

    def close(self) -> None:
        """Mark the window closed and drop the resources it owns.

        The only resource a simulated window holds is its pending event queue,
        which is discarded. Safe to call any number of times.
        """
        self._closed = True
        self._pending = []

    def simulate_event(self, event: Event) -> None:
        """Queue an event as an operating system would deliver it.

        **Test-only.** This is how a test stands in for the OS. It is not part
        of the :class:`PlatformWindow` contract and is unreachable from the
        public game API.

        Events simulated on a closed window are discarded, mirroring a real
        backend: once the OS window is destroyed, nothing more arrives for it.

        Note that this only queues the event; it does not alter window state.
        Simulating a :class:`~trjoludus.events.WindowResized` therefore does
        not change :attr:`size`.

        Args:
            event: The event to deliver on the next :meth:`poll_events`.
        """
        if not self._closed:
            self._pending.append(event)


class NullBackend(PlatformBackend):
    """Backend that creates :class:`NullWindow` instances."""

    def __init__(self) -> None:
        self._windows: list[NullWindow] = []
        self._shut_down = False

    @property
    def name(self) -> str:
        """Always ``"null"``."""
        return BACKEND_NAME

    @property
    def is_shut_down(self) -> bool:
        """Whether :meth:`shutdown` has been called.

        Specific to this backend; see :attr:`NullWindow.is_closed`.
        """
        return self._shut_down

    @property
    def windows(self) -> tuple[NullWindow, ...]:
        """Windows created by this backend and not yet released by shutdown.

        Specific to this backend, for inspection in tests.
        """
        return tuple(self._windows)

    def create_window(self, title: str, width: int, height: int) -> NullWindow:
        """Create a simulated window.

        There is no operating system to refuse the request, so this fails only
        after :meth:`shutdown`. That check exists for fidelity rather than
        necessity: the real backends cannot create a window once their display
        connection or window class is gone, and a stand-in that quietly
        allowed it would let a test pass on code that breaks on Linux and
        Windows.

        The backend imposes no limit on how many windows exist at once.

        Args:
            title: Initial window title.
            width: Client-area width, in pixels.
            height: Client-area height, in pixels.

        Raises:
            PlatformError: If the backend has been shut down.
        """
        if self._shut_down:
            raise PlatformError("Cannot create a window after backend shutdown.")

        window = NullWindow(title, width, height)
        self._windows.append(window)
        return window

    def shutdown(self) -> None:
        """Release the backend's own resources.

        Drops the backend's references to the windows it created. It does not
        close them: per the contract, windows are already closed by the time
        shutdown runs. Safe to call any number of times.
        """
        self._shut_down = True
        self._windows.clear()
