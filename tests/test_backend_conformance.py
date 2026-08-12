"""One contract, asserted against every backend.

The point of a platform abstraction is that the layers above it cannot tell
which backend is underneath. That only holds if the same assertions pass for
all of them, so the checks live in a single mixin and each backend gets a
subclass that supplies one.

Only *externally observable contract* is asserted here. Where the platforms
genuinely differ -- whether ``shutdown()`` also closes windows, what the
backend-specific inspection properties report -- the difference is deliberate
and is documented in ARCHITECTURE.md rather than forced into uniformity.

Backends that cannot run here are skipped, never faked. A mocked window server
would agree with a wrong implementation, which is the opposite of what a
conformance suite is for.
"""

import os
import sys
import unittest

from trjoludus.errors import PlatformError
from trjoludus.events import Event
from trjoludus.platform import BACKEND_NAMES
from trjoludus.platform.base import PlatformBackend, PlatformWindow
from trjoludus.platform.null import NullBackend


def x11_available() -> bool:
    if not os.environ.get("DISPLAY"):
        return False
    try:
        from trjoludus.platform.linux import _xlib

        xlib = _xlib.load_xlib()
    except PlatformError:
        return False
    display = xlib.XOpenDisplay(None)
    if not display:
        return False
    xlib.XCloseDisplay(display)
    return True


X11_AVAILABLE = x11_available()
ON_WINDOWS = sys.platform == "win32"


class BackendContract:
    """Assertions every backend must satisfy.

    Deliberately not a TestCase, so unittest does not collect and run it on
    its own with no backend to test.
    """

    def make_backend(self) -> PlatformBackend:
        raise NotImplementedError

    def backend(self) -> PlatformBackend:
        backend = self.make_backend()
        self.addCleanup(backend.shutdown)
        return backend

    # --- identity --------------------------------------------------------

    def test_backend_satisfies_the_contract(self):
        self.assertIsInstance(self.backend(), PlatformBackend)

    def test_backend_name_is_a_known_name(self):
        name = self.backend().name
        self.assertIsInstance(name, str)
        self.assertIn(name, BACKEND_NAMES)

    # --- window creation -------------------------------------------------

    def test_creates_a_window_satisfying_the_contract(self):
        window = self.backend().create_window("test", 320, 240)
        self.assertIsInstance(window, PlatformWindow)

    def test_client_size_matches_the_request(self):
        window = self.backend().create_window("test", 400, 300)
        self.assertEqual(window.size, (400, 300))

    def test_size_is_a_pair_of_positive_ints(self):
        width, height = self.backend().create_window("test", 200, 150).size
        self.assertIsInstance(width, int)
        self.assertIsInstance(height, int)
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)

    def test_multiple_windows_are_independent(self):
        backend = self.backend()
        first = backend.create_window("first", 200, 150)
        second = backend.create_window("second", 320, 240)

        self.assertIsNot(first, second)
        self.assertEqual(first.size, (200, 150))
        self.assertEqual(second.size, (320, 240))

        first.title = "renamed"
        self.assertEqual(second.title, "second")

        first.close()
        self.assertTrue(first.is_closed)
        self.assertFalse(second.is_closed)

    # --- title -----------------------------------------------------------

    def test_title_is_readable(self):
        self.assertEqual(self.backend().create_window("Hello", 200, 150).title,
                         "Hello")

    def test_title_is_writable(self):
        window = self.backend().create_window("before", 200, 150)
        window.title = "after"
        self.assertEqual(window.title, "after")

    def test_title_accepts_non_ascii(self):
        """Every backend must carry the title the caller gave it."""
        title = "TrjoLudus — åæø ✓"
        window = self.backend().create_window(title, 200, 150)
        self.assertEqual(window.title, title)
        window.title = "Apex Horizon åæø"
        self.assertEqual(window.title, "Apex Horizon åæø")

    def test_title_is_readable_after_close(self):
        window = self.backend().create_window("kept", 200, 150)
        window.close()
        self.assertEqual(window.title, "kept")

    # --- events ----------------------------------------------------------

    def test_poll_events_returns_platform_neutral_events(self):
        window = self.backend().create_window("test", 200, 150)
        for _ in range(3):
            for event in window.poll_events():
                self.assertIsInstance(event, Event)

    def test_poll_events_is_repeatable_and_non_blocking(self):
        import time

        window = self.backend().create_window("test", 200, 150)
        started = time.monotonic()
        for _ in range(10):
            list(window.poll_events())
        self.assertLess(time.monotonic() - started, 5.0)

    def test_poll_events_returns_nothing_after_close(self):
        window = self.backend().create_window("test", 200, 150)
        window.close()
        self.assertEqual(list(window.poll_events()), [])

    # --- cleanup ---------------------------------------------------------

    def test_close_marks_the_window_closed(self):
        window = self.backend().create_window("test", 200, 150)
        self.assertFalse(window.is_closed)
        window.close()
        self.assertTrue(window.is_closed)

    def test_close_is_idempotent(self):
        window = self.backend().create_window("test", 200, 150)
        for _ in range(3):
            window.close()
        self.assertTrue(window.is_closed)

    def test_shutdown_is_idempotent(self):
        backend = self.make_backend()
        for _ in range(3):
            backend.shutdown()
        self.assertTrue(backend.is_shut_down)

    def test_shutdown_with_no_windows_is_safe(self):
        backend = self.make_backend()
        backend.shutdown()
        self.assertTrue(backend.is_shut_down)

    def test_shutdown_after_closing_windows_is_safe(self):
        backend = self.make_backend()
        window = backend.create_window("test", 200, 150)
        window.close()
        backend.shutdown()
        self.assertTrue(backend.is_shut_down)

    def test_closing_a_window_after_shutdown_is_safe(self):
        backend = self.make_backend()
        window = backend.create_window("test", 200, 150)
        backend.shutdown()
        window.close()  # must not raise, whatever shutdown already did

    def test_create_window_after_shutdown_raises(self):
        """A gone display connection or window class cannot make windows."""
        backend = self.make_backend()
        backend.shutdown()
        with self.assertRaises(PlatformError):
            backend.create_window("too late", 200, 150)


class TestNullConformance(BackendContract, unittest.TestCase):
    def make_backend(self):
        return NullBackend()


@unittest.skipUnless(X11_AVAILABLE, "no usable X11 display")
class TestX11Conformance(BackendContract, unittest.TestCase):
    def make_backend(self):
        from trjoludus.platform.linux.x11 import X11Backend

        return X11Backend()


@unittest.skipUnless(ON_WINDOWS, "not running on Windows")
class TestWin32Conformance(BackendContract, unittest.TestCase):
    def make_backend(self):
        from trjoludus.platform.windows.win32 import Win32Backend

        return Win32Backend()


class TestSuiteCoversEveryBackend(unittest.TestCase):
    """The suite is only meaningful if it actually covers what it claims."""

    def test_every_backend_name_has_a_conformance_case(self):
        covered = {
            "null": TestNullConformance,
            "x11": TestX11Conformance,
            "win32": TestWin32Conformance,
        }
        self.assertEqual(set(covered), set(BACKEND_NAMES))

    def test_null_conformance_is_never_skipped(self):
        """Whatever the machine, one backend must always be exercised."""
        self.assertFalse(getattr(TestNullConformance, "__unittest_skip__", False))


if __name__ == "__main__":
    unittest.main()
