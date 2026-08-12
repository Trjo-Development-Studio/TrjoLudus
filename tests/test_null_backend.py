"""Tests for the headless null backend.

Every test here runs without a display. The suite as a whole is also run with
the graphical environment variables unset, which is what actually proves the
backend is headless -- see ``test_requires_no_graphical_environment``.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

import trjoludus
from trjoludus.events import Event, WindowCloseRequested, WindowResized
from trjoludus.platform.base import PlatformBackend, PlatformWindow
from trjoludus.platform.null import BACKEND_NAME, NullBackend, NullWindow

GRAPHICAL_ENV_VARS = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE",
)

#: Directory containing the ``trjoludus`` package, so subprocesses can import
#: it regardless of the working directory the suite was launched from.
PACKAGE_PARENT = str(Path(trjoludus.__file__).parent.parent)


def run_python(script: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run ``script`` in a clean subprocess with ``trjoludus`` importable."""
    env = dict(env)
    env["PYTHONPATH"] = PACKAGE_PARENT
    return subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestBackend(unittest.TestCase):
    def test_can_be_constructed(self):
        self.assertIsInstance(NullBackend(), NullBackend)

    def test_satisfies_the_backend_contract(self):
        """Construction succeeding at all proves no abstract method is missing."""
        self.assertIsInstance(NullBackend(), PlatformBackend)

    def test_name_is_null(self):
        self.assertEqual(NullBackend().name, "null")
        self.assertEqual(NullBackend().name, BACKEND_NAME)

    def test_starts_with_no_windows(self):
        self.assertEqual(NullBackend().windows, ())

    def test_starts_not_shut_down(self):
        self.assertFalse(NullBackend().is_shut_down)


class TestWindowCreation(unittest.TestCase):
    def setUp(self):
        self.backend = NullBackend()

    def test_creates_a_window(self):
        window = self.backend.create_window("Title", 800, 600)
        self.assertIsInstance(window, NullWindow)

    def test_window_satisfies_the_window_contract(self):
        window = self.backend.create_window("Title", 800, 600)
        self.assertIsInstance(window, PlatformWindow)

    def test_initial_size_matches_request(self):
        window = self.backend.create_window("Title", 1280, 720)
        self.assertEqual(window.size, (1280, 720))

    def test_initial_title_matches_request(self):
        window = self.backend.create_window("My Game", 320, 240)
        self.assertEqual(window.title, "My Game")

    def test_window_starts_open(self):
        self.assertFalse(self.backend.create_window("T", 320, 240).is_closed)

    def test_window_starts_with_no_events(self):
        window = self.backend.create_window("T", 320, 240)
        self.assertEqual(list(window.poll_events()), [])

    def test_backend_tracks_created_windows(self):
        first = self.backend.create_window("A", 100, 100)
        second = self.backend.create_window("B", 200, 200)
        self.assertEqual(self.backend.windows, (first, second))

    def test_multiple_windows_are_independent(self):
        first = self.backend.create_window("A", 100, 100)
        second = self.backend.create_window("B", 200, 200)

        self.assertIsNot(first, second)
        self.assertEqual(first.size, (100, 100))
        self.assertEqual(second.size, (200, 200))

        first.title = "renamed"
        self.assertEqual(second.title, "B")

        first.simulate_event(WindowCloseRequested())
        self.assertEqual(list(second.poll_events()), [])

        first.close()
        self.assertFalse(second.is_closed)


class TestTitle(unittest.TestCase):
    def setUp(self):
        self.window = NullBackend().create_window("before", 320, 240)

    def test_is_readable(self):
        self.assertEqual(self.window.title, "before")

    def test_is_writable(self):
        self.window.title = "after"
        self.assertEqual(self.window.title, "after")

    def test_accepts_non_ascii(self):
        """Titles reach UTF-8 on X11 and UTF-16 on Win32; neither is ASCII."""
        self.window.title = "Apex Horizon — åæø"
        self.assertEqual(self.window.title, "Apex Horizon — åæø")


class TestEvents(unittest.TestCase):
    def setUp(self):
        self.window = NullBackend().create_window("T", 640, 480)

    def test_initially_returns_no_events(self):
        self.assertEqual(list(self.window.poll_events()), [])

    def test_returns_a_simulated_event(self):
        self.window.simulate_event(WindowCloseRequested())
        self.assertEqual(list(self.window.poll_events()), [WindowCloseRequested()])

    def test_returns_events_in_order(self):
        self.window.simulate_event(WindowResized(800, 600))
        self.window.simulate_event(WindowCloseRequested())
        self.assertEqual(
            list(self.window.poll_events()),
            [WindowResized(800, 600), WindowCloseRequested()],
        )

    def test_drains_the_queue(self):
        self.window.simulate_event(WindowResized(800, 600))
        self.assertEqual(len(list(self.window.poll_events())), 1)
        self.assertEqual(list(self.window.poll_events()), [])

    def test_repeated_polling_stays_empty(self):
        for _ in range(3):
            self.assertEqual(list(self.window.poll_events()), [])

    def test_events_queued_between_polls_are_delivered(self):
        self.window.simulate_event(WindowResized(1, 1))
        self.window.poll_events()

        self.window.simulate_event(WindowResized(2, 2))
        self.assertEqual(list(self.window.poll_events()), [WindowResized(2, 2)])

    def test_only_returns_events(self):
        self.window.simulate_event(WindowResized(320, 240))
        for event in self.window.poll_events():
            self.assertIsInstance(event, Event)

    def test_simulate_event_does_not_change_window_size(self):
        """Documented limitation: the null window does not model resizing."""
        self.window.simulate_event(WindowResized(1920, 1080))
        self.window.poll_events()
        self.assertEqual(self.window.size, (640, 480))

    def test_injection_is_absent_from_the_contract(self):
        """Event injection must not leak into the platform-window API."""
        self.assertFalse(hasattr(PlatformWindow, "simulate_event"))


class TestClose(unittest.TestCase):
    def setUp(self):
        self.window = NullBackend().create_window("T", 320, 240)

    def test_marks_the_window_closed(self):
        self.window.close()
        self.assertTrue(self.window.is_closed)

    def test_is_idempotent(self):
        self.window.close()
        self.window.close()
        self.window.close()
        self.assertTrue(self.window.is_closed)

    def test_releases_pending_events(self):
        self.window.simulate_event(WindowCloseRequested())
        self.window.close()
        self.assertEqual(list(self.window.poll_events()), [])

    def test_polling_after_close_is_safe(self):
        self.window.close()
        self.assertEqual(list(self.window.poll_events()), [])

    def test_events_simulated_after_close_are_discarded(self):
        """A destroyed OS window delivers nothing further."""
        self.window.close()
        self.window.simulate_event(WindowCloseRequested())
        self.assertEqual(list(self.window.poll_events()), [])

    def test_title_remains_readable_after_close(self):
        self.window.close()
        self.assertEqual(self.window.title, "T")

    def test_size_remains_readable_after_close(self):
        self.window.close()
        self.assertEqual(self.window.size, (320, 240))


class TestShutdown(unittest.TestCase):
    def setUp(self):
        self.backend = NullBackend()

    def test_marks_the_backend_shut_down(self):
        self.backend.shutdown()
        self.assertTrue(self.backend.is_shut_down)

    def test_is_idempotent(self):
        self.backend.shutdown()
        self.backend.shutdown()
        self.backend.shutdown()
        self.assertTrue(self.backend.is_shut_down)

    def test_releases_window_references(self):
        self.backend.create_window("A", 100, 100)
        self.backend.create_window("B", 200, 200)
        self.backend.shutdown()
        self.assertEqual(self.backend.windows, ())

    def test_shutdown_with_no_windows_is_safe(self):
        self.backend.shutdown()
        self.assertEqual(self.backend.windows, ())

    def test_does_not_close_windows_itself(self):
        """Per the contract, windows are already closed before shutdown runs."""
        window = self.backend.create_window("A", 100, 100)
        self.backend.shutdown()
        self.assertFalse(window.is_closed)


class TestHeadless(unittest.TestCase):
    def test_loads_no_ctypes(self):
        """Checked in a subprocess; sys.modules here depends on test order."""
        result = run_python(
            "import sys\n"
            "import trjoludus.platform.null\n"
            "loaded = [m for m in sys.modules if m.split('.')[0] == 'ctypes']\n"
            "assert not loaded, loaded\n"
            "print('ok')\n",
            os.environ,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_requires_no_graphical_environment(self):
        """Create and drive a window in a subprocess with no display at all."""
        env = {k: v for k, v in os.environ.items() if k not in GRAPHICAL_ENV_VARS}
        result = run_python(
            "import os\n"
            f"assert not any(v in os.environ for v in {GRAPHICAL_ENV_VARS!r})\n"
            "from trjoludus.platform.null import NullBackend\n"
            "from trjoludus.events import WindowCloseRequested\n"
            "backend = NullBackend()\n"
            "window = backend.create_window('headless', 640, 480)\n"
            "window.simulate_event(WindowCloseRequested())\n"
            "events = list(window.poll_events())\n"
            "window.close()\n"
            "backend.shutdown()\n"
            "assert events == [WindowCloseRequested()], events\n"
            "assert window.is_closed\n"
            "print('ok')\n",
            env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_works_with_blank_graphical_environment(self):
        """Empty strings, rather than unset, are a different failure mode."""
        env = dict(os.environ)
        env.update(dict.fromkeys(GRAPHICAL_ENV_VARS, ""))
        result = run_python(
            "from trjoludus.platform.null import NullBackend\n"
            "w = NullBackend().create_window('t', 1, 1)\n"
            "assert w.size == (1, 1)\n"
            "print('ok')\n",
            env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
