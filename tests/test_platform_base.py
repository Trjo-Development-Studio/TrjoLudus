"""Tests for the platform backend contracts.

These test the *contract*, not any backend. The dummy classes below are test
fixtures -- the smallest thing that satisfies the interface -- and are not the
null backend, which is a separate step.
"""

import unittest
from collections.abc import Iterable

from trjoludus.events import Event, WindowCloseRequested, WindowResized
from trjoludus.platform.base import PlatformBackend, PlatformWindow


class DummyWindow(PlatformWindow):
    """Minimal complete implementation of the window contract."""

    def __init__(self, title: str = "dummy", width: int = 320, height: int = 240):
        self._title = title
        self._size = (width, height)
        self._pending: list[Event] = []
        self.presented: list[tuple[bytes, int, int]] = []
        self.close_count = 0

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value

    def poll_events(self) -> Iterable[Event]:
        events, self._pending = self._pending, []
        return events

    def present(self, pixels, width: int, height: int) -> None:
        self.presented.append((bytes(pixels), width, height))

    def close(self) -> None:
        self.close_count += 1

    def push(self, event: Event) -> None:
        """Test helper: queue an event as a backend would."""
        self._pending.append(event)


class DummyBackend(PlatformBackend):
    """Minimal complete implementation of the backend contract."""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def keeps_application_alive(self) -> bool:
        return True

    def create_window(self, title: str, width: int, height: int) -> PlatformWindow:
        return DummyWindow(title, width, height)

    def shutdown(self) -> None:
        pass


class TestContractsAreAbstract(unittest.TestCase):
    def test_platform_window_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            PlatformWindow()

    def test_platform_backend_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            PlatformBackend()

    def test_incomplete_window_is_rejected(self):
        """A backend that forgets a method must fail loudly, at construction."""

        class Incomplete(PlatformWindow):
            @property
            def size(self):
                return (0, 0)

        with self.assertRaises(TypeError):
            Incomplete()

    def test_incomplete_backend_is_rejected(self):
        class Incomplete(PlatformBackend):
            @property
            def name(self):
                return "incomplete"

        with self.assertRaises(TypeError):
            Incomplete()

    def test_complete_implementations_are_accepted(self):
        self.assertIsInstance(DummyBackend(), PlatformBackend)
        self.assertIsInstance(DummyWindow(), PlatformWindow)


class TestWindowContract(unittest.TestCase):
    def test_size_reports_width_and_height(self):
        self.assertEqual(DummyWindow(width=800, height=600).size, (800, 600))

    def test_title_is_readable_and_settable(self):
        window = DummyWindow(title="before")
        self.assertEqual(window.title, "before")
        window.title = "after"
        self.assertEqual(window.title, "after")

    def test_poll_events_returns_empty_when_idle(self):
        self.assertEqual(list(DummyWindow().poll_events()), [])

    def test_poll_events_drains_the_queue(self):
        """Events are pulled once and not redelivered."""
        window = DummyWindow()
        window.push(WindowResized(640, 480))
        window.push(WindowCloseRequested())

        first = list(window.poll_events())
        self.assertEqual(first, [WindowResized(640, 480), WindowCloseRequested()])
        self.assertEqual(list(window.poll_events()), [])

    def test_poll_events_yields_events(self):
        window = DummyWindow()
        window.push(WindowCloseRequested())
        for event in window.poll_events():
            self.assertIsInstance(event, Event)

    def test_close_is_idempotent(self):
        window = DummyWindow()
        window.close()
        window.close()
        self.assertEqual(window.close_count, 2)


class TestBackendContract(unittest.TestCase):
    def test_name_identifies_the_backend(self):
        self.assertEqual(DummyBackend().name, "dummy")

    def test_create_window_returns_a_platform_window(self):
        window = DummyBackend().create_window("Title", 1024, 768)
        self.assertIsInstance(window, PlatformWindow)
        self.assertEqual(window.title, "Title")
        self.assertEqual(window.size, (1024, 768))

    def test_shutdown_is_callable_more_than_once(self):
        backend = DummyBackend()
        backend.shutdown()
        backend.shutdown()


if __name__ == "__main__":
    unittest.main()
