"""Contracts every platform backend implements.

These abstract classes are the seam between the engine and the operating
system. The engine talks only to what is declared here; each backend
(``linux/x11.py``, ``windows/win32.py``, ``null.py``) provides the other side.

The module itself is platform-neutral and contains no ``ctypes`` and no OS
knowledge. It lives under ``trjoludus/platform/`` because it defines that
layer's shape, not because it touches an operating system.

**Events are pulled, not pushed.** :meth:`PlatformWindow.poll_events` drains a
queue. X11 works this way natively; Win32 does not -- it calls a ``WndProc``
callback -- so the Win32 backend queues internally and drains here. Normalising
at this level means nothing above the platform layer knows the difference.

Abstract base classes are used rather than protocols so that a backend missing
a method fails loudly at instantiation, rather than subtly at the first call.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable

from trjoludus.events import Event

__all__ = ["PlatformBackend", "PlatformWindow"]


class PlatformWindow(ABC):
    """A single operating-system window."""

    @property
    @abstractmethod
    def size(self) -> tuple[int, int]:
        """Current ``(width, height)`` of the client area, in pixels.

        This is the drawable area, excluding any window decorations.
        """

    @property
    @abstractmethod
    def title(self) -> str:
        """The window's title text."""

    @title.setter
    @abstractmethod
    def title(self, value: str) -> None:
        """Set the window's title text."""

    @abstractmethod
    def poll_events(self) -> Iterable[Event]:
        """Drain and return the events that arrived since the last call.

        Never blocks. Returns an empty iterable when nothing has happened.
        """

    @abstractmethod
    def close(self) -> None:
        """Destroy the window and release its operating-system resources.

        Must be safe to call more than once.
        """


class PlatformBackend(ABC):
    """Entry point to one platform implementation."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this backend, e.g. ``"x11"`` or ``"null"``.

        Matches the value accepted by the ``TRJOLUDUS_BACKEND`` override.
        """

    @abstractmethod
    def create_window(self, title: str, width: int, height: int) -> PlatformWindow:
        """Create and show a window.

        Args:
            title: Initial window title.
            width: Initial client-area width, in pixels.
            height: Initial client-area height, in pixels.

        Raises:
            PlatformError: If the window could not be created.
        """

    @abstractmethod
    def shutdown(self) -> None:
        """Release resources held by the backend itself.

        Called once, after every window has been closed. Must be safe to call
        more than once.
        """
