"""Tests for held-key state, and its separation from key events.

Two things share the keyboard: ``keyboard.button.pressed("W")`` asks what is
held right now, and ``keyboard.wait()`` blocks until a press arrives and hands
it out once. These check that each does its own job and that neither takes
anything from the other -- a press read by a wait still counts as held, and
asking what is held never empties the queue a wait reads from.

Events are injected through the null backend, so every transition is exact
rather than timed. Every blocking test scripts its own way out; none can hang.
"""

import unittest

from trjoludus import Game, keyboard, mouse
from trjoludus import input as input_module
from trjoludus.app import Application, current_application
from trjoludus.events import (
    KEY_NAMES,
    KeyPressed,
    KeyReleased,
    MouseButtonPressed,
)
from trjoludus.keyboard import KeyboardState, key
from trjoludus.platform.null import NullBackend


class KeyboardStateTestCase(unittest.TestCase):
    def setUp(self):
        mouse._reset()
        keyboard._reset()
        key._set(None)
        self.addCleanup(mouse._reset)
        self.addCleanup(keyboard._reset)
        self.addCleanup(key._set, None)

    def watch(self, script, ask, frames=6):
        """Run a game, feeding events on given frames, asking on every frame.

        ``script`` maps a frame number to the events delivered *before* that
        frame's question, so a test reads as a sequence of transitions.
        """
        backend = NullBackend()
        answers = []

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                for event in script.get(self.count, ()):
                    backend.windows[0].simulate_event(event)
                answers.append(ask())
                if self.count >= frames:
                    self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        return answers


class TestHeldState(KeyboardStateTestCase):
    def test_nothing_is_held_to_begin_with(self):
        answers = self.watch({}, lambda: keyboard.button.pressed("W"),
                             frames=3)
        self.assertEqual(answers, [False, False, False])

    def test_a_press_makes_it_held(self):
        answers = self.watch({1: [KeyPressed("W")]},
                             lambda: keyboard.button.pressed("W"), frames=3)
        self.assertEqual(answers, [False, True, True])

    def test_a_release_makes_it_unheld(self):
        answers = self.watch(
            {1: [KeyPressed("W")], 3: [KeyReleased("W")]},
            lambda: keyboard.button.pressed("W"), frames=5,
        )
        self.assertEqual(answers, [False, True, True, False, False])

    def test_it_stays_held_across_many_frames(self):
        answers = self.watch({1: [KeyPressed("W")]},
                             lambda: keyboard.button.pressed("W"), frames=20)
        self.assertEqual(answers[1:], [True] * 19)

    def test_released_is_the_opposite_of_pressed(self):
        answers = self.watch(
            {1: [KeyPressed("W")], 3: [KeyReleased("W")]},
            lambda: (keyboard.button.pressed("W"),
                     keyboard.button.released("W")),
            frames=5,
        )
        for held, free in answers:
            self.assertNotEqual(held, free)

    def test_released_is_true_for_a_key_never_touched(self):
        """State, not an event: it is not only true just after letting go."""
        answers = self.watch({}, lambda: keyboard.button.released("ESCAPE"),
                             frames=3)
        self.assertEqual(answers, [True, True, True])

    def test_a_press_and_release_in_one_batch_ends_unheld(self):
        answers = self.watch(
            {1: [KeyPressed("W"), KeyReleased("W")]},
            lambda: keyboard.button.pressed("W"), frames=3,
        )
        self.assertEqual(answers, [False, False, False])

    def test_pressing_twice_without_a_release_stays_held(self):
        """Two downs and one up: one release is still enough to let go.

        An event injected during frame N arrives at the poll that starts
        frame N + 1, which is why the release shows up one frame after it is
        sent.
        """
        answers = self.watch(
            {1: [KeyPressed("W")], 2: [KeyPressed("W")],
             4: [KeyReleased("W")]},
            lambda: keyboard.button.pressed("W"), frames=5,
        )
        self.assertEqual(answers, [False, True, True, True, False])

    def test_a_release_with_no_press_is_harmless(self):
        answers = self.watch({1: [KeyReleased("W")]},
                             lambda: keyboard.button.pressed("W"), frames=3)
        self.assertEqual(answers, [False, False, False])

    def test_pressed_is_not_a_one_frame_event(self):
        """The key point: holding is a condition, not a moment."""
        answers = self.watch({1: [KeyPressed("SPACE")]},
                             lambda: keyboard.button.pressed("SPACE"),
                             frames=30)
        self.assertEqual(sum(answers), 29)


class TestSeveralKeys(KeyboardStateTestCase):
    def test_two_keys_are_held_at_once(self):
        answers = self.watch(
            {1: [KeyPressed("W"), KeyPressed("D")]},
            lambda: (keyboard.button.pressed("W"),
                     keyboard.button.pressed("D")),
            frames=3,
        )
        self.assertEqual(answers[1:], [(True, True), (True, True)])

    def test_releasing_one_leaves_the_other_held(self):
        answers = self.watch(
            {1: [KeyPressed("W"), KeyPressed("D")], 3: [KeyReleased("W")]},
            lambda: (keyboard.button.pressed("W"),
                     keyboard.button.pressed("D")),
            frames=5,
        )
        self.assertEqual(answers[3:], [(False, True), (False, True)])

    def test_many_keys_at_once(self):
        held = ["W", "A", "S", "D", "SPACE", "UP"]
        answers = self.watch(
            {1: [KeyPressed(name) for name in held]},
            lambda: [keyboard.button.pressed(name) for name in held],
            frames=3,
        )
        self.assertEqual(answers[-1], [True] * len(held))

    def test_they_are_released_independently(self):
        answers = self.watch(
            {1: [KeyPressed("W"), KeyPressed("A"), KeyPressed("D")],
             2: [KeyReleased("A")],
             3: [KeyReleased("D")]},
            lambda: (keyboard.button.pressed("W"),
                     keyboard.button.pressed("A"),
                     keyboard.button.pressed("D")),
            frames=5,
        )
        self.assertEqual(answers[1], (True, True, True))
        self.assertEqual(answers[2], (True, False, True))
        self.assertEqual(answers[4], (True, False, False))

    def test_the_movement_pattern(self):
        """Two directions held together, which is the point of held state."""
        moved = []

        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    backend.windows[0].simulate_event(KeyPressed("W"))
                    backend.windows[0].simulate_event(KeyPressed("D"))
                step = [0, 0]
                if keyboard.button.pressed("W"):
                    step[1] -= 1
                if keyboard.button.pressed("D"):
                    step[0] += 1
                moved.append(tuple(step))
                if self.count >= 4:
                    self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertEqual(moved[1:], [(1, -1)] * 3)


class TestAskingDoesNotConsume(KeyboardStateTestCase):
    def test_asking_a_hundred_times_gives_the_same_answer(self):
        answers = self.watch(
            {1: [KeyPressed("W")]},
            lambda: {keyboard.button.pressed("W") for _ in range(100)},
            frames=3,
        )
        self.assertEqual(answers[1], {True})
        self.assertEqual(answers[2], {True})

    def test_asking_leaves_the_press_for_a_wait(self):
        result = {}
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    backend.windows[0].simulate_event(KeyPressed("W"))
                    return
                for _ in range(50):
                    keyboard.button.pressed("W")
                # Must not still be waiting: the press is still queued.
                keyboard.wait(input_module.key)
                result["read"] = str(key)
                self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertEqual(result["read"], "W")

    def test_the_queue_is_untouched_by_asking(self):
        lengths = []
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    for name in ("W", "A", "S"):
                        backend.windows[0].simulate_event(KeyPressed(name))
                    return
                application = current_application()
                before = len(application._input)
                for _ in range(100):
                    keyboard.button.pressed("W")
                    keyboard.button.released("A")
                lengths.append((before, len(application._input)))
                self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertEqual(lengths, [(3, 3)])

    def test_state_is_kept_up_to_date_rather_than_worked_out(self):
        """A query must not scan the queue: it is a lookup in a set."""
        state = KeyboardState()
        state.key_down("W")
        self.assertIsInstance(state.held, set)
        self.assertTrue(state.pressed("W"))

        import inspect

        source = inspect.getsource(KeyboardState.pressed)
        self.assertIn("in self.held", source)


class TestWaitsAndStateTogether(KeyboardStateTestCase):
    def test_a_wait_still_receives_the_press(self):
        result = {}
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    backend.windows[0].simulate_event(KeyPressed("A"))
                    return
                keyboard.wait(input_module.key)
                result["key"] = str(key)
                self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertEqual(result["key"], "A")

    def test_a_press_read_by_a_wait_still_counts_as_held(self):
        result = {}
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    backend.windows[0].simulate_event(KeyPressed("W"))
                    return
                keyboard.wait(input_module.key)
                result["held"] = keyboard.button.pressed("W")
                self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertTrue(result["held"],
                        "a wait swallowed the press without marking it held")

    def test_a_key_released_during_a_wait_is_not_stuck(self):
        """The release arrives while a wait pumps; state must still see it."""
        result = {}
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    window = backend.windows[0]
                    window.simulate_event(KeyPressed("W"))
                    window.simulate_event(KeyReleased("W"))
                    window.simulate_event(KeyPressed("A"))
                    return
                keyboard.wait(input_module.key)       # takes W
                result["after_first"] = keyboard.button.pressed("W")
                keyboard.wait(input_module.key)       # takes A
                result["a_held"] = keyboard.button.pressed("A")
                self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertFalse(result["after_first"], "W stayed held after release")
        self.assertTrue(result["a_held"])

    def test_a_mouse_wait_does_not_disturb_keyboard_state(self):
        result = {}
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    window = backend.windows[0]
                    window.simulate_event(KeyPressed("W"))
                    window.simulate_event(
                        MouseButtonPressed(button="LEFT", x=1, y=1))
                    return
                mouse.wait(input_module.mouse)
                result["held"] = keyboard.button.pressed("W")
                result["button"] = mouse.button
                self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertTrue(result["held"])
        self.assertEqual(result["button"], "LEFT")

    def test_a_mouse_wait_leaves_the_key_for_the_keyboard(self):
        result = {}
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    window = backend.windows[0]
                    window.simulate_event(KeyPressed("W"))
                    window.simulate_event(
                        MouseButtonPressed(button="LEFT", x=1, y=1))
                    return
                mouse.wait(input_module.mouse)
                keyboard.wait(input_module.key)
                result["key"] = str(key)
                self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertEqual(result["key"], "W")

    def test_input_wait_keeps_the_order_and_the_state(self):
        seen = []
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    window = backend.windows[0]
                    window.simulate_event(KeyPressed("W"))
                    window.simulate_event(
                        MouseButtonPressed(button="LEFT", x=2, y=3))
                    window.simulate_event(KeyPressed("A"))
                    return
                for _ in range(3):
                    input_module.wait()
                    seen.append(input_module.type)
                seen.append(keyboard.button.pressed("W"))
                seen.append(keyboard.button.pressed("A"))
                self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertEqual(seen[:3],
                         [input_module.key, input_module.mouse,
                          input_module.key])
        self.assertEqual(seen[3:], [True, True])

    def test_holding_a_key_does_not_end_a_wait_by_itself(self):
        """A release is state, not input: it must not answer a wait."""
        result = {}
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    window = backend.windows[0]
                    window.simulate_event(KeyPressed("W"))
                    window.simulate_event(KeyReleased("W"))
                    return
                keyboard.wait(input_module.key)     # the press
                result["first"] = str(key)
                self.quit()               # so the second wait cannot hang
                keyboard.wait(input_module.key)
                result["second"] = key.value

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertEqual(result["first"], "W")
        self.assertIsNone(result["second"],
                          "a release was handed out as input")


class TestWindowLifecycle(KeyboardStateTestCase):
    def test_nothing_is_held_after_the_run_ends(self):
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    backend.windows[0].simulate_event(KeyPressed("W"))
                    return
                self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertFalse(keyboard.button.pressed("W"),
                         "a key stayed held after the window went")

    def test_a_key_held_when_the_window_vanishes_is_not_stuck(self):
        class Dying(NullBackend):
            def __init__(self):
                super().__init__()
                self.polls = 0

            def create_window(self, title, width, height):
                window = super().create_window(title, width, height)
                backend = self
                original = window.poll_events

                def poll_events():
                    backend.polls += 1
                    if backend.polls == 1:
                        window.simulate_event(KeyPressed("W"))
                    if backend.polls >= 3:
                        window._closed = True
                    return original()

                window.poll_events = poll_events
                return window

            @property
            def keeps_application_alive(self):
                return self.polls < 3

        backend = Dying()

        class G(Game):
            def on_update(self, dt):
                pass          # the backend ends the run by losing its window

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertFalse(keyboard.button.pressed("W"))

    def test_a_second_run_starts_with_nothing_held(self):
        seen = []

        def run_once(press):
            backend = NullBackend()

            class G(Game):
                count = 0

                def on_update(self, dt):
                    self.count += 1
                    if self.count == 1 and press:
                        backend.windows[0].simulate_event(KeyPressed("W"))
                        return
                    seen.append(keyboard.button.pressed("W"))
                    self.quit()

            Application(G(), size=(40, 30), max_fps=None,
                        backend=backend).run()

        run_once(press=True)
        run_once(press=False)
        self.assertEqual(seen, [True, False])

    def test_state_belongs_to_a_window(self):
        """Groundwork for several windows, without a public API for them."""
        found = {}

        class G(Game):
            def on_update(self, dt):
                application = current_application()
                other = object()
                found["mine"] = application.keyboard_state()
                found["other"] = application.keyboard_state(other)
                found["mine"].key_down("W")
                self.quit()

        Application(G(), size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        self.assertIsNot(found["mine"], found["other"])
        self.assertFalse(found["other"].pressed("W"))

    def test_a_key_in_another_window_is_not_held_here(self):
        answers = []

        class G(Game):
            def on_update(self, dt):
                application = current_application()
                application.keyboard_state(object()).key_down("W")
                answers.append(keyboard.button.pressed("W"))
                self.quit()

        Application(G(), size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        self.assertEqual(answers, [False])


class TestKeyNames(KeyboardStateTestCase):
    def test_a_key_must_be_a_string(self):
        for bad in (1, None, ["W"]):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    keyboard.button.pressed(bad)

    def test_an_unknown_key_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            keyboard.button.pressed("SHIFT")
        message = str(caught.exception)
        self.assertIn("not a key TrjoLudus knows", message)
        self.assertIn("ESCAPE", message)

    def test_lowercase_says_what_to_write_instead(self):
        with self.assertRaises(ValueError) as caught:
            keyboard.button.pressed("w")
        self.assertIn("'W' is", str(caught.exception))
        self.assertIn("uppercase", str(caught.exception))

    def test_released_checks_the_name_too(self):
        with self.assertRaises(ValueError):
            keyboard.button.released("shift")
        with self.assertRaises(TypeError):
            keyboard.button.released(None)

    def test_every_known_key_can_be_asked_about(self):
        for name in sorted(KEY_NAMES):
            with self.subTest(key=name):
                self.assertFalse(keyboard.button.pressed(name))

    def test_the_names_are_the_ones_events_use(self):
        """One way of naming keys, not two."""
        answers = self.watch({1: [KeyPressed("ESCAPE")]},
                             lambda: keyboard.button.pressed("ESCAPE"),
                             frames=3)
        self.assertTrue(answers[-1])


class TestOutsideAGame(KeyboardStateTestCase):
    def test_nothing_is_held_when_no_game_runs(self):
        self.assertFalse(keyboard.button.pressed("W"))
        self.assertTrue(keyboard.button.released("W"))

    def test_it_does_not_raise_without_a_window(self):
        for name in ("W", "SPACE", "UP"):
            self.assertFalse(keyboard.button.pressed(name))

    def test_the_wait_api_is_unchanged(self):
        """Step 3's blocking API keeps working exactly as it did."""
        self.assertTrue(callable(keyboard.wait))
        self.assertIsNone(key.value)


if __name__ == "__main__":
    unittest.main()
