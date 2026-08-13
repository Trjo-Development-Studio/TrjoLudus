"""Tests for keyboard.wait(input.key).

All headless. Key presses are injected as platform-neutral events through the
null backend, so waiting can be tested exactly rather than by asking a human to
press keys. The X11 side -- turning a real keycode into a canonical name -- is
tested separately in test_x11.py.

Each test drives a real Application, because that is what wait() pumps. There
is no second loop to fake.
"""

import unittest

import trjoludus as tl
from trjoludus.errors import TrjoLudusError
from trjoludus.events import KEY_NAMES, KeyPressed, WindowResized
from trjoludus.platform.null import NullBackend


class ScriptedBackend(NullBackend):
    """Null backend that feeds a window a scripted sequence of events.

    Each entry is ``(frame, event)``: the event is queued the first time
    ``poll_events`` runs on or after that many polls, which lets a test place
    an event at a chosen point in a wait without any timing assumptions.
    """

    def __init__(self, script=()):
        super().__init__()
        self.script = list(script)
        self.polls = 0
        self.window = None

    def create_window(self, title, width, height):
        window = super().create_window(title, width, height)
        self.window = window
        backend = self

        original_poll = window.poll_events

        def poll_events():
            backend.polls += 1
            for when, event in list(backend.script):
                if backend.polls >= when:
                    window.simulate_event(event)
                    backend.script.remove((when, event))
            return original_poll()

        window.poll_events = poll_events
        return window


def run_game(game, backend=None, size=(8, 8)):
    backend = backend or ScriptedBackend()
    tl.Application(game, size=size, max_fps=None, backend=backend).run()
    return backend


class TestKeyNames(unittest.TestCase):
    def test_the_required_keys_are_all_named(self):
        for name in ("W", "A", "S", "D", "ESCAPE", "ENTER", "SPACE",
                     "UP", "DOWN", "LEFT", "RIGHT"):
            with self.subTest(key=name):
                self.assertIn(name, KEY_NAMES)

    def test_names_are_uppercase(self):
        for name in KEY_NAMES:
            self.assertEqual(name, name.upper())

    def test_input_key_is_the_key_value(self):
        self.assertIs(tl.input.key, tl.key)

    def test_input_offers_a_slot_for_each_kind_of_input(self):
        self.assertIs(tl.input.key, tl.key)
        self.assertIsNotNone(tl.input.mouse)
        self.assertIsNot(tl.input.key, tl.input.mouse)


class TestKeyValue(unittest.TestCase):
    """key is a live value, so it has to read like the key name."""

    def setUp(self):
        self.addCleanup(tl.key._set, None)

    def test_compares_equal_to_the_key_name(self):
        tl.key._set("W")
        self.assertTrue(tl.key == "W")
        self.assertFalse(tl.key == "A")

    def test_prints_as_the_key_name(self):
        tl.key._set("ESCAPE")
        self.assertEqual(str(tl.key), "ESCAPE")

    def test_formats_as_the_key_name(self):
        tl.key._set("W")
        self.assertEqual(f"{tl.key}", "W")

    def test_works_with_in(self):
        tl.key._set("A")
        self.assertIn(tl.key, ("W", "A", "S", "D"))
        self.assertIn(tl.key, {"W", "A"})

    def test_value_gives_a_plain_string_copy(self):
        tl.key._set("W")
        copied = tl.key.value
        tl.key._set("A")
        self.assertEqual(copied, "W")
        self.assertIsInstance(copied, str)

    def test_starts_empty(self):
        tl.key._set(None)
        self.assertIsNone(tl.key.value)
        self.assertFalse(tl.key)
        self.assertEqual(str(tl.key), "")

    def test_updating_replaces_the_previous_key(self):
        tl.key._set("W")
        tl.key._set("A")
        self.assertTrue(tl.key == "A")
        self.assertFalse(tl.key == "W")


class TestWaitOutsideAGame(unittest.TestCase):
    def test_waiting_with_no_game_running_explains_itself(self):
        with self.assertRaises(TrjoLudusError) as caught:
            tl.keyboard.wait(tl.input.key)
        self.assertIn("running", str(caught.exception))

    def test_a_bad_argument_is_rejected(self):
        with self.assertRaises(TrjoLudusError):
            tl.keyboard.wait("W")

    def test_the_error_names_the_right_argument(self):
        with self.assertRaises(TrjoLudusError) as caught:
            tl.keyboard.wait("W")
        self.assertIn("input.key", str(caught.exception))


class TestWaitReturnsKeys(unittest.TestCase):
    def test_returns_the_key_that_was_pressed(self):
        class G(tl.Game):
            pressed = None

            def on_update(self, dt):
                tl.keyboard.wait(tl.input.key)
                self.pressed = tl.key.value
                self.quit()

        game = G()
        run_game(game, ScriptedBackend([(2, KeyPressed("W"))]))
        self.assertEqual(game.pressed, "W")

    def test_returns_each_of_the_required_keys(self):
        for name in ("W", "A", "S", "D", "ESCAPE", "ENTER", "SPACE",
                     "UP", "DOWN", "LEFT", "RIGHT"):
            with self.subTest(key=name):
                class G(tl.Game):
                    pressed = None

                    def on_update(self, dt):
                        tl.keyboard.wait(tl.input.key)
                        self.pressed = tl.key.value
                        self.quit()

                game = G()
                run_game(game, ScriptedBackend([(2, KeyPressed(name))]))
                self.assertEqual(game.pressed, name)

    def test_consecutive_different_keys_arrive_in_order(self):
        class G(tl.Game):
            def __init__(self):
                self.pressed = []

            def on_update(self, dt):
                tl.keyboard.wait(tl.input.key)
                self.pressed.append(tl.key.value)
                tl.keyboard.wait(tl.input.key)
                self.pressed.append(tl.key.value)
                self.quit()

        game = G()
        run_game(game, ScriptedBackend(
            [(2, KeyPressed("W")), (2, KeyPressed("A"))]))
        self.assertEqual(game.pressed, ["W", "A"])

    def test_the_same_key_twice_is_reported_twice(self):
        """Two presses are two events, even of the same key."""

        class G(tl.Game):
            def __init__(self):
                self.pressed = []

            def on_update(self, dt):
                tl.keyboard.wait(tl.input.key)
                self.pressed.append(tl.key.value)
                tl.keyboard.wait(tl.input.key)
                self.pressed.append(tl.key.value)
                self.quit()

        game = G()
        run_game(game, ScriptedBackend(
            [(2, KeyPressed("W")), (3, KeyPressed("W"))]))
        self.assertEqual(game.pressed, ["W", "W"])


class TestWaitWaitsForNewInput(unittest.TestCase):
    """The behaviour the whole design turns on."""

    def test_a_second_wait_does_not_repeat_the_first_key(self):
        """One press answers exactly one wait."""

        class G(tl.Game):
            def __init__(self):
                self.first = None
                self.second = "not set"

            def on_update(self, dt):
                tl.keyboard.wait(tl.input.key)
                self.first = tl.key.value
                # Only one key was ever pressed, so this must not return "W"
                # again. It ends when the close request makes the game quit.
                tl.keyboard.wait(tl.input.key)
                self.second = tl.key.value
                self.quit()

            def on_event(self, event):
                if isinstance(event, tl.WindowCloseRequested):
                    self.quit()

        game = G()
        run_game(game, ScriptedBackend([
            (2, KeyPressed("W")),
            (6, tl.WindowCloseRequested()),
        ]))
        self.assertEqual(game.first, "W")
        self.assertIsNone(game.second, "the same press was handed out twice")

    def test_a_key_pressed_before_the_wait_is_still_delivered(self):
        """Queued input is not thrown away; it is answered in order."""

        class G(tl.Game):
            pressed = None
            frames = 0

            def on_update(self, dt):
                self.frames += 1
                if self.frames < 3:
                    return          # let the key arrive first
                tl.keyboard.wait(tl.input.key)
                self.pressed = tl.key.value
                self.quit()

        game = G()
        run_game(game, ScriptedBackend([(1, KeyPressed("A"))]))
        self.assertEqual(game.pressed, "A")


class TestWaitAndOtherEvents(unittest.TestCase):
    def test_unrelated_events_still_reach_the_game_while_waiting(self):
        class G(tl.Game):
            def __init__(self):
                self.seen = []
                self.pressed = None

            def on_event(self, event):
                self.seen.append(event)

            def on_update(self, dt):
                tl.keyboard.wait(tl.input.key)
                self.pressed = tl.key.value
                self.quit()

        game = G()
        run_game(game, ScriptedBackend([
            (2, WindowResized(20, 10)),
            (4, KeyPressed("S")),
        ]))
        self.assertEqual(game.pressed, "S")
        self.assertIn(WindowResized(20, 10), game.seen)

    def test_key_presses_do_not_also_go_to_on_event(self):
        """One press belongs to one place, so it cannot be handled twice."""

        class G(tl.Game):
            def __init__(self):
                self.seen = []

            def on_event(self, event):
                self.seen.append(event)

            def on_update(self, dt):
                tl.keyboard.wait(tl.input.key)
                self.quit()

        game = G()
        run_game(game, ScriptedBackend([(2, KeyPressed("W"))]))
        self.assertEqual([e for e in game.seen if isinstance(e, KeyPressed)], [])


class TestWaitAndShutdown(unittest.TestCase):
    def test_a_close_request_does_not_block_the_game_forever(self):
        """The wait must end, or the window could never be closed."""

        class G(tl.Game):
            pressed = "not set"

            def on_event(self, event):
                if isinstance(event, tl.WindowCloseRequested):
                    self.quit()

            def on_update(self, dt):
                tl.keyboard.wait(tl.input.key)
                self.pressed = tl.key.value
                self.quit()

        game = G()
        run_game(game, ScriptedBackend([(3, tl.WindowCloseRequested())]))
        self.assertIsNone(game.pressed)

    def test_quitting_from_on_start_never_enters_the_wait(self):
        class G(tl.Game):
            reached_update = False

            def on_start(self):
                self.quit()

            def on_update(self, dt):
                self.reached_update = True

        game = G()
        run_game(game)
        self.assertFalse(game.reached_update)

    def test_the_application_still_shuts_down_cleanly_after_a_wait(self):
        class G(tl.Game):
            stopped = False

            def on_update(self, dt):
                tl.keyboard.wait(tl.input.key)
                self.quit()

            def on_stop(self):
                self.stopped = True

        game = G()
        backend = run_game(game, ScriptedBackend([(2, KeyPressed("W"))]))
        self.assertTrue(game.stopped)
        self.assertTrue(backend.is_shut_down)

    def test_key_is_cleared_when_a_run_finishes(self):
        """A second game must not start out holding the first one's press."""

        class G(tl.Game):
            def on_update(self, dt):
                tl.keyboard.wait(tl.input.key)
                self.quit()

        run_game(G(), ScriptedBackend([(2, KeyPressed("W"))]))
        self.assertIsNone(tl.key.value)

    def test_queued_keys_do_not_survive_into_the_next_run(self):
        """A new game must not inherit the last one's unread input."""

        class Quitter(tl.Game):
            def on_update(self, dt):
                self.quit()

        run_game(Quitter(), ScriptedBackend([(1, KeyPressed("W"))]))

        class G(tl.Game):
            pressed = "not set"

            def on_event(self, event):
                if isinstance(event, tl.WindowCloseRequested):
                    self.quit()

            def on_update(self, dt):
                tl.keyboard.wait(tl.input.key)
                self.pressed = tl.key.value
                self.quit()

        game = G()
        run_game(game, ScriptedBackend([(3, tl.WindowCloseRequested())]))
        self.assertIsNone(game.pressed, "input leaked from the previous run")


if __name__ == "__main__":
    unittest.main()
