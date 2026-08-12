"""Tests for the platform-neutral event types."""

import dataclasses
import unittest

import trjoludus
from trjoludus.events import Event, WindowCloseRequested, WindowResized


class TestEventBase(unittest.TestCase):
    def test_events_derive_from_event(self):
        self.assertIsInstance(WindowCloseRequested(), Event)
        self.assertIsInstance(WindowResized(640, 480), Event)

    def test_events_are_dataclasses(self):
        for cls in (Event, WindowCloseRequested, WindowResized):
            self.assertTrue(dataclasses.is_dataclass(cls), cls)

    def test_events_are_exposed_publicly(self):
        self.assertIs(trjoludus.WindowCloseRequested, WindowCloseRequested)
        self.assertIs(trjoludus.WindowResized, WindowResized)
        self.assertIs(trjoludus.Event, Event)


class TestWindowCloseRequested(unittest.TestCase):
    def test_is_frozen(self):
        event = WindowCloseRequested()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            event.anything = 1  # type: ignore[attr-defined]

    def test_instances_are_equal(self):
        self.assertEqual(WindowCloseRequested(), WindowCloseRequested())

    def test_takes_no_arguments(self):
        with self.assertRaises(TypeError):
            WindowCloseRequested(1)  # type: ignore[call-arg]


class TestWindowResized(unittest.TestCase):
    def test_carries_width_and_height(self):
        event = WindowResized(1280, 720)
        self.assertEqual(event.width, 1280)
        self.assertEqual(event.height, 720)

    def test_is_frozen(self):
        event = WindowResized(800, 600)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            event.width = 1

    def test_equality_is_by_value(self):
        self.assertEqual(WindowResized(800, 600), WindowResized(800, 600))
        self.assertNotEqual(WindowResized(800, 600), WindowResized(640, 480))

    def test_requires_both_fields(self):
        with self.assertRaises(TypeError):
            WindowResized(800)  # type: ignore[call-arg]

    def test_repr_shows_values(self):
        self.assertIn("800", repr(WindowResized(800, 600)))
        self.assertIn("600", repr(WindowResized(800, 600)))


class TestEventTypesAreDistinct(unittest.TestCase):
    def test_different_event_types_are_not_equal(self):
        """A close request must never compare equal to a resize."""
        self.assertNotEqual(WindowCloseRequested(), Event())
        self.assertNotEqual(WindowResized(0, 0), Event())

    def test_isinstance_discriminates(self):
        """The dispatch pattern games are expected to use must work."""
        events = [WindowCloseRequested(), WindowResized(320, 240)]
        closes = [e for e in events if isinstance(e, WindowCloseRequested)]
        resizes = [e for e in events if isinstance(e, WindowResized)]
        self.assertEqual(len(closes), 1)
        self.assertEqual(len(resizes), 1)


if __name__ == "__main__":
    unittest.main()
