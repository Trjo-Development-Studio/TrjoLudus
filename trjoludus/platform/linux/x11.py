"""X11 backend.

Creates real windows through Xlib. On a modern Wayland desktop these are
served by Xwayland, which is how the backend runs on the development machine.

**Ownership.** The backend owns the display connection for its whole lifetime:
it opens the connection when constructed and closes it in :meth:`shutdown`.
Windows borrow that connection and destroy only their own X window in
:meth:`X11Window.close`. A window never closes the display, so one window
closing cannot break another.

**Event routing.** X delivers events per *connection*, not per window, so
draining the queue from one window would consume another window's events. The
backend therefore pumps the connection once and files each event into the
window it belongs to; :meth:`X11Window.poll_events` returns only that window's
events.
"""

import sys
from collections.abc import Iterable

from trjoludus.errors import PlatformError
from trjoludus.events import Event, WindowCloseRequested, WindowResized
from trjoludus.platform.base import PlatformBackend, PlatformWindow
from trjoludus.platform.linux import _xlib

__all__ = ["X11Backend", "X11Window"]

#: Identifier for this backend.
BACKEND_NAME = "x11"

#: Protocol errors seen since the process started, most recent last. X protocol
#: errors are asynchronous, so they cannot be raised at the call site; they are
#: recorded here and written to stderr instead of vanishing.
protocol_errors: list[tuple[int, int, int]] = []

# Xlib keeps raw C function pointers to these handlers, so Python must hold a
# reference for as long as Xlib might call them. Letting either be collected
# would leave Xlib calling into freed memory.
_error_handler_ref = None
_io_error_handler_ref = None


def _install_error_handlers(xlib) -> None:
    """Install the protocol and I/O error handlers, once per process.

    Xlib's default I/O error handler terminates the process, so this must run
    before any display is opened.
    """
    global _error_handler_ref, _io_error_handler_ref
    if _io_error_handler_ref is not None:
        return

    @_xlib.IO_ERROR_HANDLER
    def on_io_error(display):
        # Xlib exits the process after this returns, no matter what it
        # returns -- the connection is already gone, so there is nothing to
        # recover. All this handler can do is make the death legible instead
        # of silent.
        print(
            "TrjoLudus: fatal X11 I/O error -- the connection to the display "
            "was lost (server exited, or the session ended). Xlib terminates "
            "the process after this point.",
            file=sys.stderr,
            flush=True,
        )
        return 0

    @_xlib.ERROR_HANDLER
    def on_error(display, event):
        error = event.contents
        protocol_errors.append(
            (error.error_code, error.request_code, error.minor_code)
        )
        print(
            f"TrjoLudus: X11 protocol error: code={error.error_code} "
            f"request={error.request_code} minor={error.minor_code}",
            file=sys.stderr,
            flush=True,
        )
        return 0

    _io_error_handler_ref = on_io_error
    _error_handler_ref = on_error
    xlib.XSetIOErrorHandler(on_io_error)
    xlib.XSetErrorHandler(on_error)


class X11Window(PlatformWindow):
    """A real X11 window.

    Created by :meth:`X11Backend.create_window`; not constructed directly.
    """

    def __init__(self, backend: "X11Backend", window_id: int, title: str,
                 width: int, height: int) -> None:
        self._backend = backend
        self._id = window_id
        self._title = title
        self._size = (width, height)
        self._pending: list[Event] = []
        self._closed = False
        self._destroyed_by_server = False

    @property
    def window_id(self) -> int:
        """The X window ID. Specific to this backend, for diagnostics."""
        return self._id

    @property
    def is_closed(self) -> bool:
        """Whether :meth:`close` has been called."""
        return self._closed

    @property
    def size(self) -> tuple[int, int]:
        """Current ``(width, height)`` of the client area, in pixels.

        Starts as the requested size and tracks every ConfigureNotify, so it
        reflects what the window manager actually granted.
        """
        return self._size

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value
        if not self._closed:
            self._backend._apply_title(self._id, value)

    def poll_events(self) -> Iterable[Event]:
        """Drain this window's events. Never blocks."""
        if not self._closed:
            self._backend._pump()
        events, self._pending = self._pending, []
        return events

    def close(self) -> None:
        """Destroy the X window. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        self._pending = []
        self._backend._destroy_window(self)


class X11Backend(PlatformBackend):
    """Backend that creates real windows through Xlib.

    Opens the display connection on construction, so a missing library or an
    unreachable server fails immediately and loudly rather than at first use.

    Raises:
        PlatformError: If Xlib cannot be loaded or the display cannot be
            opened.
    """

    def __init__(self) -> None:
        self._xlib = _xlib.load_xlib()
        _install_error_handlers(self._xlib)

        self._display = self._xlib.XOpenDisplay(None)
        if not self._display:
            raise PlatformError(
                "Could not open an X11 display. TrjoLudus's Linux backend "
                "connects through Xlib (via Xwayland on a Wayland session); "
                "check that DISPLAY is set and the session is running."
            )

        self._screen = self._xlib.XDefaultScreen(self._display)
        self._root = self._xlib.XRootWindow(self._display, self._screen)
        self._windows: dict[int, X11Window] = {}
        self._shut_down = False

        intern = self._intern_atom
        self._wm_protocols = intern("WM_PROTOCOLS")
        self._wm_delete_window = intern("WM_DELETE_WINDOW")
        self._net_wm_name = intern("_NET_WM_NAME")
        self._utf8_string = intern("UTF8_STRING")

    @property
    def name(self) -> str:
        """Always ``"x11"``."""
        return BACKEND_NAME

    @property
    def is_shut_down(self) -> bool:
        """Whether :meth:`shutdown` has been called."""
        return self._shut_down

    @property
    def windows(self) -> tuple[X11Window, ...]:
        """Windows that are currently open."""
        return tuple(self._windows.values())

    def _intern_atom(self, name: str) -> int:
        return self._xlib.XInternAtom(self._display, name.encode("ascii"), False)

    def create_window(self, title: str, width: int, height: int) -> X11Window:
        """Create and show a window with the given client-area size.

        ``width`` and ``height`` are the drawable area: XCreateSimpleWindow
        takes client dimensions directly, so no frame adjustment is needed.

        Raises:
            PlatformError: If the backend has been shut down, or the server
                refused to create the window.
        """
        if self._shut_down:
            raise PlatformError("Cannot create a window after backend shutdown.")

        xlib = self._xlib
        window_id = xlib.XCreateSimpleWindow(
            self._display,
            self._root,
            0,
            0,
            width,
            height,
            0,
            xlib.XBlackPixel(self._display, self._screen),
            xlib.XWhitePixel(self._display, self._screen),
        )
        if not window_id:
            raise PlatformError("XCreateSimpleWindow failed to create a window.")

        # Ask the window manager to send WM_DELETE_WINDOW instead of severing
        # the connection when the user clicks the close button. Without this,
        # closing the window kills the process.
        protocols = (_xlib.Atom * 1)(self._wm_delete_window)
        xlib.XSetWMProtocols(self._display, window_id, protocols, 1)

        xlib.XSelectInput(self._display, window_id, _xlib.STRUCTURE_NOTIFY_MASK)
        self._apply_title(window_id, title)
        xlib.XMapWindow(self._display, window_id)
        xlib.XFlush(self._display)

        window = X11Window(self, window_id, title, width, height)
        self._windows[window_id] = window
        return window

    def shutdown(self) -> None:
        """Close every remaining window and release the display connection.

        Safe to call more than once.
        """
        if self._shut_down:
            return
        self._shut_down = True

        for window in tuple(self._windows.values()):
            window.close()
        self._windows.clear()

        if self._display is not None:
            self._xlib.XCloseDisplay(self._display)
            self._display = None

    def _apply_title(self, window_id: int, title: str) -> None:
        """Set both the modern and legacy title properties.

        ``_NET_WM_NAME`` with a ``UTF8_STRING`` is what current window
        managers read, and is the only one of the two that is defined for
        non-ASCII text. ``XStoreName`` sets the legacy ``WM_NAME`` as a
        fallback for anything that has not been updated in twenty years.
        """
        raw = title.encode("utf-8")
        self._xlib.XStoreName(self._display, window_id, raw)
        self._xlib.XChangeProperty(
            self._display,
            window_id,
            self._net_wm_name,
            self._utf8_string,
            _xlib.PROP_FORMAT_BYTE,
            _xlib.PROP_MODE_REPLACE,
            raw,
            len(raw),
        )
        self._xlib.XFlush(self._display)

    def _destroy_window(self, window: X11Window) -> None:
        """Destroy one window's server-side resources."""
        self._windows.pop(window._id, None)
        if self._display is None:
            return
        if not window._destroyed_by_server:
            self._xlib.XDestroyWindow(self._display, window._id)
        self._xlib.XFlush(self._display)

    def _pump(self) -> None:
        """Drain the connection, filing each event under its own window."""
        if self._display is None:
            return

        xlib = self._xlib
        event = _xlib.XEvent()
        while xlib.XPending(self._display) > 0:
            xlib.XNextEvent(self._display, event)
            self._dispatch(event)

    def _dispatch(self, event) -> None:
        """Translate one XEvent and queue it on the window it belongs to.

        Anything not recognised is dropped: raw X events must never reach the
        engine, and an unhandled type has no platform-neutral meaning.
        """
        event_type = event.type

        if event_type == _xlib.CLIENT_MESSAGE:
            window = self._windows.get(event.xclient.window)
            if window is None:
                return
            if (
                event.xclient.message_type == self._wm_protocols
                and event.xclient.data.l[0] == self._wm_delete_window
            ):
                window._pending.append(WindowCloseRequested())

        elif event_type == _xlib.CONFIGURE_NOTIFY:
            window = self._windows.get(event.xconfigure.window)
            if window is None:
                return
            size = (event.xconfigure.width, event.xconfigure.height)
            # ConfigureNotify also fires for moves and restacks, so only
            # report an actual change in size.
            if size != window._size:
                window._size = size
                window._pending.append(WindowResized(size[0], size[1]))

        elif event_type == _xlib.DESTROY_NOTIFY:
            window = self._windows.get(event.xdestroywindow.window)
            if window is not None:
                # The server already destroyed it; close() must not ask again.
                window._destroyed_by_server = True
