"""Win32 backend.

Creates real windows through user32.

**Push becomes pull.** Windows delivers messages by calling a window
procedure, while :class:`~trjoludus.platform.base.PlatformWindow` is pull-based.
The window procedure therefore does nothing but translate the handful of
messages this milestone cares about into platform-neutral events and queue
them; :meth:`Win32Window.poll_events` drains that queue. Game callbacks are
never invoked from inside the window procedure, and the backend never runs a
loop of its own -- the application still owns the loop.

**Closing stays the game's decision.** ``WM_CLOSE`` is answered with 0 rather
than passed to ``DefWindowProcW``, because the default handler destroys the
window. Queuing a
:class:`~trjoludus.events.WindowCloseRequested` and leaving the window alive
matches what the X11 backend does with ``WM_DELETE_WINDOW``.
"""

import ctypes
import itertools
import sys
from collections.abc import Iterable

from trjoludus.errors import PlatformError
from trjoludus.events import Event, WindowCloseRequested, WindowResized
from trjoludus.platform.base import PlatformBackend, PlatformWindow
from trjoludus.platform.windows import _user32

__all__ = ["Win32Backend", "Win32Window"]

#: Identifier for this backend.
BACKEND_NAME = "win32"

#: Window classes are process-global and cannot be registered twice under the
#: same name, so each backend registers its own.
_class_counter = itertools.count()


def _last_error_message(action: str) -> str:
    return f"{action} failed (Win32 error {ctypes.get_last_error()})."


def loword(value: int) -> int:
    """Low 16 bits of a message parameter.

    LPARAM is signed and pointer-sized, so it reaches Python as a possibly
    negative int. Masking rather than slicing keeps the result the unsigned
    16-bit quantity Win32 means.
    """
    return value & 0xFFFF


def hiword(value: int) -> int:
    """Bits 16-31 of a message parameter. See :func:`loword`."""
    return (value >> 16) & 0xFFFF


class Win32Window(PlatformWindow):
    """A real Win32 window.

    Created by :meth:`Win32Backend.create_window`; not constructed directly.
    """

    def __init__(self, backend: "Win32Backend", hwnd: int, title: str,
                 width: int, height: int) -> None:
        self._backend = backend
        self._hwnd = hwnd
        self._title = title
        self._size = (width, height)
        self._pending: list[Event] = []
        self._closed = False
        self._destroyed_by_os = False

    @property
    def hwnd(self) -> int:
        """The native window handle. Specific to this backend."""
        return self._hwnd

    @property
    def is_closed(self) -> bool:
        """Whether :meth:`close` has been called."""
        return self._closed

    @property
    def size(self) -> tuple[int, int]:
        """Current ``(width, height)`` of the client area, in pixels.

        Starts as the requested client size and tracks every ``WM_SIZE``.
        """
        return self._size

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value
        if not self._closed:
            self._backend._set_title(self._hwnd, value)

    def poll_events(self) -> Iterable[Event]:
        """Drain this window's events. Never blocks."""
        if not self._closed:
            self._backend._pump()
        events, self._pending = self._pending, []
        return events

    def close(self) -> None:
        """Destroy the native window. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        self._pending = []
        self._backend._destroy_window(self)


class Win32Backend(PlatformBackend):
    """Backend that creates real windows through user32.

    Loads the libraries, makes the process DPI-aware and registers a window
    class on construction, so a broken environment fails immediately rather
    than at first use.

    Raises:
        PlatformError: If this is not Windows, or the window class could not
            be registered.
    """

    def __init__(self) -> None:
        self._user32, self._kernel32 = _user32.load_libraries()
        self._instance = self._kernel32.GetModuleHandleW(None)
        self._windows: dict[int, Win32Window] = {}
        self._shut_down = False

        self._enable_dpi_awareness()

        # Windows keeps a raw pointer to this callback for as long as the
        # class is registered, so Python must hold a reference to it. Letting
        # it be collected would leave Windows calling into freed memory --
        # storing it on the instance is what prevents that.
        self._wndproc = _user32.WNDPROC(self._handle_message)

        self._class_name = f"TrjoLudusWindow{next(_class_counter)}"
        self._register_class()

    @property
    def name(self) -> str:
        """Always ``"win32"``."""
        return BACKEND_NAME

    @property
    def is_shut_down(self) -> bool:
        """Whether :meth:`shutdown` has been called."""
        return self._shut_down

    @property
    def windows(self) -> tuple[Win32Window, ...]:
        """Windows that are currently open."""
        return tuple(self._windows.values())

    def _enable_dpi_awareness(self) -> None:
        """Opt into per-monitor DPI awareness, before any window exists.

        Without it Windows reports scaled, incorrect window dimensions. The
        call is Windows 10 1703+; on anything older it is simply absent, which
        is not fatal -- sizes are merely subject to the system's scaling.
        """
        set_context = getattr(self._user32, "SetProcessDpiAwarenessContext", None)
        if set_context is None:  # pragma: no cover -- needs an old Windows
            return
        set_context(_user32.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)

    def _register_class(self) -> None:
        window_class = _user32.WNDCLASSEXW()
        window_class.cbSize = ctypes.sizeof(_user32.WNDCLASSEXW)
        window_class.style = _user32.CS_HREDRAW | _user32.CS_VREDRAW
        window_class.lpfnWndProc = self._wndproc
        window_class.cbClsExtra = 0
        window_class.cbWndExtra = 0
        window_class.hInstance = self._instance
        window_class.hIcon = None
        window_class.hCursor = self._user32.LoadCursorW(
            None, ctypes.c_wchar_p(_user32.IDC_ARROW)
        )
        window_class.hbrBackground = None
        window_class.lpszMenuName = None
        window_class.lpszClassName = self._class_name
        window_class.hIconSm = None

        if not self._user32.RegisterClassExW(ctypes.byref(window_class)):
            raise PlatformError(_last_error_message("RegisterClassExW"))

    def create_window(self, title: str, width: int, height: int) -> Win32Window:
        """Create and show a window with the given client-area size.

        ``width`` and ``height`` describe the drawable area. Win32 sizes
        windows by their outer rectangle, so the requested client size is
        expanded by the frame with ``AdjustWindowRectEx`` first; skipping that
        would silently shrink the drawable area by the border and caption.

        Raises:
            PlatformError: If the backend has been shut down, or the window
                could not be created.
        """
        if self._shut_down:
            raise PlatformError("Cannot create a window after backend shutdown.")

        style = _user32.WS_OVERLAPPEDWINDOW
        ex_style = _user32.WS_EX_APPWINDOW

        rect = _user32.RECT(0, 0, width, height)
        if not self._user32.AdjustWindowRectEx(
            ctypes.byref(rect), style, False, ex_style
        ):
            raise PlatformError(_last_error_message("AdjustWindowRectEx"))

        hwnd = self._user32.CreateWindowExW(
            ex_style,
            self._class_name,
            title,
            style,
            _user32.CW_USEDEFAULT,
            _user32.CW_USEDEFAULT,
            rect.right - rect.left,
            rect.bottom - rect.top,
            None,
            None,
            self._instance,
            None,
        )
        if not hwnd:
            raise PlatformError(_last_error_message("CreateWindowExW"))

        window = Win32Window(self, hwnd, title, width, height)
        self._windows[hwnd] = window

        self._user32.ShowWindow(hwnd, _user32.SW_SHOWNORMAL)
        window._size = self._client_size(hwnd, (width, height))
        return window

    def shutdown(self) -> None:
        """Close every remaining window and unregister the window class.

        Safe to call more than once.
        """
        if self._shut_down:
            return
        self._shut_down = True

        for window in tuple(self._windows.values()):
            window.close()
        self._windows.clear()

        # A registered class outlives the windows that used it, so it has to
        # be released explicitly or the process leaks one per backend.
        self._user32.UnregisterClassW(self._class_name, self._instance)

    def _client_size(self, hwnd: int, fallback: tuple[int, int]) -> tuple[int, int]:
        """Read the real client size, falling back to what was requested."""
        rect = _user32.RECT()
        if not self._user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return fallback
        return (rect.right - rect.left, rect.bottom - rect.top)

    def _set_title(self, hwnd: int, title: str) -> None:
        """Set the window title through the wide-character API.

        ``SetWindowTextW`` takes UTF-16, which ctypes produces from a Python
        ``str`` directly. The ANSI variant would mangle anything outside the
        active code page.
        """
        self._user32.SetWindowTextW(hwnd, title)

    def _destroy_window(self, window: Win32Window) -> None:
        """Destroy one window's native resources."""
        self._windows.pop(window._hwnd, None)
        if not window._destroyed_by_os:
            self._user32.DestroyWindow(window._hwnd)

    def _pump(self) -> None:
        """Drain the thread's message queue without blocking.

        ``PeekMessageW`` with a null window handle takes messages for every
        window on this thread, so one pump serves all of them. Dispatching is
        what calls :meth:`_handle_message`, which is where events are queued.
        """
        message = _user32.MSG()
        while self._user32.PeekMessageW(
            ctypes.byref(message), None, 0, 0, _user32.PM_REMOVE
        ):
            self._user32.TranslateMessage(ctypes.byref(message))
            self._user32.DispatchMessageW(ctypes.byref(message))

    def _handle_message(self, hwnd, message, wparam, lparam):
        """The window procedure. Called by Windows during :meth:`_pump`.

        Translates the few messages this milestone understands into
        platform-neutral events and queues them. It deliberately does no more
        than that: no game callback runs here, and nothing about the engine's
        loop depends on when Windows chooses to call it.
        """
        window = self._windows.get(hwnd)

        if window is not None:
            if message == _user32.WM_CLOSE:
                # Not forwarded to DefWindowProcW, which would destroy the
                # window. Closing is a request the game answers.
                window._pending.append(WindowCloseRequested())
                return 0

            if message == _user32.WM_SIZE:
                if wparam != _user32.SIZE_MINIMIZED:
                    size = (loword(lparam), hiword(lparam))
                    if size != window._size:
                        window._size = size
                        window._pending.append(WindowResized(size[0], size[1]))
                return 0

            if message == _user32.WM_DESTROY:
                # The window is already gone; close() must not ask again.
                # PostQuitMessage is deliberately not called: WM_QUIT exists to
                # end a message loop, and the loop here belongs to the
                # application, not to this backend.
                window._destroyed_by_os = True
                return 0

        return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)
