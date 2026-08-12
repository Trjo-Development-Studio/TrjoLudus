"""Tests for the application and the engine-owned game loop.

Everything runs on the null backend, so the whole lifecycle -- window, events,
clock, cleanup -- is exercised with no operating system involved.

Every game used here stops itself. The null window never delivers a close
event on its own, so a game that forgot to call ``quit()`` would hang the
suite rather than fail it.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

import trjoludus
from trjoludus.app import DEFAULT_SIZE, DEFAULT_TITLE, Application, run
from trjoludus.clock import Clock
from trjoludus.events import WindowCloseRequested, WindowResized
from trjoludus.game import Game
from trjoludus.platform.null import NullBackend

GRAPHICAL_ENV_VARS = ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE")
PACKAGE_PARENT = str(Path(trjoludus.__file__).parent.parent)


class RecordingGame(Game):
    """Records every callback, then quits after a set number of frames."""

    def __init__(self, quit_after: int = 1):
        self.quit_after = quit_after
        self.calls: list[str] = []
        self.events: list[object] = []
        self.deltas: list[float] = []

    def on_start(self):
        self.calls.append("on_start")

    def on_event(self, event):
        self.calls.append("on_event")
        self.events.append(event)

    def on_update(self, dt):
        self.calls.append("on_update")
        self.deltas.append(dt)
        if len(self.deltas) >= self.quit_after:
            self.quit()

    def on_stop(self):
        self.calls.append("on_stop")

    @property
    def frames(self) -> int:
        return len(self.deltas)


class RecordingBackend(NullBackend):
    """Null backend for driving the application under test.

    Adds two things the plain null backend does not have:

    * ``created`` -- a permanent record of every window created. Needed
      because ``NullBackend.shutdown()`` releases ``windows``, so after a run
      there is nothing left to inspect.
    * event seeding -- windows start with events already queued, standing in
      for the operating system having delivered messages before the first
      poll.
    """

    def __init__(self, events=()):
        super().__init__()
        self._seed = list(events)
        self.created: list[object] = []

    def create_window(self, title, width, height):
        window = super().create_window(title, width, height)
        for event in self._seed:
            window.simulate_event(event)
        self.created.append(window)
        return window


def run_app(game, *, backend=None, **kwargs):
    """Run a game unpaced, returning the application."""
    kwargs.setdefault("max_fps", None)
    app = Application(game, backend=backend or RecordingBackend(), **kwargs)
    app.run()
    return app


class TestValidation(unittest.TestCase):
    def test_rejects_non_string_title(self):
        with self.assertRaises(TypeError):
            Application(Game(), title=123)

    def test_rejects_size_that_is_not_a_pair(self):
        for bad in ((100,), (100, 200, 300), 100):
            with self.subTest(size=bad), self.assertRaises((ValueError, TypeError)):
                Application(Game(), size=bad)

    def test_rejects_non_positive_dimensions(self):
        for bad in ((0, 100), (100, 0), (-1, 100), (100, -1)):
            with self.subTest(size=bad), self.assertRaises(ValueError):
                Application(Game(), size=bad)

    def test_rejects_non_integer_dimensions(self):
        with self.assertRaises(TypeError):
            Application(Game(), size=(100.5, 200))

    def test_reuses_clock_validation_for_max_fps(self):
        with self.assertRaises(ValueError):
            Application(Game(), max_fps=0)

    def test_accepts_valid_arguments(self):
        app = Application(Game(), title="ok", size=(320, 240), max_fps=30)
        self.assertEqual(app.clock.max_fps, 30)


class TestWindowCreation(unittest.TestCase):
    def test_creates_one_window(self):
        backend = RecordingBackend()
        run_app(RecordingGame(), backend=backend, title="T", size=(320, 240))
        self.assertEqual(len(backend.created), 1)

    def test_window_uses_requested_title_and_size(self):
        backend = RecordingBackend()
        run_app(RecordingGame(), backend=backend, title="My Game", size=(800, 600))
        window = backend.created[0]
        self.assertEqual(window.title, "My Game")
        self.assertEqual(window.size, (800, 600))

    def test_defaults(self):
        backend = RecordingBackend()
        run_app(RecordingGame(), backend=backend)
        window = backend.created[0]
        self.assertEqual(window.title, DEFAULT_TITLE)
        self.assertEqual(window.size, DEFAULT_SIZE)

    def test_default_title_and_size_match_the_documented_api(self):
        self.assertEqual(DEFAULT_TITLE, "TrjoLudus")
        self.assertEqual(DEFAULT_SIZE, (1280, 720))


class TestLifecycle(unittest.TestCase):
    def test_callback_order(self):
        game = RecordingGame(quit_after=2)
        run_app(game)
        self.assertEqual(
            game.calls, ["on_start", "on_update", "on_update", "on_stop"]
        )

    def test_on_start_is_called_exactly_once(self):
        game = RecordingGame(quit_after=3)
        run_app(game)
        self.assertEqual(game.calls.count("on_start"), 1)

    def test_on_stop_is_called_exactly_once(self):
        game = RecordingGame(quit_after=3)
        run_app(game)
        self.assertEqual(game.calls.count("on_stop"), 1)

    def test_on_start_precedes_every_update(self):
        game = RecordingGame(quit_after=2)
        run_app(game)
        self.assertEqual(game.calls[0], "on_start")

    def test_on_stop_follows_every_update(self):
        game = RecordingGame(quit_after=2)
        run_app(game)
        self.assertEqual(game.calls[-1], "on_stop")

    def test_window_exists_before_on_start(self):
        backend = RecordingBackend()

        class Checking(RecordingGame):
            def on_start(self):
                super().on_start()
                self.windows_at_start = len(backend.created)

        game = Checking()
        run_app(game, backend=backend)
        self.assertEqual(game.windows_at_start, 1)

    def test_runs_the_requested_number_of_frames(self):
        for frames in (1, 2, 5, 25):
            with self.subTest(frames=frames):
                game = RecordingGame(quit_after=frames)
                run_app(game)
                self.assertEqual(game.frames, frames)

    def test_dt_is_a_float(self):
        game = RecordingGame(quit_after=3)
        run_app(game)
        for dt in game.deltas:
            self.assertIsInstance(dt, float)

    def test_first_frame_has_zero_dt(self):
        game = RecordingGame(quit_after=2)
        run_app(game)
        self.assertEqual(game.deltas[0], 0.0)


class TestCleanup(unittest.TestCase):
    def test_window_is_closed_after_normal_shutdown(self):
        backend = RecordingBackend()
        run_app(RecordingGame(), backend=backend)
        self.assertTrue(backend.created[0].is_closed)

    def test_backend_is_shut_down_after_normal_shutdown(self):
        backend = RecordingBackend()
        run_app(RecordingGame(), backend=backend)
        self.assertTrue(backend.is_shut_down)

    def test_cleanup_order_is_stop_then_close_then_shutdown(self):
        order = []

        class OrderedBackend(NullBackend):
            def create_window(self, title, width, height):
                window = super().create_window(title, width, height)
                original_close = window.close

                def close():
                    order.append("window.close")
                    original_close()

                window.close = close
                return window

            def shutdown(self):
                order.append("backend.shutdown")
                super().shutdown()

        class StopRecording(RecordingGame):
            def on_stop(self):
                order.append("on_stop")
                super().on_stop()

        run_app(StopRecording(), backend=OrderedBackend())
        self.assertEqual(order, ["on_stop", "window.close", "backend.shutdown"])


class TestEventDispatch(unittest.TestCase):
    def test_events_reach_the_game(self):
        backend = RecordingBackend([WindowResized(640, 480)])
        game = RecordingGame(quit_after=1)
        run_app(game, backend=backend)
        self.assertEqual(game.events, [WindowResized(640, 480)])

    def test_event_order_is_preserved(self):
        seeded = [
            WindowResized(1, 1),
            WindowResized(2, 2),
            WindowResized(3, 3),
            WindowCloseRequested(),
        ]
        game = RecordingGame(quit_after=1)
        run_app(game, backend=RecordingBackend(seeded))
        self.assertEqual(game.events, seeded)

    def test_events_are_dispatched_before_the_first_update(self):
        game = RecordingGame(quit_after=1)
        run_app(game, backend=RecordingBackend([WindowResized(1, 1)]))
        self.assertEqual(game.calls, ["on_start", "on_event", "on_update", "on_stop"])

    def test_no_events_means_no_on_event_calls(self):
        game = RecordingGame(quit_after=2)
        run_app(game)
        self.assertEqual(game.events, [])
        self.assertNotIn("on_event", game.calls)

    def test_events_are_not_redelivered(self):
        game = RecordingGame(quit_after=3)
        run_app(game, backend=RecordingBackend([WindowResized(1, 1)]))
        self.assertEqual(len(game.events), 1)

    def test_only_platform_neutral_events_cross_the_boundary(self):
        game = RecordingGame(quit_after=1)
        run_app(game, backend=RecordingBackend([WindowResized(9, 9)]))
        for event in game.events:
            self.assertIsInstance(event, trjoludus.Event)


class TestCloseRequestBehaviour(unittest.TestCase):
    """The engine must not act on a close request by itself."""

    def test_close_request_alone_does_not_stop_the_loop(self):
        game = RecordingGame(quit_after=3)
        run_app(game, backend=RecordingBackend([WindowCloseRequested()]))
        self.assertEqual(game.frames, 3)

    def test_a_game_that_handles_it_does_stop(self):
        class Closing(RecordingGame):
            def on_event(self, event):
                super().on_event(event)
                if isinstance(event, WindowCloseRequested):
                    self.quit()

        game = Closing(quit_after=100)
        run_app(game, backend=RecordingBackend([WindowCloseRequested()]))
        self.assertEqual(game.frames, 0)
        self.assertEqual(game.calls, ["on_start", "on_event", "on_stop"])


class TestQuitTiming(unittest.TestCase):
    def test_quit_before_run_skips_every_frame(self):
        game = RecordingGame(quit_after=5)
        game.quit()
        run_app(game)
        self.assertEqual(game.frames, 0)
        self.assertEqual(game.calls, ["on_start", "on_stop"])

    def test_quit_during_on_start_skips_every_frame(self):
        class QuittingEarly(RecordingGame):
            def on_start(self):
                super().on_start()
                self.quit()

        game = QuittingEarly(quit_after=5)
        run_app(game)
        self.assertEqual(game.frames, 0)
        self.assertEqual(game.calls, ["on_start", "on_stop"])

    def test_quit_during_on_event_skips_that_frames_update(self):
        class QuittingOnEvent(RecordingGame):
            def on_event(self, event):
                super().on_event(event)
                self.quit()

        game = QuittingOnEvent(quit_after=5)
        run_app(game, backend=RecordingBackend([WindowResized(1, 1)]))
        self.assertEqual(game.frames, 0)
        self.assertNotIn("on_update", game.calls)

    def test_quit_during_on_event_still_delivers_the_rest_of_the_batch(self):
        """Events already polled happened; delivery must not depend on order."""

        class QuittingOnFirstEvent(RecordingGame):
            def on_event(self, event):
                super().on_event(event)
                self.quit()

        seeded = [WindowResized(1, 1), WindowResized(2, 2), WindowCloseRequested()]
        game = QuittingOnFirstEvent(quit_after=5)
        run_app(game, backend=RecordingBackend(seeded))
        self.assertEqual(game.events, seeded)
        self.assertEqual(game.frames, 0)

    def test_quit_during_on_update_stops_after_that_frame(self):
        game = RecordingGame(quit_after=1)
        run_app(game)
        self.assertEqual(game.frames, 1)

    def test_quit_after_the_loop_has_stopped_is_harmless(self):
        class QuittingInStop(RecordingGame):
            def on_stop(self):
                super().on_stop()
                self.quit()

        game = QuittingInStop(quit_after=1)
        run_app(game)
        self.assertEqual(game.calls, ["on_start", "on_update", "on_stop"])


class TestFailureCleanup(unittest.TestCase):
    class Boom(Exception):
        pass

    def _run_expecting_boom(self, game, backend):
        with self.assertRaises(self.Boom):
            Application(game, backend=backend, max_fps=None).run()

    def test_on_start_failure_still_cleans_up(self):
        class Failing(RecordingGame):
            def on_start(self):
                super().on_start()
                raise TestFailureCleanup.Boom

        backend = RecordingBackend()
        self._run_expecting_boom(Failing(), backend)
        self.assertTrue(backend.created[0].is_closed)
        self.assertTrue(backend.is_shut_down)

    def test_on_start_failure_does_not_call_on_stop(self):
        """on_stop pairs with a successful on_start, never a failed one."""

        class Failing(RecordingGame):
            def on_start(self):
                super().on_start()
                raise TestFailureCleanup.Boom

        game = Failing()
        self._run_expecting_boom(game, RecordingBackend())
        self.assertNotIn("on_stop", game.calls)

    def test_on_update_failure_still_cleans_up(self):
        class Failing(RecordingGame):
            def on_update(self, dt):
                super().on_update(dt)
                raise TestFailureCleanup.Boom

        backend = RecordingBackend()
        game = Failing()
        self._run_expecting_boom(game, backend)
        self.assertTrue(backend.is_shut_down)

    def test_on_update_failure_calls_on_stop(self):
        class Failing(RecordingGame):
            def on_update(self, dt):
                super().on_update(dt)
                raise TestFailureCleanup.Boom

        game = Failing()
        self._run_expecting_boom(game, RecordingBackend())
        self.assertIn("on_stop", game.calls)

    def test_on_event_failure_still_cleans_up(self):
        class Failing(RecordingGame):
            def on_event(self, event):
                super().on_event(event)
                raise TestFailureCleanup.Boom

        backend = RecordingBackend([WindowResized(1, 1)])
        game = Failing()
        self._run_expecting_boom(game, backend)
        self.assertTrue(backend.is_shut_down)
        self.assertIn("on_stop", game.calls)

    def test_original_exception_is_not_swallowed(self):
        class Failing(RecordingGame):
            def on_update(self, dt):
                raise TestFailureCleanup.Boom("original")

        with self.assertRaises(TestFailureCleanup.Boom) as caught:
            Application(Failing(), backend=RecordingBackend(), max_fps=None).run()
        self.assertEqual(str(caught.exception), "original")

    def test_failing_on_stop_does_not_prevent_cleanup(self):
        class Failing(RecordingGame):
            def on_stop(self):
                super().on_stop()
                raise TestFailureCleanup.Boom

        backend = RecordingBackend()
        with self.assertRaises(TestFailureCleanup.Boom):
            Application(Failing(quit_after=1), backend=backend, max_fps=None).run()
        self.assertTrue(backend.is_shut_down)


class TestClockIntegration(unittest.TestCase):
    def test_application_uses_a_clock(self):
        app = Application(Game(), max_fps=None)
        self.assertIsInstance(app.clock, Clock)

    def test_clock_is_configured_from_max_fps(self):
        self.assertEqual(Application(Game(), max_fps=30).clock.max_fps, 30)
        self.assertIsNone(Application(Game(), max_fps=None).clock.max_fps)

    def test_default_max_fps_is_sixty(self):
        self.assertEqual(Application(Game()).clock.max_fps, 60)

    def test_clock_ticks_once_per_frame(self):
        game = RecordingGame(quit_after=4)
        app = run_app(game)
        self.assertEqual(app.clock.frame_count, game.frames)

    def test_deltas_come_from_the_clock(self):
        """The last dt a game saw must be the clock's own last delta."""
        game = RecordingGame(quit_after=3)
        app = run_app(game)
        self.assertEqual(game.deltas[-1], app.clock.delta)

    def test_elapsed_matches_the_sum_of_deltas(self):
        game = RecordingGame(quit_after=5)
        app = run_app(game)
        self.assertAlmostEqual(app.clock.elapsed, sum(game.deltas))

    def test_application_has_no_second_timing_mechanism(self):
        """Timing lives in Clock; the application must not duplicate it."""
        import trjoludus.app as app_module

        source = Path(app_module.__file__).read_text(encoding="utf-8")
        for forbidden in ("perf_counter", "monotonic", "time.sleep", "import time"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_paced_run_actually_paces(self):
        game = RecordingGame(quit_after=2)
        app = run_app(game, max_fps=200)
        self.assertGreater(app.clock.elapsed, 0.0)


class TestRunFunction(unittest.TestCase):
    def test_run_is_exposed_publicly(self):
        self.assertIs(trjoludus.run, run)

    def test_run_drives_the_full_lifecycle(self):
        game = RecordingGame(quit_after=2)
        run(game, max_fps=None)
        self.assertEqual(
            game.calls, ["on_start", "on_update", "on_update", "on_stop"]
        )

    def test_run_accepts_title_and_size(self):
        game = RecordingGame(quit_after=1)
        run(game, title="Named", size=(640, 480), max_fps=None)
        self.assertEqual(game.frames, 1)

    def test_run_validates_arguments(self):
        with self.assertRaises(ValueError):
            run(RecordingGame(), size=(0, 100))

    def test_run_requires_no_backend_or_window_from_the_game(self):
        """The documented entry point: a game and nothing else."""
        game = RecordingGame(quit_after=1)
        run(game, max_fps=None)
        self.assertEqual(game.frames, 1)


class TestHeadless(unittest.TestCase):
    def test_full_lifecycle_without_a_graphical_environment(self):
        env = {k: v for k, v in os.environ.items() if k not in GRAPHICAL_ENV_VARS}
        env["PYTHONPATH"] = PACKAGE_PARENT
        script = (
            "import os\n"
            f"assert not any(v in os.environ for v in {GRAPHICAL_ENV_VARS!r})\n"
            "import trjoludus as tl\n"
            "class G(tl.Game):\n"
            "    calls = []\n"
            "    frames = 0\n"
            "    def on_start(self): self.calls.append('start')\n"
            "    def on_update(self, dt):\n"
            "        self.frames += 1\n"
            "        assert isinstance(dt, float)\n"
            "        if self.frames >= 3: self.quit()\n"
            "    def on_stop(self): self.calls.append('stop')\n"
            "g = G()\n"
            "tl.run(g, title='headless', size=(320, 240), max_fps=None)\n"
            "assert g.frames == 3, g.frames\n"
            "assert g.calls == ['start', 'stop'], g.calls\n"
            "print('ok')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
