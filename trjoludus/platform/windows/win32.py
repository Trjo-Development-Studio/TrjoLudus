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


#: Virtual-key codes that are not simply a character, as canonical names.
_NAMED_VIRTUAL_KEYS = {
    _user32.VK_ESCAPE: "ESCAPE",
    _user32.VK_RETURN: "ENTER",
    _user32.VK_SPACE: "SPACE",
    _user32.VK_UP: "UP",
    _user32.VK_DOWN: "DOWN",
    _user32.VK_LEFT: "LEFT",
    _user32.VK_RIGHT: "RIGHT",
}


def key_name(virtual_key: int) -> str | None:
    """Translate a Win32 virtual-key code into a canonical key name.

    Returns ``None`` for keys TrjoLudus has no name for, so they are ignored
    rather than reported under a guessed name.
    """
    named = _NAMED_VIRTUAL_KEYS.get(virtual_key)
    if named is not None:
        return named
    # Letter and digit virtual-key codes are the ASCII code of the uppercase
    # character, which is already the canonical name.
    if 0x41 <= virtual_key <= 0x5A:  # A-Z
        return chr(virtual_key)
    if 0x30 <= virtual_key <= 0x39:  # 0-9
        return chr(virtual_key)
    return None


#: Which button each message concerns, and whether it went down.
_BUTTON_MESSAGES = {
    _user32.WM_LBUTTONDOWN: ("LEFT", True),
    _user32.WM_LBUTTONUP: ("LEFT", False),
    _user32.WM_RBUTTONDOWN: ("RIGHT", True),
    _user32.WM_RBUTTONUP: ("RIGHT", False),
    _user32.WM_MBUTTONDOWN: ("MIDDLE", True),
    _user32.WM_MBUTTONUP: ("MIDDLE", False),
}


def signed_word(value: int) -> int:
    """Read a 16-bit field as signed.

    Pointer coordinates are signed: with the mouse captured, a drag past the
    left or top edge reports a negative position, which read as unsigned would
    become a number near 65535.
    """
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def mouse_position(lparam: int) -> tuple[int, int]:
    """Unpack the pointer position Win32 packs into an LPARAM."""
    return (signed_word(lparam), signed_word(lparam >> 16))


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
    def is_open(self) -> bool:
        """Whether the native window still exists.

        False once the game closes it *or* Windows destroys it, which are
        different things: a window can go away without anyone asking.
        """
        return not self._closed and not self._destroyed_by_os

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
        if self.is_open:
            self._backend._set_title(self._hwnd, value)

    def poll_events(self) -> Iterable[Event]:
        """Drain this window's events. Never blocks."""
        if not self._closed:
            self._backend._pump()
        events, self._pending = self._pending, []
        return events

    def present(self, pixels, width: int, height: int) -> None:
        """Blit a BGRA buffer onto the window.

        Does nothing once the window is gone, so a frame drawn just before
        Windows destroyed it is not sent to a dead handle.
        """
        if not self.is_open:
            return
        self._backend._put_image(self._hwnd, pixels, width, height)

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
        self._user32, self._kernel32, self._gdi32 = _user32.load_libraries()
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

    @property
    def keeps_application_alive(self) -> bool:
        """Whether any window this backend created still exists."""
        return any(window.is_open for window in self._windows.values())

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

    def _put_image(self, hwnd: int, pixels, width: int, height: int) -> None:
        """Copy a BGRA buffer to a window with StretchDIBits.

        A 32-bit ``BI_RGB`` DIB is blue, green, red, unused in memory, which
        is the layout the engine already composites into, so the buffer goes
        across untouched.

        ``biHeight`` is negative on purpose: a positive height means a DIB is
        stored bottom-up, and the engine's rows run top-down.
        """
        if width <= 0 or height <= 0:
            return

        buffer = pixels if isinstance(pixels, bytearray) else bytearray(pixels)
        if len(buffer) < width * height * 4:
            return

        info = _user32.BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(_user32.BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = _user32.BI_RGB

        raw = (ctypes.c_char * len(buffer)).from_buffer(buffer)
        device = self._user32.GetDC(hwnd)
        if not device:
            return
        try:
            self._gdi32.StretchDIBits(
                device,
                0, 0, width, height,
                0, 0, width, height,
                ctypes.cast(raw, ctypes.c_void_p),
                ctypes.byref(info),
                _user32.DIB_RGB_COLORS,
                _user32.SRCCOPY,
            )
        finally:
            self._user32.ReleaseDC(hwnd, device)

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

            if message == _user32.WM_MOUSEMOVE:
                x, y = mouse_position(lparam)
                window._pending.append(MouseMoved(x, y))
                return 0

            button = _BUTTON_MESSAGES.get(message)
            if button is not None:
                name, went_down = button
                x, y = mouse_position(lparam)
                window._pending.append(
                    MouseButtonPressed(name, x, y) if went_down
                    else MouseButtonReleased(name, x, y)
                )
                return 0

            if message in (_user32.WM_KEYDOWN, _user32.WM_SYSKEYDOWN,
                           _user32.WM_KEYUP, _user32.WM_SYSKEYUP):
                went_down = message in (_user32.WM_KEYDOWN,
                                        _user32.WM_SYSKEYDOWN)
                name = key_name(wparam)
                if name is not None:
                    window._pending.append(
                        KeyPressed(name) if went_down else KeyReleased(name)
                    )
                # Still forwarded: DefWindowProcW turns key messages into
                # system behaviour such as Alt opening the window menu.
                return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)

            if message == _user32.WM_DESTROY:
                # The window is already gone; close() must not ask again.
                # PostQuitMessage is deliberately not called: WM_QUIT exists to
                # end a message loop, and the loop here belongs to the
                # application, not to this backend.
                window._destroyed_by_os = True
                return 0

        return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)
