"""Tests for the time system: waiting, delta and frame rate.

Timing tests are easy to write badly. These avoid exact values: a wait is
checked against a generous lower bound and an upper bound loose enough that a
loaded machine cannot fail it, and everything about *when* a wait gives up is
made deterministic instead -- the game quits, or the backend drops its window,
rather than a clock being raced.

Every blocking test scripts its own way out. None of them can hang.
"""

import unittest
from time import perf_counter

from trjoludus import Game, time as game_time
from trjoludus.app import Application, current_application
from trjoludus.clock import Clock
from trjoludus.errors import TrjoLudusError
from trjoludus.events import KeyPressed, WindowCloseRequested
from trjoludus.platform.null import NullBackend
from trjoludus.scene import current_scene
from trjoludus.ui import current_ui


class DyingBackend(NullBackend):
    """Loses its window after a set number of polls.

    A window can go away without any close request being sent. That is the
    other reason every blocking call has to give up, and this is how a test
    causes it on purpose.
    """

    def __init__(self, polls_before_dying=3):
        super().__init__()
        self.remaining = polls_before_dying
        self.window = None

    def create_window(self, title, width, height):
        window = super().create_window(title, width, height)
        backend = self
        original = window.poll_events

        def poll_events():
            backend.remaining -= 1
            if backend.remaining <= 0:
                window._closed = True
            return original()

        window.poll_events = poll_events
        self.window = window
        return window

    @property
    def keeps_application_alive(self) -> bool:
        return self.remaining > 0


class TimeTestCase(unittest.TestCase):
    def setUp(self):
        current_scene().clear()
        current_ui().clear()
        self.addCleanup(current_scene().clear)
        self.addCleanup(current_ui().clear)

    def play(self, game, backend=None, max_fps=None, size=(40, 30)):
        Application(game, size=size, max_fps=max_fps,
                    backend=backend or NullBackend()).run()
        return game


class TestWaiting(TimeTestCase):
    def test_it_waits_about_that_long(self):
        measured = []

        class G(Game):
            def on_update(self, dt):
                start = perf_counter()
                game_time.wait(0.05)
                measured.append(perf_counter() - start)
                self.quit()

        self.play(G())
        # Generous both ways: the point is that it waited, not that it hit a
        # stopwatch. A loaded machine may overshoot; it must not undershoot.
        self.assertGreaterEqual(measured[0], 0.04)
        self.assertLess(measured[0], 2.0)

    def test_a_longer_wait_takes_longer(self):
        measured = []

        class G(Game):
            def on_update(self, dt):
                for length in (0.01, 0.08):
                    start = perf_counter()
                    game_time.wait(length)
                    measured.append(perf_counter() - start)
                self.quit()

        self.play(G())
        self.assertGreater(measured[1], measured[0])

    def test_waiting_for_no_time_returns_at_once(self):
        measured = []

        class G(Game):
            def on_update(self, dt):
                start = perf_counter()
                game_time.wait(0)
                measured.append(perf_counter() - start)
                self.quit()

        self.play(G())
        self.assertLess(measured[0], 0.5)

    def test_a_wait_shorter_than_the_poll_interval_still_works(self):
        class G(Game):
            def on_update(self, dt):
                game_time.wait(0.0001)
                self.quit()

        self.play(G())          # must return rather than round up and hang

    def test_it_returns_nothing(self):
        answers = []

        class G(Game):
            def on_update(self, dt):
                answers.append(game_time.wait(0.001))
                self.quit()

        self.play(G())
        self.assertEqual(answers, [None])

    def test_seconds_must_be_a_number(self):
        errors = []

        class G(Game):
            def on_update(self, dt):
                for bad in ("1", None, True, [1]):
                    try:
                        game_time.wait(bad)
                    except TypeError as error:
                        errors.append(type(error).__name__)
                self.quit()

        self.play(G())
        self.assertEqual(errors, ["TypeError"] * 4)

    def test_a_negative_wait_is_refused(self):
        errors = []

        class G(Game):
            def on_update(self, dt):
                try:
                    game_time.wait(-1)
                except ValueError as error:
                    errors.append(str(error))
                self.quit()

        self.play(G())
        self.assertIn("only runs forwards", errors[0])

    def test_waiting_outside_a_game_says_so(self):
        with self.assertRaises(TrjoLudusError) as caught:
            game_time.wait(0.01)
        self.assertIn("running game", str(caught.exception))

    def test_events_are_still_delivered_while_waiting(self):
        """A close request must reach the game mid-wait, not a second later."""
        seen = []
        backend = NullBackend()

        class G(Game):
            def on_start(self):
                backend.windows[0].simulate_event(WindowCloseRequested())

            def on_event(self, event):
                seen.append(event)

            def on_update(self, dt):
                game_time.wait(0.02)
                self.quit()

        self.play(G(), backend=backend)
        self.assertTrue(any(isinstance(e, WindowCloseRequested) for e in seen))


class TestWaitingEndsWithTheGame(TimeTestCase):
    """A wait can never outlive the game it is waiting in."""

    def test_a_wait_after_quitting_returns_at_once(self):
        measured = []

        class G(Game):
            def on_update(self, dt):
                self.quit()
                start = perf_counter()
                game_time.wait(30)
                measured.append(perf_counter() - start)

        self.play(G())
        self.assertLess(measured[0], 1.0, "a quit game must not keep waiting")

    def test_a_wait_ends_when_the_window_disappears(self):
        measured = []

        class G(Game):
            def on_update(self, dt):
                start = perf_counter()
                game_time.wait(30)
                measured.append(perf_counter() - start)
                self.quit()

        self.play(G(), backend=DyingBackend(polls_before_dying=3))
        self.assertLess(measured[0], 5.0, "a wait outlived its window")

    def test_the_wait_reports_that_it_gave_up(self):
        answers = []

        class G(Game):
            def on_update(self, dt):
                application = current_application()
                self.quit()
                answers.append(application.wait_for_seconds(30))

        self.play(G())
        self.assertEqual(answers, [False])

    def test_a_completed_wait_reports_that_it_finished(self):
        answers = []

        class G(Game):
            def on_update(self, dt):
                answers.append(current_application().wait_for_seconds(0.001))
                self.quit()

        self.play(G())
        self.assertEqual(answers, [True])

    def test_the_keyboard_wait_still_gives_up_too(self):
        """The shared wait step must not have changed the older waits."""
        from trjoludus import input as input_module
        from trjoludus import key, keyboard

        class G(Game):
            def on_update(self, dt):
                self.quit()
                keyboard.wait(input_module.key)   # nothing will ever arrive
                self.answer = key.value if hasattr(key, "value") else None

        self.play(G())      # a hang here is the failure

    def test_the_mouse_wait_still_gives_up_too(self):
        from trjoludus import input as input_module
        from trjoludus import mouse

        class G(Game):
            def on_update(self, dt):
                self.quit()
                mouse.wait(input_module.mouse)

        self.play(G())

    def test_a_wait_still_ends_when_the_window_goes(self):
        from trjoludus import input as input_module
        from trjoludus import keyboard

        class G(Game):
            def on_update(self, dt):
                keyboard.wait(input_module.key)
                self.quit()

        self.play(G(), backend=DyingBackend(polls_before_dying=3))

    def test_input_still_arrives_through_the_shared_step(self):
        from trjoludus import input as input_module
        from trjoludus import key, keyboard

        seen = []
        backend = NullBackend()

        class G(Game):
            def on_start(self):
                backend.windows[0].simulate_event(KeyPressed("W"))

            def on_update(self, dt):
                keyboard.wait(input_module.key)
                seen.append(str(key))
                self.quit()

        self.play(G(), backend=backend)
        self.assertEqual(seen, ["W"])


class TestDelta(TimeTestCase):
    def test_it_is_zero_on_the_first_frame(self):
        seen = []

        class G(Game):
            def on_update(self, dt):
                seen.append(game_time.delta)
                self.quit()

        self.play(G())
        self.assertEqual(seen, [0.0])

    def test_it_is_never_negative(self):
        seen = []

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                seen.append(game_time.delta)
                if self.count >= 10:
                    self.quit()

        self.play(G())
        self.assertEqual(len(seen), 10)
        self.assertTrue(all(value >= 0.0 for value in seen), seen)

    def test_it_is_the_same_number_on_update_is_given(self):
        pairs = []

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                pairs.append((dt, game_time.delta))
                if self.count >= 5:
                    self.quit()

        self.play(G())
        for handed, read in pairs:
            self.assertEqual(handed, read)

    def test_it_is_measured_in_seconds(self):
        """A paced game's delta must match the frame period it asked for."""
        seen = []

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count > 1:        # skip the first, which is 0.0
                    seen.append(game_time.delta)
                if self.count >= 6:
                    self.quit()

        self.play(G(), max_fps=50)        # 0.02s per frame
        average = sum(seen) / len(seen)
        # Seconds, not milliseconds and not frames: 0.02 within a wide band.
        self.assertGreater(average, 0.005)
        self.assertLess(average, 0.2)

    def test_it_is_clamped_so_a_stall_cannot_teleport_a_game(self):
        seen = []

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    game_time.wait(0.4)   # a long stall, on purpose
                else:
                    seen.append(game_time.delta)
                    self.quit()

        self.play(G())
        self.assertLessEqual(seen[0], 0.25 + 1e-9)

    def test_it_is_zero_outside_a_game(self):
        self.assertEqual(game_time.delta, 0.0)

    def test_it_is_zero_again_after_a_run(self):
        class G(Game):
            def on_update(self, dt):
                self.quit()

        self.play(G())
        self.assertEqual(game_time.delta, 0.0)

    def test_frame_rate_independent_movement(self):
        """The same simulated seconds must cover the same distance.

        The clock is driven by a fake time source, so this compares two frame
        rates exactly rather than racing a real one: ten frames of a tenth of
        a second, and a hundred frames of a hundredth, are both one second and
        must move a thing the same distance.
        """
        def distance_at(step, frames):
            # One extra tick: the first establishes the baseline and reports
            # 0.0, so `frames` measured deltas need `frames + 1` ticks.
            ticks = iter([step * index for index in range(frames + 2)])
            clock = Clock(max_fps=None, time_source=lambda: next(ticks),
                          sleep_function=lambda seconds: None)
            travelled = 0.0
            for _ in range(frames + 1):
                travelled += 100 * clock.tick()
            return travelled

        slow = distance_at(0.1, 10)        # 10 fps for one second
        fast = distance_at(0.01, 100)      # 100 fps for one second
        self.assertAlmostEqual(slow, fast, places=6)
        # One second at 100 pixels a second, on both.
        self.assertAlmostEqual(fast, 100.0, places=6)


class TestMovingByTime(TimeTestCase):
    """Whole-pixel positions and fractional speeds have to be reconciled."""

    def test_a_fractional_step_is_kept(self):
        """The whole point: a frame's worth of movement is not a whole pixel."""
        from trjoludus import color, draw

        box = draw.list("menu").rect(0, 0, 10, 10, color.blue)
        box.move.x(1.67)
        self.assertEqual(box.x, 1.67)

    def test_rounding_each_step_would_have_drifted(self):
        """What the old whole-pixel API forced, measured.

        At 60 frames a second a 100-pixel-per-second step is 1.67 pixels, and
        every one of them rounds to 2 -- 20% too far after a second. This is
        the arithmetic sub-pixel positions exist to avoid.
        """
        step = 100 * (1 / 60)
        drifted = 60 * round(step)
        self.assertEqual(drifted, 120)
        self.assertGreater(drifted, 100 * 1.15)

    def test_moving_by_a_fraction_each_frame_does_not_drift(self):
        from trjoludus import color, draw

        box = draw.list("menu").rect(0, 0, 10, 10, color.blue)
        for _ in range(60):
            box.move.x(100 * (1 / 60))
        self.assertAlmostEqual(box.x, 100.0, places=6)
        self.assertEqual(box.screen_position[0], 100)

    def test_the_simple_pattern_lands_where_it_should(self):
        """One simulated second at 100 pixels a second is 100 pixels."""
        from trjoludus import color, draw

        box = draw.list("menu").rect(0, 0, 10, 10, color.blue)
        ticks = iter([0.01 * index for index in range(200)])
        clock = Clock(max_fps=None, time_source=lambda: next(ticks),
                      sleep_function=lambda seconds: None)

        for _ in range(101):                 # 100 measured frames of 0.01s
            box.move.x(100 * clock.tick())

        self.assertEqual(box.screen_position[0], 100)

    def test_the_same_distance_at_a_different_frame_rate(self):
        from trjoludus import color, draw

        def travel(step, frames):
            menu = draw.list(f"menu{step}")
            box = menu.rect(0, 0, 10, 10, color.blue)
            ticks = iter([step * index for index in range(frames + 3)])
            clock = Clock(max_fps=None, time_source=lambda: next(ticks),
                          sleep_function=lambda seconds: None)
            for _ in range(frames + 1):
                box.move.x(100 * clock.tick())
            return box.screen_position[0]

        self.assertEqual(travel(0.1, 10), travel(0.01, 100))


class TestFps(TimeTestCase):
    def test_it_is_available_while_a_game_runs(self):
        seen = []

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                seen.append(game_time.fps)
                if self.count >= 5:
                    self.quit()

        self.play(G())
        self.assertEqual(len(seen), 5)
        self.assertTrue(all(isinstance(value, float) for value in seen))
        self.assertTrue(all(value >= 0.0 for value in seen))

    def test_it_is_zero_before_anything_has_been_measured(self):
        seen = []

        class G(Game):
            def on_update(self, dt):
                seen.append(game_time.fps)
                self.quit()

        self.play(G())
        self.assertEqual(seen, [0.0])

    def test_it_is_the_other_side_of_delta(self):
        pairs = []

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                pairs.append((game_time.delta, game_time.fps))
                if self.count >= 5:
                    self.quit()

        self.play(G(), max_fps=60)
        for delta, fps in pairs:
            if delta > 0.0:
                self.assertAlmostEqual(fps, 1.0 / delta, places=6)

    def test_a_paced_game_reports_roughly_its_cap(self):
        seen = []

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count > 1:
                    seen.append(game_time.fps)
                if self.count >= 8:
                    self.quit()

        self.play(G(), max_fps=50)
        average = sum(seen) / len(seen)
        # Wide: pacing sleeps at least as long as asked, never less, so the
        # measured rate can only come in under the cap.
        self.assertGreater(average, 5)
        self.assertLess(average, 200)

    def test_it_is_zero_outside_a_game(self):
        self.assertEqual(game_time.fps, 0.0)


class TestReadOnly(TimeTestCase):
    def test_delta_cannot_be_assigned(self):
        with self.assertRaises(AttributeError) as caught:
            game_time.delta = 0.5
        self.assertIn("read-only", str(caught.exception))

    def test_fps_cannot_be_assigned(self):
        with self.assertRaises(AttributeError):
            game_time.fps = 120

    def test_refusing_the_assignment_leaves_the_real_value(self):
        try:
            game_time.delta = 99.0
        except AttributeError:
            pass
        self.assertEqual(game_time.delta, 0.0)

    def test_assignment_is_refused_inside_a_game_too(self):
        errors = []

        class G(Game):
            def on_update(self, dt):
                try:
                    game_time.delta = 99.0
                except AttributeError:
                    errors.append("refused")
                self.quit()

        self.play(G())
        self.assertEqual(errors, ["refused"])

    def test_an_unknown_name_is_still_an_attribute_error(self):
        with self.assertRaises(AttributeError):
            game_time.elapsed_hours

    def test_wait_can_still_be_reached(self):
        self.assertTrue(callable(game_time.wait))

    def test_what_the_module_offers(self):
        self.assertEqual(set(game_time.__all__), {"delta", "fps", "wait"})


class TestRunIsolation(TimeTestCase):
    def test_the_second_run_starts_from_zero(self):
        first = []

        class G(Game):
            def on_update(self, dt):
                first.append(game_time.delta)
                self.quit()

        game = G()
        self.play(game)
        self.play(game)
        self.assertEqual(first, [0.0, 0.0], "timing leaked into the next run")

    def test_the_frame_count_does_not_carry_over(self):
        counts = []

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count >= 3:
                    counts.append(current_application().clock.frame_count)
                    self.quit()

        game = G()
        application = Application(game, size=(40, 30), max_fps=None,
                                  backend=NullBackend())
        application.run()
        game.count = 0
        application._backend = NullBackend()
        application.run()
        self.assertEqual(counts[0], counts[1],
                         "the clock carried frames into the next run")

    def test_elapsed_time_does_not_carry_over(self):
        elapsed = []

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count >= 2:
                    elapsed.append(current_application().clock.elapsed)
                    self.quit()

        game = G()
        application = Application(game, size=(40, 30), max_fps=None,
                                  backend=NullBackend())
        application.run()
        game.count = 0
        application._backend = NullBackend()
        application.run()
        self.assertLess(abs(elapsed[0] - elapsed[1]), 0.25)

    def test_a_wait_in_one_run_does_not_shorten_the_next(self):
        deltas = []

        class G(Game):
            def on_update(self, dt):
                deltas.append(game_time.delta)
                game_time.wait(0.01)
                self.quit()

        game = G()
        self.play(game)
        self.play(game)
        self.assertEqual(deltas, [0.0, 0.0])


class TestOneTimekeeper(TimeTestCase):
    """Timing lives in the clock; nothing else grows a timer of its own."""

    def test_the_time_module_holds_no_state(self):
        import trjoludus.time as module

        stateful = [
            name for name, value in vars(module).items()
            if not name.startswith("__")
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ]
        self.assertEqual(stateful, [])

    def test_delta_comes_from_the_running_clock(self):
        seen = []

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                clock = current_application().clock
                seen.append((game_time.delta, clock.delta,
                             game_time.fps, clock.fps))
                if self.count >= 4:
                    self.quit()

        self.play(G(), max_fps=60)
        for delta, clock_delta, fps, clock_fps in seen:
            self.assertEqual(delta, clock_delta)
            self.assertEqual(fps, clock_fps)

    def test_the_engine_measures_time_in_one_place(self):
        """Only the clock reads a system timer."""
        import pathlib

        import trjoludus

        root = pathlib.Path(trjoludus.__file__).parent
        offenders = []
        for path in sorted(root.rglob("*.py")):
            source = path.read_text()
            if "perf_counter" in source and path.name != "clock.py":
                offenders.append(path.name)
        self.assertEqual(offenders, [],
                         "timing belongs to clock.py alone")

    def test_waiting_does_not_start_a_second_loop(self):
        """The wait turns the same crank the loop and the input waits do."""
        import inspect

        from trjoludus.app import Application as App

        source = inspect.getsource(App.wait_for_seconds)
        self.assertIn("_keep_waiting", source)
        self.assertIn("_keep_waiting", inspect.getsource(App.wait_for_input))


if __name__ == "__main__":
    unittest.main()
