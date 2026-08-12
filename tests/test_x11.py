"""Tests for the X11 backend.

Split in two, because most of this cannot be checked without a display:

* :class:`TestDeclarations` and friends run anywhere. They check the ctypes
  declarations, constants and error paths -- the things that cause silent
  memory corruption when they are wrong.
* :class:`TestX11Integration` and below run only when a real X server is
  reachable, and are skipped otherwise so the headless suite stays green.

Nothing here fakes Xlib. A mocked X server would happily agree with a wrong
struct layout, which is exactly the bug class that matters here, so the
integration tests talk to the real thing or do not run at all.
"""

import ctypes
import os
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from trjoludus.app import Application
from trjoludus.errors import PlatformError
from trjoludus.events import WindowCloseRequested, WindowResized
from trjoludus.game import Game
from trjoludus.platform.base import PlatformBackend, PlatformWindow
from trjoludus.platform.linux import _xlib
from trjoludus.platform.linux.x11 import (
    BACKEND_NAME,
    X11Backend,
    X11Window,
    encode_legacy_title,
    encode_utf8_title,
)

#: How long an integration test waits for the server to deliver an event.
EVENT_TIMEOUT = 5.0


def x11_available() -> bool:
    """Whether a usable X display can actually be opened."""
    if not os.environ.get("DISPLAY"):
        return False
    try:
        xlib = _xlib.load_xlib()
    except PlatformError:
        return False
    display = xlib.XOpenDisplay(None)
    if not display:
        return False
    xlib.XCloseDisplay(display)
    return True


X11_AVAILABLE = x11_available()
requires_x11 = unittest.skipUnless(X11_AVAILABLE, "no usable X11 display")


def wait_for_event(window, event_type, timeout=EVENT_TIMEOUT, match=None):
    """Poll until a matching event arrives, or give up.

    ``match`` matters for resizes. X is asynchronous and a window manager may
    emit ConfigureNotify events of its own -- on map, when placing the window,
    or when applying its own size constraints. Waiting for merely the first
    WindowResized therefore races the compositor, so a test that triggered a
    specific size must wait for *that* size.
    """
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        seen.extend(window.poll_events())
        for event in seen:
            if isinstance(event, event_type) and (match is None or match(event)):
                return event, seen
        time.sleep(0.01)
    return None, seen


class TestDeclarations(unittest.TestCase):
    """The ctypes declarations. Wrong values here corrupt memory silently."""

    def test_every_function_declares_argtypes_and_restype(self):
        """The hard rule from ARCHITECTURE.md, checked mechanically."""
        self.assertGreater(len(_xlib.FUNCTION_SIGNATURES), 0)
        for name, (argtypes, restype) in _xlib.FUNCTION_SIGNATURES.items():
            with self.subTest(function=name):
                self.assertIsInstance(argtypes, list, "argtypes must be a list")
                self.assertIsNotNone(restype, "restype must be explicit")

    def test_pointer_returning_functions_are_not_left_as_int(self):
        """c_int restype truncates a 64-bit Display*; that segfaults later."""
        argtypes, restype = _xlib.FUNCTION_SIGNATURES["XOpenDisplay"]
        self.assertIs(restype, _xlib.Display)
        self.assertIsNot(restype, ctypes.c_int)

    def test_xevent_is_the_full_union_size(self):
        """Xlib writes a whole XEvent; a short buffer would be overrun."""
        self.assertEqual(ctypes.sizeof(_xlib.XEvent), 192)

    def test_xevent_members_fit_inside_the_union(self):
        for name in ("XClientMessageEvent", "XConfigureEvent",
                     "XDestroyWindowEvent", "XErrorEvent"):
            with self.subTest(struct=name):
                self.assertLessEqual(
                    ctypes.sizeof(getattr(_xlib, name)),
                    ctypes.sizeof(_xlib.XEvent),
                )

    def test_client_message_payload_layout(self):
        """The union is sized by its widest member, ``long l[5]``.

        The familiar "20 bytes" is only the ``char b[20]`` view; on a 64-bit
        system the union is 40 bytes, which is why the event struct is 96 and
        ``data`` starts at offset 56.
        """
        self.assertEqual(ctypes.sizeof(_xlib.XClientMessageData), 40)
        self.assertEqual(_xlib.XClientMessageData.b.size, 20)
        self.assertEqual(ctypes.sizeof(_xlib.XClientMessageEvent), 96)
        self.assertEqual(_xlib.XClientMessageEvent.data.offset, 56)

    def test_wm_delete_window_is_read_from_data_l_zero(self):
        """The protocol atom arrives in the first long of the payload."""
        event = _xlib.XEvent()
        event.xclient.data.l[0] = 12345
        self.assertEqual(event.xclient.data.l[0], 12345)

    def test_event_type_constants(self):
        self.assertEqual(_xlib.DESTROY_NOTIFY, 17)
        self.assertEqual(_xlib.CONFIGURE_NOTIFY, 22)
        self.assertEqual(_xlib.CLIENT_MESSAGE, 33)

    def test_structure_notify_mask(self):
        self.assertEqual(_xlib.STRUCTURE_NOTIFY_MASK, 1 << 17)

    def test_no_input_masks_are_declared(self):
        """Keyboard and mouse belong to Milestone 2."""
        for name in dir(_xlib):
            self.assertNotIn("KEY_PRESS", name)
            self.assertNotIn("BUTTON_PRESS", name)

    def test_xid_types_are_unsigned_long(self):
        for name in ("XID", "Window", "Atom"):
            with self.subTest(type=name):
                self.assertIs(getattr(_xlib, name), ctypes.c_ulong)


class TestTitleEncoding(unittest.TestCase):
    """Title encoding, checked without a display.

    _NET_WM_NAME is UTF8_STRING and WM_NAME is ICCCM STRING (Latin-1). They
    are different types, so they need different bytes; conflating them is what
    produced mojibake.
    """

    def test_utf8_title_is_utf8(self):
        self.assertEqual(encode_utf8_title("Hello"), b"Hello")
        self.assertEqual(encode_utf8_title("åæø"), "åæø".encode("utf-8"))

    def test_utf8_title_round_trips(self):
        title = "TrjoLudus — X11 Test ✓"
        self.assertEqual(encode_utf8_title(title).decode("utf-8"), title)

    def test_legacy_title_is_latin1_not_utf8(self):
        """The regression: an em dash must not become three Latin-1 chars."""
        title = "TrjoLudus — X11 Test"
        legacy = encode_legacy_title(title)

        self.assertNotEqual(legacy, title.encode("utf-8"))
        self.assertNotIn("â".encode("latin-1"), legacy)
        # Valid Latin-1 by construction, so decoding per spec cannot fail.
        legacy.decode("latin-1")

    def test_legacy_title_keeps_latin1_representable_characters(self):
        """Norwegian characters exist in Latin-1 and must survive intact."""
        legacy = encode_legacy_title("Apex Horizon åæø")
        self.assertEqual(legacy.decode("latin-1"), "Apex Horizon åæø")

    def test_legacy_title_replaces_unrepresentable_characters(self):
        self.assertEqual(encode_legacy_title("a — b").decode("latin-1"), "a ? b")
        self.assertEqual(encode_legacy_title("✓").decode("latin-1"), "?")

    def test_legacy_title_never_raises(self):
        """Any title at all must produce a settable WM_NAME."""
        for title in ("", "plain", "日本語", "emoji 🎮", "mixed åæø — ✓"):
            with self.subTest(title=title):
                self.assertIsInstance(encode_legacy_title(title), bytes)

    def test_ascii_titles_are_identical_in_both_properties(self):
        self.assertEqual(encode_utf8_title("Pong"), encode_legacy_title("Pong"))

    def test_legacy_encoding_is_lossy_where_utf8_is_not(self):
        title = "TrjoLudus — X11 Test"
        self.assertEqual(encode_utf8_title(title).decode("utf-8"), title)
        self.assertNotEqual(encode_legacy_title(title).decode("latin-1"), title)


class TestLibraryLoading(unittest.TestCase):
    def test_backend_name_constant(self):
        self.assertEqual(BACKEND_NAME, "x11")

    def test_library_name_is_the_soname(self):
        self.assertEqual(_xlib.LIBRARY_NAME, "libX11.so.6")

    def test_missing_library_raises_platform_error(self):
        saved = _xlib._library
        _xlib._library = None
        try:
            with mock.patch("ctypes.CDLL", side_effect=OSError("not found")):
                with self.assertRaises(PlatformError) as caught:
                    _xlib.load_xlib()
            self.assertIn("libX11", str(caught.exception))
        finally:
            _xlib._library = saved

    def test_load_failure_is_a_trjoludus_error(self):
        self.assertTrue(issubclass(PlatformError, Exception))

    @unittest.skipUnless(_xlib.ctypes.util.find_library("X11"), "libX11 absent")
    def test_loaded_library_has_every_signature_applied(self):
        """Loading must set argtypes/restype on the real function objects."""
        library = _xlib.load_xlib()
        for name, (argtypes, restype) in _xlib.FUNCTION_SIGNATURES.items():
            with self.subTest(function=name):
                function = getattr(library, name)
                self.assertEqual(list(function.argtypes), argtypes)
                self.assertIs(function.restype, restype)

    @unittest.skipUnless(_xlib.ctypes.util.find_library("X11"), "libX11 absent")
    def test_loading_is_cached(self):
        self.assertIs(_xlib.load_xlib(), _xlib.load_xlib())

    @unittest.skipUnless(_xlib.ctypes.util.find_library("X11"), "libX11 absent")
    def test_loading_does_not_require_a_display(self):
        env = dict(os.environ)
        env.pop("DISPLAY", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNotNone(_xlib.load_xlib())


class TestContractConformance(unittest.TestCase):
    """Checkable without a display: the classes satisfy the contracts."""

    def test_backend_implements_the_contract(self):
        self.assertTrue(issubclass(X11Backend, PlatformBackend))

    def test_window_implements_the_contract(self):
        self.assertTrue(issubclass(X11Window, PlatformWindow))

    def test_backend_declares_no_abstract_methods(self):
        self.assertEqual(X11Backend.__abstractmethods__, frozenset())

    def test_window_declares_no_abstract_methods(self):
        self.assertEqual(X11Window.__abstractmethods__, frozenset())

    def test_window_has_no_event_injection(self):
        """simulate_event belongs to the null backend, not a real one."""
        self.assertFalse(hasattr(X11Window, "simulate_event"))


class TestErrorHandlerLifetime(unittest.TestCase):
    """Xlib holds raw pointers to these; Python must keep them alive."""

    def test_handlers_are_referenced_at_module_level(self):
        from trjoludus.platform.linux import x11

        if X11_AVAILABLE:
            X11Backend().shutdown()  # forces installation
            self.assertIsNotNone(x11._io_error_handler_ref)
            self.assertIsNotNone(x11._error_handler_ref)
        self.assertIn("_io_error_handler_ref", vars(x11))
        self.assertIn("_error_handler_ref", vars(x11))


@requires_x11
class TestX11Integration(unittest.TestCase):
    """Real windows on a real server."""

    def setUp(self):
        self.backend = X11Backend()
        self.addCleanup(self.backend.shutdown)

    def test_backend_name(self):
        self.assertEqual(self.backend.name, "x11")

    def test_creates_a_real_window(self):
        window = self.backend.create_window("test", 320, 240)
        self.assertIsInstance(window, X11Window)
        self.assertNotEqual(window.window_id, 0)

    def test_client_area_matches_the_request(self):
        window = self.backend.create_window("test", 400, 300)
        self.assertEqual(window.size, (400, 300))

    def test_title_is_readable(self):
        window = self.backend.create_window("Hello", 200, 150)
        self.assertEqual(window.title, "Hello")

    def test_title_is_writable(self):
        window = self.backend.create_window("before", 200, 150)
        window.title = "after"
        self.assertEqual(window.title, "after")

    def test_title_accepts_non_ascii(self):
        """UTF-8 is why _NET_WM_NAME is set, not just XStoreName."""
        window = self.backend.create_window("Apex Horizon — åæø ✓", 200, 150)
        self.assertEqual(window.title, "Apex Horizon — åæø ✓")
        window.title = "renamed ø"
        self.assertEqual(window.title, "renamed ø")

    def test_poll_events_never_blocks(self):
        window = self.backend.create_window("test", 200, 150)
        started = time.monotonic()
        for _ in range(5):
            list(window.poll_events())
        self.assertLess(time.monotonic() - started, 2.0)

    def test_poll_events_returns_platform_neutral_events_only(self):
        window = self.backend.create_window("test", 200, 150)
        for _ in range(3):
            for event in window.poll_events():
                self.assertNotIsInstance(event, _xlib.XEvent)

    def test_close_is_idempotent(self):
        window = self.backend.create_window("test", 200, 150)
        window.close()
        window.close()
        self.assertTrue(window.is_closed)

    def test_shutdown_is_idempotent(self):
        backend = X11Backend()
        backend.shutdown()
        backend.shutdown()
        self.assertTrue(backend.is_shut_down)

    def test_shutdown_closes_remaining_windows(self):
        backend = X11Backend()
        window = backend.create_window("test", 200, 150)
        backend.shutdown()
        self.assertTrue(window.is_closed)

    def test_create_window_after_shutdown_raises(self):
        backend = X11Backend()
        backend.shutdown()
        with self.assertRaises(PlatformError):
            backend.create_window("test", 200, 150)

    def test_polling_a_closed_window_is_safe(self):
        window = self.backend.create_window("test", 200, 150)
        window.close()
        self.assertEqual(list(window.poll_events()), [])


@requires_x11
class TestCloseRequest(unittest.TestCase):
    """WM_DELETE_WINDOW is the whole reason the window survives a click."""

    def setUp(self):
        self.backend = X11Backend()
        self.addCleanup(self.backend.shutdown)

    def _send_delete(self, window):
        """Synthesise exactly the message a window manager sends."""
        xlib = self.backend._xlib
        event = _xlib.XEvent()
        event.xclient.type = _xlib.CLIENT_MESSAGE
        event.xclient.window = window.window_id
        event.xclient.message_type = self.backend._wm_protocols
        event.xclient.format = _xlib.CLIENT_MESSAGE_FORMAT_LONG
        event.xclient.data.l[0] = self.backend._wm_delete_window
        xlib.XSendEvent(self.backend._display, window.window_id, False, 0, event)
        xlib.XFlush(self.backend._display)

    def test_delete_message_becomes_a_close_request(self):
        window = self.backend.create_window("close me", 200, 150)
        self._send_delete(window)
        found, seen = wait_for_event(window, WindowCloseRequested)
        self.assertIsNotNone(found, f"no close request; saw {seen}")

    def test_close_request_does_not_destroy_the_window(self):
        """Closing stays the application's decision, not the backend's."""
        window = self.backend.create_window("close me", 200, 150)
        self._send_delete(window)
        wait_for_event(window, WindowCloseRequested)
        self.assertFalse(window.is_closed)
        self.assertFalse(self.backend.is_shut_down)

    def test_close_request_is_delivered_once(self):
        window = self.backend.create_window("close me", 200, 150)
        self._send_delete(window)
        wait_for_event(window, WindowCloseRequested)
        later = [e for e in window.poll_events()
                 if isinstance(e, WindowCloseRequested)]
        self.assertEqual(later, [])

    def test_events_are_routed_to_the_right_window(self):
        first = self.backend.create_window("first", 200, 150)
        second = self.backend.create_window("second", 200, 150)
        self._send_delete(second)

        found, _ = wait_for_event(second, WindowCloseRequested)
        self.assertIsNotNone(found)
        self.assertEqual(
            [e for e in first.poll_events()
             if isinstance(e, WindowCloseRequested)],
            [],
        )


@requires_x11
@unittest.skipUnless(shutil.which("xprop"), "xprop not installed")
class TestTitlePropertiesOnServer(unittest.TestCase):
    """Read the properties back off the server with an independent tool.

    Each property is checked on its own. A correct _NET_WM_NAME says nothing
    about WM_NAME -- they have different types, and it was WM_NAME that was
    wrong.
    """

    NON_ASCII_TITLE = "TrjoLudus — X11 Test"

    def setUp(self):
        self.backend = X11Backend()
        self.addCleanup(self.backend.shutdown)

    def read_property(self, window, name, timeout=EVENT_TIMEOUT):
        """Read a property, waiting for the server to have processed it.

        The backend uses XFlush, which pushes the request but does not wait
        for the server to act on it, and xprop reads over its own connection.
        Reading once therefore races: the property can legitimately not exist
        yet. Retrying until it appears tests the value rather than the timing.
        """
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            result = subprocess.run(
                ["xprop", "-id", str(window.window_id), name],
                capture_output=True, text=True, timeout=30,
            )
            last = result.stdout.strip()
            if "=" in last:
                return last
            time.sleep(0.05)
        return last

    def test_net_wm_name_holds_the_exact_utf8_title(self):
        window = self.backend.create_window(self.NON_ASCII_TITLE, 200, 150)
        value = self.read_property(window, "_NET_WM_NAME")
        self.assertIn("UTF8_STRING", value)
        self.assertIn(self.NON_ASCII_TITLE, value)

    def test_wm_name_is_a_latin1_string_without_mojibake(self):
        window = self.backend.create_window(self.NON_ASCII_TITLE, 200, 150)
        value = self.read_property(window, "WM_NAME")

        self.assertIn("STRING", value)
        self.assertNotIn("UTF8_STRING", value)
        # The old bug rendered the em dash as "â" plus two more characters.
        self.assertNotIn("â", value)
        self.assertIn("TrjoLudus", value)
        self.assertIn("X11 Test", value)

    def test_latin1_representable_characters_survive_in_wm_name(self):
        window = self.backend.create_window("Apex Horizon åæø", 200, 150)
        value = self.read_property(window, "WM_NAME")
        self.assertIn("åæø", value)
        self.assertNotIn("Ã", value)  # the UTF-8-as-Latin-1 signature

    def test_retitling_updates_both_properties(self):
        window = self.backend.create_window("before", 200, 150)
        window.title = "after — renamed"

        self.assertIn("after — renamed", self.read_property(window, "_NET_WM_NAME"))
        legacy = self.read_property(window, "WM_NAME")
        self.assertIn("after", legacy)
        self.assertNotIn("â", legacy)


class TestDocumentationMatchesImplementation(unittest.TestCase):
    """Guard the specific wording that was wrong."""

    def architecture_text(self):
        root = Path(__file__).resolve().parent.parent
        return (root / "ARCHITECTURE.md").read_text(encoding="utf-8")

    def test_io_error_handling_is_not_described_as_recoverable(self):
        text = self.architecture_text()
        self.assertIn("XSetIOErrorHandler", text)
        self.assertNotIn(
            "Xlib's default I/O error handler calls `exit(1)`,\n  bypassing all "
            "Python cleanup. It must be installed before opening the display.",
            text,
            "the superseded, inaccurate claim is back",
        )

    def test_title_encodings_are_documented(self):
        text = self.architecture_text()
        for expected in ("_NET_WM_NAME", "WM_NAME", "UTF8_STRING", "8859-1"):
            self.assertIn(expected, text)


@requires_x11
class TestResize(unittest.TestCase):
    def setUp(self):
        self.backend = X11Backend()
        self.addCleanup(self.backend.shutdown)

    def _resize(self, window, width, height):
        self.backend._xlib.XResizeWindow(
            self.backend._display, window.window_id, width, height)
        self.backend._xlib.XFlush(self.backend._display)

    def test_resize_produces_a_window_resized_event(self):
        window = self.backend.create_window("resize me", 400, 300)
        self._resize(window, 640, 480)

        found, seen = wait_for_event(
            window, WindowResized,
            match=lambda e: (e.width, e.height) == (640, 480))
        self.assertIsNotNone(found, f"no 640x480 resize event; saw {seen}")
        self.assertEqual((found.width, found.height), (640, 480))

    def test_size_tracks_the_resize(self):
        window = self.backend.create_window("resize me", 400, 300)
        self._resize(window, 512, 384)

        found, seen = wait_for_event(
            window, WindowResized,
            match=lambda e: (e.width, e.height) == (512, 384))
        self.assertIsNotNone(found, f"no 512x384 resize event; saw {seen}")
        self.assertEqual(window.size, (512, 384))


@requires_x11
class TestApplicationOnX11(unittest.TestCase):
    """The full stack: Game -> Application -> X11Backend -> Xlib."""

    def test_application_runs_on_a_real_window(self):
        class Counting(Game):
            def __init__(self):
                self.frames = 0

            def on_update(self, dt):
                self.frames += 1
                if self.frames >= 3:
                    self.quit()

        game = Counting()
        backend = X11Backend()
        Application(game, title="x11 lifecycle", size=(320, 240),
                    max_fps=None, backend=backend).run()

        self.assertEqual(game.frames, 3)
        self.assertTrue(backend.is_shut_down)

    def test_game_quits_on_a_close_request(self):
        """The documented pattern, driven by a real X message."""
        backend = X11Backend()
        state = {"window": None}

        class Closing(Game):
            def __init__(self):
                self.frames = 0
                self.closed = False

            def on_event(self, event):
                if isinstance(event, WindowCloseRequested):
                    self.closed = True
                    self.quit()

            def on_update(self, dt):
                self.frames += 1
                if self.frames == 2:
                    window = backend.windows[0]
                    state["window"] = window
                    xlib = backend._xlib
                    event = _xlib.XEvent()
                    event.xclient.type = _xlib.CLIENT_MESSAGE
                    event.xclient.window = window.window_id
                    event.xclient.message_type = backend._wm_protocols
                    event.xclient.format = _xlib.CLIENT_MESSAGE_FORMAT_LONG
                    event.xclient.data.l[0] = backend._wm_delete_window
                    xlib.XSendEvent(
                        backend._display, window.window_id, False, 0, event)
                    xlib.XFlush(backend._display)
                if self.frames > 300:
                    self.quit()

        game = Closing()
        Application(game, title="x11 close", size=(320, 240),
                    max_fps=None, backend=backend).run()

        self.assertTrue(game.closed, "close request never reached the game")
        self.assertTrue(state["window"].is_closed)
        self.assertTrue(backend.is_shut_down)


if __name__ == "__main__":
    unittest.main()
