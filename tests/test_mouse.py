"""Tests for mouse position, buttons and waiting.

All headless. Mouse input is injected as platform-neutral events through the
null backend, so both the continuous state and the discrete input can be
checked exactly rather than by asking a human to wiggle a mouse. Turning a
real X button number into a canonical name is tested in test_x11.py.
"""

import unittest

import trjoludus as tl
from trjoludus import Game, input, mouse
from trjoludus.app import Application
from trjoludus.errors import TrjoLudusError
from trjoludus.events import (
    MOUSE_BUTTONS,
    MouseButtonPressed,
    MouseButtonReleased,
    MouseMoved,
    WindowResized,
)
from trjoludus.platform.null import NullBackend


class ScriptedBackend(NullBackend):
    """Null backend that feeds a window a scripted sequence of events.

    ``(poll, event)``: the event is queued the first time ``poll_events`` runs
    on or after that many polls, so a test can place input at a chosen point
    in a wait without any timing assumptions.
    """

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


class MouseTestCase(unittest.TestCase):
    def setUp(self):
        mouse._reset()
        self.addCleanup(mouse._reset)

    def run_game(self, game, backend=None, size=(64, 48)):
        backend = backend or ScriptedBackend()
        Application(game, size=size, max_fps=None, backend=backend).run()
        return backend


class TestButtonNames(unittest.TestCase):
    def test_the_three_buttons(self):
        self.assertEqual(MOUSE_BUTTONS, {"LEFT", "RIGHT", "MIDDLE"})

    def test_mouse_is_exposed_publicly(self):
        self.assertIs(tl.mouse, mouse)

    def test_input_mouse_is_its_own_slot(self):
        self.assertIsNot(input.mouse, input.key)


class TestPosition(MouseTestCase):
    def test_starts_at_the_origin(self):
        self.assertEqual(mouse.position, (0, 0))
        self.assertEqual((mouse.x, mouse.y), (0, 0))

    def test_movement_updates_the_position(self):
        class G(Game):
            seen = None

            def on_update(self, dt):
                self.seen = mouse.position
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([(1, MouseMoved(12, 34))]))
        self.assertEqual(game.seen, (12, 34))

    def test_position_keeps_updating(self):
        class G(Game):
            def __init__(self):
                self.seen = []

            def on_update(self, dt):
                self.seen.append(mouse.position)
                if len(self.seen) >= 3:
                    self.quit()

        game = G()
        self.run_game(game, ScriptedBackend(
            [(1, MouseMoved(1, 1)), (2, MouseMoved(2, 2)), (3, MouseMoved(3, 3))]
        ))
        self.assertEqual(game.seen[-1], (3, 3))
        self.assertNotEqual(game.seen[0], game.seen[-1])

    def test_x_and_y_agree_with_position(self):
        class G(Game):
            seen = None

            def on_update(self, dt):
                self.seen = (mouse.x, mouse.y, mouse.position)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([(1, MouseMoved(7, 9))]))
        x, y, position = game.seen
        self.assertEqual((x, y), position)

    def test_reading_the_position_never_goes_stale(self):
        """It is looked up, not copied, so there is nothing to refresh."""
        state = mouse.active_state()
        state.moved(5, 6)
        first = mouse.position
        state.moved(50, 60)
        self.assertEqual(first, (5, 6))
        self.assertEqual(mouse.position, (50, 60))

    def test_the_position_is_reset_between_runs(self):
        class G(Game):
            def on_update(self, dt):
                self.quit()

        self.run_game(G(), ScriptedBackend([(1, MouseMoved(99, 99))]))
        self.assertEqual(mouse.position, (0, 0))


class TestButtons(MouseTestCase):
    def test_nothing_is_pressed_to_begin_with(self):
        for name in MOUSE_BUTTONS:
            with self.subTest(button=name):
                self.assertFalse(mouse.pressed(name))

    def test_each_button_can_be_held(self):
        for name in ("LEFT", "RIGHT", "MIDDLE"):
            with self.subTest(button=name):
                mouse._reset()

                class G(Game):
                    seen = None

                    def on_update(self, dt):
                        self.seen = mouse.pressed(name)
                        self.quit()

                game = G()
                self.run_game(game, ScriptedBackend(
                    [(1, MouseButtonPressed(name, 0, 0))]))
                self.assertTrue(game.seen)

    def test_releasing_clears_the_button(self):
        class G(Game):
            def __init__(self):
                self.while_down = None
                self.after_up = None

            def on_update(self, dt):
                if self.while_down is None:
                    self.while_down = mouse.pressed("LEFT")
                    return
                self.after_up = mouse.pressed("LEFT")
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (1, MouseButtonPressed("LEFT", 0, 0)),
            (2, MouseButtonReleased("LEFT", 0, 0)),
        ]))
        self.assertTrue(game.while_down)
        self.assertFalse(game.after_up)

    def test_buttons_are_independent(self):
        class G(Game):
            seen = None

            def on_update(self, dt):
                self.seen = (mouse.pressed("LEFT"), mouse.pressed("RIGHT"))
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend(
            [(1, MouseButtonPressed("LEFT", 0, 0))]))
        self.assertEqual(game.seen, (True, False))

    def test_a_press_also_updates_the_position(self):
        class G(Game):
            seen = None

            def on_update(self, dt):
                self.seen = mouse.position
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend(
            [(1, MouseButtonPressed("LEFT", 21, 22))]))
        self.assertEqual(game.seen, (21, 22))

    def test_held_buttons_are_forgotten_between_runs(self):
        class G(Game):
            def on_update(self, dt):
                self.quit()

        self.run_game(G(), ScriptedBackend(
            [(1, MouseButtonPressed("LEFT", 0, 0))]))
        self.assertFalse(mouse.pressed("LEFT"))

    def test_an_unknown_button_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            mouse.pressed("SCROLL")
        message = str(caught.exception)
        self.assertIn("SCROLL", message)
        self.assertIn("LEFT", message)

    def test_a_non_string_button_is_rejected(self):
        with self.assertRaises(TypeError):
            mouse.pressed(1)

    def test_lowercase_is_not_quietly_accepted(self):
        with self.assertRaises(ValueError):
            mouse.pressed("left")


class TestWaitOutsideAGame(unittest.TestCase):
    def test_waiting_with_no_game_running_explains_itself(self):
        with self.assertRaises(TrjoLudusError) as caught:
            mouse.wait(input.mouse)
        self.assertIn("running", str(caught.exception))

    def test_a_bad_argument_is_rejected(self):
        with self.assertRaises(TrjoLudusError) as caught:
            mouse.wait("LEFT")
        self.assertIn("input.mouse", str(caught.exception))

    def test_the_keyboard_slot_is_not_accepted(self):
        with self.assertRaises(TrjoLudusError):
            mouse.wait(input.key)


class TestWait(MouseTestCase):
    def test_reports_the_button_that_was_pressed(self):
        class G(Game):
            seen = None

            def on_update(self, dt):
                mouse.wait(input.mouse)
                self.seen = mouse.button
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend(
            [(2, MouseButtonPressed("RIGHT", 0, 0))]))
        self.assertEqual(game.seen, "RIGHT")

    def test_reports_where_the_click_happened(self):
        class G(Game):
            seen = None

            def on_update(self, dt):
                mouse.wait(input.mouse)
                self.seen = mouse.position
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend(
            [(2, MouseButtonPressed("LEFT", 40, 30))]))
        self.assertEqual(game.seen, (40, 30))

    def test_clicks_arrive_in_order(self):
        class G(Game):
            def __init__(self):
                self.seen = []

            def on_update(self, dt):
                mouse.wait(input.mouse)
                self.seen.append(mouse.button)
                mouse.wait(input.mouse)
                self.seen.append(mouse.button)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, MouseButtonPressed("LEFT", 0, 0)),
            (2, MouseButtonPressed("RIGHT", 0, 0)),
        ]))
        self.assertEqual(game.seen, ["LEFT", "RIGHT"])

    def test_each_click_answers_exactly_one_wait(self):
        """One press must not satisfy two waits."""

        class G(Game):
            def __init__(self):
                self.first = None
                self.second = "not set"

            def on_event(self, event):
                if isinstance(event, tl.WindowCloseRequested):
                    self.quit()

            def on_update(self, dt):
                mouse.wait(input.mouse)
                self.first = mouse.button
                mouse.wait(input.mouse)
                self.second = mouse.button
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, MouseButtonPressed("LEFT", 0, 0)),
            (6, tl.WindowCloseRequested()),
        ]))
        self.assertEqual(game.first, "LEFT")
        self.assertIsNone(game.second, "the same click was handed out twice")

    def test_the_same_button_twice_is_two_clicks(self):
        class G(Game):
            def __init__(self):
                self.seen = []

            def on_update(self, dt):
                mouse.wait(input.mouse)
                self.seen.append(mouse.button)
                mouse.wait(input.mouse)
                self.seen.append(mouse.button)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, MouseButtonPressed("LEFT", 0, 0)),
            (3, MouseButtonPressed("LEFT", 0, 0)),
        ]))
        self.assertEqual(game.seen, ["LEFT", "LEFT"])

    def test_movement_does_not_end_a_wait(self):
        """Otherwise nudging the mouse would count as input."""

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
            (2, MouseMoved(5, 5)),
            (3, MouseMoved(6, 6)),
            (6, tl.WindowCloseRequested()),
        ]))
        self.assertIsNone(game.seen, "movement ended the wait")

    def test_a_release_does_not_end_a_wait(self):
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
            (2, MouseButtonReleased("LEFT", 0, 0)),
            (6, tl.WindowCloseRequested()),
        ]))
        self.assertIsNone(game.seen)

    def test_a_click_from_before_the_wait_is_still_delivered(self):
        class G(Game):
            seen = None
            frames = 0

            def on_update(self, dt):
                self.frames += 1
                if self.frames < 3:
                    return
                mouse.wait(input.mouse)
                self.seen = mouse.button
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend(
            [(1, MouseButtonPressed("MIDDLE", 0, 0))]))
        self.assertEqual(game.seen, "MIDDLE")

    def test_unrelated_events_still_reach_the_game(self):
        class G(Game):
            def __init__(self):
                self.seen = []

            def on_event(self, event):
                self.seen.append(event)

            def on_update(self, dt):
                mouse.wait(input.mouse)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, WindowResized(20, 10)),
            (4, MouseButtonPressed("LEFT", 0, 0)),
        ]))
        self.assertIn(WindowResized(20, 10), game.seen)

    def test_mouse_events_do_not_also_reach_on_event(self):
        """One press belongs in one place, as with keys."""

        class G(Game):
            def __init__(self):
                self.seen = []

            def on_event(self, event):
                self.seen.append(event)

            def on_update(self, dt):
                mouse.wait(input.mouse)
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([
            (2, MouseMoved(1, 1)),
            (2, MouseButtonPressed("LEFT", 0, 0)),
        ]))
        mouse_events = [
            e for e in game.seen
            if isinstance(e, (MouseMoved, MouseButtonPressed,
                              MouseButtonReleased))
        ]
        self.assertEqual(mouse_events, [])

    def test_the_button_is_cleared_between_runs(self):
        class G(Game):
            def on_update(self, dt):
                mouse.wait(input.mouse)
                self.quit()

        self.run_game(G(), ScriptedBackend(
            [(2, MouseButtonPressed("LEFT", 0, 0))]))
        self.assertIsNone(mouse.button)

    def test_unread_clicks_do_not_survive_into_the_next_run(self):
        class Quitter(Game):
            def on_update(self, dt):
                self.quit()

        self.run_game(Quitter(), ScriptedBackend(
            [(1, MouseButtonPressed("LEFT", 0, 0))]))

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
        self.run_game(game, ScriptedBackend([(3, tl.WindowCloseRequested())]))
        self.assertIsNone(game.seen, "input leaked from the previous run")


class TestWaitAndWindowLifetime(MouseTestCase):
    """The lifecycle rule has to cover this wait too, not just the keyboard."""

    def test_a_wait_ends_when_the_last_window_disappears(self):
        class GraphicalBackend(ScriptedBackend):
            @property
            def keeps_application_alive(self):
                return any(not w.is_closed for w in self._windows)

        backend = GraphicalBackend()

        class G(Game):
            seen = "not set"

            def on_update(self, dt):
                backend.windows[0].close()
                mouse.wait(input.mouse)
                self.seen = mouse.button
                self.quit()

        game = G()
        self.run_game(game, backend)
        self.assertIsNone(game.seen, "mouse.wait() did not give up")

    def test_a_close_request_does_not_block_the_game_forever(self):
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
        self.run_game(game, ScriptedBackend([(3, tl.WindowCloseRequested())]))
        self.assertIsNone(game.seen)


class TestMultipleWindows(MouseTestCase):
    """Input belongs to the window that received it."""

    def test_input_to_another_window_is_not_mixed_in(self):
        # The close request is what ends the wait: if the other window's click
        # leaked in, the wait would end early and report RIGHT instead.
        backend = ScriptedBackend([(5, tl.WindowCloseRequested())])

        class G(Game):
            seen = "not set"

            def on_start(self):
                other = backend.create_window("second", 32, 32)
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
        self.assertIsNone(game.seen, "input from another window leaked in")


class TestNullBackend(MouseTestCase):
    def test_a_headless_game_can_read_the_mouse(self):
        class G(Game):
            seen = None

            def on_update(self, dt):
                self.seen = mouse.position
                self.quit()

        game = G()
        backend = NullBackend()
        Application(game, size=(16, 16), max_fps=None, backend=backend).run()
        self.assertEqual(game.seen, (0, 0))

    def test_simulated_mouse_events_work_headlessly(self):
        class G(Game):
            seen = None

            def on_update(self, dt):
                self.seen = mouse.position
                self.quit()

        game = G()
        self.run_game(game, ScriptedBackend([(1, MouseMoved(3, 4))]))
        self.assertEqual(game.seen, (3, 4))


if __name__ == "__main__":
    unittest.main()
