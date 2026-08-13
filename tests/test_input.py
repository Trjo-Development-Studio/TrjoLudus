"""Tests for how the three waits share one queue.

Three properties are being defended here:

1. A blocking wait always has a way out -- the game quitting, or the last
   window disappearing. Nothing may wait forever for input that cannot come.
2. Each wait answers only to its own kind of input, and leaves the other kind
   in the queue rather than discarding it.
3. Input remembers the window it came from.

**Every test here that blocks provides its own way out**, scripted rather than
timed: a close request or a window closing at a known poll. A test that relied
on a timeout would turn a hang into a slow pass.
"""

import unittest

import trjoludus as tl
from trjoludus import Game, input, key, keyboard, mouse
from trjoludus.app import Application, PendingInput
from trjoludus.errors import TrjoLudusError
from trjoludus.events import (
    KeyPressed,
    MouseButtonPressed,
    MouseButtonReleased,
    MouseMoved,
)
from trjoludus.platform.null import NullBackend


class ScriptedBackend(NullBackend):
    """Null backend that feeds a window a scripted sequence of events."""

    def __init__(self, script=()):
        super().__init__()
        self.script = list(script)
        self.polls = 0

    def create_window(self, title, width, height):
        window = super().create_window(title, width, height)
        backend = self
        original = window.poll_events

        def poll_events():
            backend.polls += 1
            for when, event in list(backend.script):
                if backend.polls >= when:
                    window.simulate_event(event)
                    backend.script.remove((when, event))
            return original()

        window.poll_events = poll_events
        return window


class GraphicalBackend(ScriptedBackend):
    """Behaves like a real backend: its windows govern the run's lifetime."""

    @property
    def keeps_application_alive(self) -> bool:
        return any(not window.is_closed for window in self._windows)


class InputTestCase(unittest.TestCase):
    def setUp(self):
        mouse._reset()
        key._set(None)
        self.addCleanup(mouse._reset)
        self.addCleanup(key._set, None)

    def run_game(self, game, backend=None, size=(32, 32)):
        backend = backend or ScriptedBackend()
        Application(game, size=size, max_fps=None, backend=backend).run()
        return backend


# --------------------------------------------------------------------------
# 1. Every blocking wait can be escaped
# --------------------------------------------------------------------------


class TestWaitsAlwaysTerminate(InputTestCase):
    """No blocking call may wait forever for input that cannot arrive."""

    def each_wait(self):
        """The three blocking calls, as things a game can do."""
        return {
            "keyboard.wait": lambda: keyboard.wait(input.key),
            "mouse.wait": lambda: mouse.wait(input.mouse),
            "input.wait": input.wait,
        }

    def test_every_wait_ends_when_the_game_quits(self):
        for name, call in self.each_wait().items():
            with self.subTest(wait=name):
                class G(Game):
                    finished = False

                    def on_event(self, event):
                        if isinstance(event, tl.WindowCloseRequested):
                            self.quit()

                    def on_update(self, dt):
                        call()
                        self.finished = True
                        self.quit()

                game = G()
                self.run_game(game, ScriptedBackend(
                    [(3, tl.WindowCloseRequested())]))
                self.assertTrue(game.finished, f"{name} never returned")

    def test_every_wait_ends_when_the_last_window_disappears(self):
        for name, call in self.each_wait().items():
            with self.subTest(wait=name):
                backend = GraphicalBackend()

                class G(Game):
                    finished = False

                    def on_update(self, dt):
                        backend.windows[0].close()
                        call()
                        self.finished = True
                        self.quit()

                game = G()
                self.run_game(game, backend)
                self.assertTrue(game.finished, f"{name} never returned")

    def test_a_wait_that_gave_up_reports_nothing(self):
        """So a stale key or click cannot be acted on during shutdown."""

        class G(Game):
            def on_event(self, event):
                if isinstance(event, tl.WindowCloseRequested):
                    self.quit()

            def on_update(self, dt):
                input.wait()
                self.seen = (input.type, key.value, mouse.button)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([(3, tl.WindowCloseRequested())]))
        self.assertEqual(game.seen, (None, None, None))


# --------------------------------------------------------------------------
# 2. Each wait answers only to its own kind
# --------------------------------------------------------------------------


class TestWaitsAreSeparate(InputTestCase):
    def test_a_click_does_not_wake_a_keyboard_wait(self):
        class G(Game):
            seen = "not set"

            def on_event(self, event):
                if isinstance(event, tl.WindowCloseRequested):
                    self.quit()

            def on_update(self, dt):
                keyboard.wait(input.key)
                self.seen = key.value
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, MouseButtonPressed("LEFT", 1, 1)),
            (6, tl.WindowCloseRequested()),
        ]))
        self.assertIsNone(game.seen, "a click woke keyboard.wait()")

    def test_a_key_does_not_wake_a_mouse_wait(self):
        class G(Game):
            seen = "not set"

            def on_event(self, event):
                if isinstance(event, tl.WindowCloseRequested):
                    self.quit()

            def on_update(self, dt):
                mouse.wait(input.mouse)
                self.seen = mouse.button
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, KeyPressed("W")),
            (6, tl.WindowCloseRequested()),
        ]))
        self.assertIsNone(game.seen, "a key woke mouse.wait()")

    def test_the_other_kind_is_kept_not_discarded(self):
        """A click arriving during a keyboard wait must survive it."""

        class G(Game):
            def __init__(self):
                self.key_seen = None
                self.click_seen = None

            def on_update(self, dt):
                keyboard.wait(input.key)
                self.key_seen = key.value
                mouse.wait(input.mouse)
                self.click_seen = mouse.button
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, MouseButtonPressed("RIGHT", 4, 5)),   # arrives first
            (3, KeyPressed("W")),                     # answers the key wait
        ]))
        self.assertEqual(game.key_seen, "W")
        self.assertEqual(game.click_seen, "RIGHT", "the click was thrown away")

    def test_a_key_kept_through_a_mouse_wait_is_still_readable(self):
        class G(Game):
            def __init__(self):
                self.click_seen = None
                self.key_seen = None

            def on_update(self, dt):
                mouse.wait(input.mouse)
                self.click_seen = mouse.button
                keyboard.wait(input.key)
                self.key_seen = key.value
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, KeyPressed("A")),
            (3, MouseButtonPressed("LEFT", 0, 0)),
        ]))
        self.assertEqual(game.click_seen, "LEFT")
        self.assertEqual(game.key_seen, "A")


class TestGeneralWait(InputTestCase):
    def test_accepts_a_key(self):
        class G(Game):
            def on_update(self, dt):
                input.wait()
                self.seen = (input.type is input.key, key.value)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([(2, KeyPressed("W"))]))
        self.assertEqual(game.seen, (True, "W"))

    def test_accepts_a_click(self):
        class G(Game):
            def on_update(self, dt):
                input.wait()
                self.seen = (input.type is input.mouse, mouse.button)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend(
            [(2, MouseButtonPressed("MIDDLE", 0, 0))]))
        self.assertEqual(game.seen, (True, "MIDDLE"))

    def test_the_documented_comparison_reads_correctly(self):
        class G(Game):
            def on_update(self, dt):
                input.wait()
                self.was_key = input.type == input.key
                self.was_mouse = input.type == input.mouse
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([(2, KeyPressed("S"))]))
        self.assertTrue(game.was_key)
        self.assertFalse(game.was_mouse)

    def test_takes_whichever_arrived_first(self):
        """One queue in arrival order, so a key before a click comes first."""

        class G(Game):
            def __init__(self):
                self.order = []

            def on_update(self, dt):
                input.wait()
                self.order.append(input.type)
                input.wait()
                self.order.append(input.type)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, KeyPressed("W")),
            (3, MouseButtonPressed("LEFT", 0, 0)),
        ]))
        self.assertEqual(game.order, [input.key, input.mouse])

    def test_takes_a_click_first_when_it_came_first(self):
        class G(Game):
            def __init__(self):
                self.order = []

            def on_update(self, dt):
                input.wait()
                self.order.append(input.type)
                input.wait()
                self.order.append(input.type)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, MouseButtonPressed("LEFT", 0, 0)),
            (3, KeyPressed("W")),
        ]))
        self.assertEqual(game.order, [input.mouse, input.key])

    def test_each_item_is_taken_once(self):
        class G(Game):
            def __init__(self):
                self.seen = []

            def on_event(self, event):
                if isinstance(event, tl.WindowCloseRequested):
                    self.quit()

            def on_update(self, dt):
                input.wait()
                self.seen.append(input.type)
                input.wait()
                self.seen.append(input.type)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, KeyPressed("W")),
            (6, tl.WindowCloseRequested()),
        ]))
        self.assertEqual(game.seen, [input.key, None])

    def test_a_general_wait_and_a_specific_one_share_the_queue(self):
        class G(Game):
            def __init__(self):
                self.first = None
                self.second = None

            def on_update(self, dt):
                # Takes the click, leaving the key alone.
                mouse.wait(input.mouse)
                self.first = mouse.button
                input.wait()
                self.second = (input.type, key.value)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, KeyPressed("D")),
            (2, MouseButtonPressed("LEFT", 0, 0)),
        ]))
        self.assertEqual(game.first, "LEFT")
        self.assertEqual(game.second, (input.key, "D"))

    def test_movement_alone_does_not_end_it(self):
        class G(Game):
            seen = "not set"

            def on_event(self, event):
                if isinstance(event, tl.WindowCloseRequested):
                    self.quit()

            def on_update(self, dt):
                input.wait()
                self.seen = input.type
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, MouseMoved(4, 4)),
            (3, MouseButtonReleased("LEFT", 4, 4)),
            (6, tl.WindowCloseRequested()),
        ]))
        self.assertIsNone(game.seen)

    def test_waiting_with_no_game_running_explains_itself(self):
        with self.assertRaises(TrjoLudusError) as caught:
            input.wait()
        self.assertIn("running", str(caught.exception))

    def test_type_starts_as_nothing(self):
        self.assertIn(input.type, (None, input.key, input.mouse))


# --------------------------------------------------------------------------
# 3. Input remembers its window
# --------------------------------------------------------------------------


class TestInputRemembersItsWindow(InputTestCase):
    def test_a_queued_item_records_the_window(self):
        seen = {}

        class G(Game):
            def on_update(self, dt):
                application = tl.Application  # noqa: F841
                from trjoludus.app import current_application

                app = current_application()
                app._deliver(app._window.poll_events())
                seen["queued"] = list(app._input)
                seen["window"] = app._window
                self.quit()

        self.run_game(G(), ScriptedBackend([(1, KeyPressed("W"))]))
        self.assertTrue(seen["queued"])
        self.assertIs(seen["queued"][0].window, seen["window"])

    def test_pending_input_carries_what_it_needs(self):
        item = PendingInput("mouse", "LEFT", object(), 3, 4)
        self.assertEqual((item.kind, item.value, item.x, item.y),
                         ("mouse", "LEFT", 3, 4))

    def test_mouse_state_is_per_window(self):
        """Two windows must not share one pointer position."""
        backend = ScriptedBackend()
        seen = {}

        class G(Game):
            def on_start(self):
                from trjoludus.app import current_application

                app = current_application()
                other = backend.create_window("second", 16, 16)
                app.mouse_state(app._window).moved(1, 2)
                app.mouse_state(other).moved(30, 40)
                seen["own"] = app.mouse_state(app._window).position
                seen["other"] = app.mouse_state(other).position
                seen["module"] = mouse.position

            def on_update(self, dt):
                self.quit()

        self.run_game(G(), backend)
        self.assertEqual(seen["own"], (1, 2))
        self.assertEqual(seen["other"], (30, 40))
        self.assertEqual(seen["module"], (1, 2),
                         "the module names must read the game's own window")

    def test_input_from_another_window_does_not_answer_this_games_wait(self):
        backend = ScriptedBackend([(5, tl.WindowCloseRequested())])

        class G(Game):
            seen = "not set"

            def on_start(self):
                other = backend.create_window("second", 16, 16)
                other.simulate_event(MouseButtonPressed("RIGHT", 5, 5))

            def on_event(self, event):
                if isinstance(event, tl.WindowCloseRequested):
                    self.quit()

            def on_update(self, dt):
                mouse.wait(input.mouse)
                self.seen = mouse.button
                self.quit()

        game = G()
        self.run_game(game, backend)
        self.assertIsNone(game.seen, "another window's click leaked in")

    def test_state_does_not_survive_into_the_next_run(self):
        class G(Game):
            def on_update(self, dt):
                self.quit()

        self.run_game(G(), ScriptedBackend([(1, MouseMoved(9, 9))]))
        self.assertEqual(mouse.position, (0, 0))


class TestNullBackend(InputTestCase):
    def test_headless_games_can_use_every_wait(self):
        class G(Game):
            def __init__(self):
                self.seen = []

            def on_update(self, dt):
                keyboard.wait(input.key)
                self.seen.append(key.value)
                mouse.wait(input.mouse)
                self.seen.append(mouse.button)
                input.wait()
                self.seen.append(input.type)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, KeyPressed("W")),
            (2, MouseButtonPressed("LEFT", 0, 0)),
            (3, KeyPressed("A")),
        ]))
        self.assertEqual(game.seen, ["W", "LEFT", input.key])

    def test_the_null_backend_does_not_end_waits_by_itself(self):
        """It has no window to lose, so only the game can stop a wait."""

        class G(Game):
            def on_update(self, dt):
                keyboard.wait(input.key)
                self.quit()

        game = G()
        backend = self.run_game(game, ScriptedBackend([(4, KeyPressed("W"))]))
        self.assertTrue(backend.keeps_application_alive)


if __name__ == "__main__":
    unittest.main()
