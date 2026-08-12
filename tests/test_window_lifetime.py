"""An application stops when its last window is gone.

The rule is general, not a keyboard fix: the loop and every blocking engine
call ask the backend whether anything still keeps the application alive. A
window can vanish without a close request -- the desktop can destroy it -- and
no close event is coming, so nothing may wait on one.

The null backend is deliberately exempt: it has no window on screen to lose,
and headless runs must not end because a simulated one was closed.

:class:`GraphicalBackend` below is a stand-in for a real graphical backend --
a null backend with the graphical answer to that one question. It exists so
the rule can be tested deterministically without a display; the real backends
are checked against the same rule in test_x11.py.
"""

import unittest

import trjoludus
from trjoludus import Game, input, key, keyboard
from trjoludus.app import Application
from trjoludus.events import KeyPressed
from trjoludus.platform.null import NullBackend

#: Nothing here may run for long. A hang is the bug under test, so a test that
#: hangs must fail rather than stall the suite.
FRAME_LIMIT = 500


class GraphicalBackend(NullBackend):
    """A backend whose windows govern the application's lifetime."""

    @property
    def keeps_application_alive(self) -> bool:
        return any(not window.is_closed for window in self._windows)


class LifetimeTestCase(unittest.TestCase):
    def run_game(self, game, backend=None):
        backend = backend or GraphicalBackend()
        Application(game, size=(8, 8), max_fps=None, backend=backend).run()
        return backend


class TestLoopStopsWithTheLastWindow(LifetimeTestCase):
    def test_closing_the_only_window_stops_the_application(self):
        class G(Game):
            frames = 0

            def on_update(self, dt):
                self.frames += 1
                if self.frames == 3:
                    backend.windows[0].close()
                self.assertion_guard = self.frames < FRAME_LIMIT
                if self.frames >= FRAME_LIMIT:
                    self.quit()

        backend = GraphicalBackend()
        game = G()
        self.run_game(game, backend)
        self.assertEqual(game.frames, 3, "the loop ran on past the last window")

    def test_a_window_destroyed_without_a_close_request_still_stops_it(self):
        """No WindowCloseRequested is coming, so nothing may wait for one."""

        class G(Game):
            frames = 0
            saw_close_request = False

            def on_event(self, event):
                if isinstance(event, trjoludus.WindowCloseRequested):
                    self.saw_close_request = True

            def on_update(self, dt):
                self.frames += 1
                if self.frames == 2:
                    # Vanishes underneath the game; no event is produced.
                    backend.windows[0].close()
                if self.frames >= FRAME_LIMIT:
                    self.quit()

        backend = GraphicalBackend()
        game = G()
        self.run_game(game, backend)
        self.assertEqual(game.frames, 2)
        self.assertFalse(game.saw_close_request)

    def test_the_game_still_stops_itself_normally(self):
        """The new rule must not take over from quit()."""

        class G(Game):
            frames = 0

            def on_update(self, dt):
                self.frames += 1
                if self.frames == 2:
                    self.quit()

        game = G()
        self.run_game(game)
        self.assertEqual(game.frames, 2)

    def test_on_stop_still_runs_when_the_window_disappears(self):
        class G(Game):
            frames = 0
            stopped = False

            def on_update(self, dt):
                self.frames += 1
                if self.frames == 2:
                    backend.windows[0].close()
                if self.frames >= FRAME_LIMIT:
                    self.quit()

            def on_stop(self):
                self.stopped = True

        backend = GraphicalBackend()
        game = G()
        self.run_game(game, backend)
        self.assertTrue(game.stopped)
        self.assertTrue(backend.is_shut_down)


class TestMultipleWindows(LifetimeTestCase):
    def test_closing_one_of_two_windows_keeps_running(self):
        class G(Game):
            frames = 0

            def on_start(self):
                backend.create_window("second", 8, 8)

            def on_update(self, dt):
                self.frames += 1
                if self.frames == 2:
                    backend.windows[0].close()
                if self.frames >= 6:
                    self.quit()

        backend = GraphicalBackend()
        game = G()
        self.run_game(game, backend)
        self.assertEqual(game.frames, 6, "one window closing ended the run")

    def test_closing_the_last_window_stops_it(self):
        class G(Game):
            frames = 0

            def on_start(self):
                backend.create_window("second", 8, 8)

            def on_update(self, dt):
                self.frames += 1
                if self.frames == 2:
                    backend.windows[0].close()
                if self.frames == 4:
                    backend.windows[1].close()
                if self.frames >= FRAME_LIMIT:
                    self.quit()

        backend = GraphicalBackend()
        game = G()
        self.run_game(game, backend)
        self.assertEqual(game.frames, 4)

    def test_the_backend_reports_alive_until_the_last_one_goes(self):
        backend = GraphicalBackend()
        first = backend.create_window("a", 8, 8)
        second = backend.create_window("b", 8, 8)

        self.assertTrue(backend.keeps_application_alive)
        first.close()
        self.assertTrue(backend.keeps_application_alive)
        second.close()
        self.assertFalse(backend.keeps_application_alive)


class TestWaitingStopsToo(LifetimeTestCase):
    """The case that started this: a blocking call must not outlive the window."""

    def test_keyboard_wait_does_not_hang_when_the_window_disappears(self):
        class G(Game):
            returned = "never"

            def on_update(self, dt):
                backend.windows[0].close()
                keyboard.wait(input.key)
                self.returned = key.value
                self.quit()

        backend = GraphicalBackend()
        game = G()
        self.run_game(game, backend)
        self.assertIsNone(game.returned, "wait() did not give up")

    def test_a_wait_already_in_progress_gives_up(self):
        """The window goes while the game is blocked, not before."""

        class ClosingBackend(GraphicalBackend):
            def create_window(self, title, width, height):
                window = super().create_window(title, width, height)
                original = window.poll_events
                polls = []

                def poll_events():
                    polls.append(1)
                    if len(polls) >= 3:
                        window.close()
                    return original()

                window.poll_events = poll_events
                return window

        class G(Game):
            returned = "never"

            def on_update(self, dt):
                keyboard.wait(input.key)
                self.returned = key.value
                self.quit()

        game = G()
        self.run_game(game, ClosingBackend())
        self.assertIsNone(game.returned)

    def test_a_key_already_waiting_is_still_delivered(self):
        """Giving up must not throw away input that already arrived."""

        class Seeded(GraphicalBackend):
            def create_window(self, title, width, height):
                window = super().create_window(title, width, height)
                window.simulate_event(KeyPressed("W"))
                return window

        class G(Game):
            returned = "never"

            def on_update(self, dt):
                keyboard.wait(input.key)
                self.returned = key.value
                self.quit()

        game = G()
        self.run_game(game, Seeded())
        self.assertEqual(game.returned, "W")


class TestNullBackendIsExempt(unittest.TestCase):
    """Headless runs must not end because a simulated window was closed."""

    def test_the_null_backend_always_keeps_the_application_alive(self):
        backend = NullBackend()
        self.assertTrue(backend.keeps_application_alive)
        window = backend.create_window("t", 8, 8)
        self.assertTrue(backend.keeps_application_alive)
        window.close()
        self.assertTrue(backend.keeps_application_alive)

    def test_a_headless_game_runs_on_after_its_window_is_closed(self):
        class G(Game):
            frames = 0

            def on_update(self, dt):
                self.frames += 1
                if self.frames == 2:
                    backend.windows[0].close()
                if self.frames >= 5:
                    self.quit()

        backend = NullBackend()
        game = G()
        Application(game, size=(8, 8), max_fps=None, backend=backend).run()
        self.assertEqual(game.frames, 5)

    def test_a_headless_game_still_stops_when_it_asks_to(self):
        class G(Game):
            frames = 0

            def on_update(self, dt):
                self.frames += 1
                if self.frames == 3:
                    self.quit()

        game = G()
        Application(game, size=(8, 8), max_fps=None,
                    backend=NullBackend()).run()
        self.assertEqual(game.frames, 3)


class TestEveryBackendAnswersTheQuestion(unittest.TestCase):
    def test_the_contract_requires_it(self):
        from trjoludus.platform.base import PlatformBackend

        self.assertIn("keeps_application_alive",
                      PlatformBackend.__abstractmethods__)

    def test_every_backend_implements_it(self):
        from trjoludus.platform.linux.x11 import X11Backend
        from trjoludus.platform.windows.win32 import Win32Backend

        for backend in (NullBackend, X11Backend, Win32Backend):
            with self.subTest(backend=backend.__name__):
                self.assertIn("keeps_application_alive", dir(backend))
                self.assertEqual(backend.__abstractmethods__, frozenset())


if __name__ == "__main__":
    unittest.main()
