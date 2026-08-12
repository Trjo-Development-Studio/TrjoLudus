"""Tests for the Game base class.

Game is deliberately independent of Application: it holds no window, no
backend and no loop, so everything here runs without either.
"""

import unittest

import trjoludus
from trjoludus.events import WindowCloseRequested, WindowResized
from trjoludus.game import Game


class TestDefaults(unittest.TestCase):
    """A game must be able to override only what it cares about."""

    def setUp(self):
        self.game = Game()

    def test_on_start_does_nothing(self):
        self.assertIsNone(self.game.on_start())

    def test_on_event_does_nothing(self):
        self.assertIsNone(self.game.on_event(WindowResized(1, 1)))

    def test_on_update_does_nothing(self):
        self.assertIsNone(self.game.on_update(0.016))

    def test_on_stop_does_nothing(self):
        self.assertIsNone(self.game.on_stop())

    def test_close_request_is_not_acted_on_by_default(self):
        """The engine treats closing as a request; the game decides."""
        self.game.on_event(WindowCloseRequested())
        self.assertFalse(self.game._quit_requested)


class TestQuit(unittest.TestCase):
    def test_starts_without_a_quit_request(self):
        self.assertFalse(Game()._quit_requested)

    def test_requests_shutdown(self):
        game = Game()
        game.quit()
        self.assertTrue(game._quit_requested)

    def test_is_idempotent(self):
        game = Game()
        game.quit()
        game.quit()
        self.assertTrue(game._quit_requested)

    def test_request_is_per_instance(self):
        first, second = Game(), Game()
        first.quit()
        self.assertTrue(first._quit_requested)
        self.assertFalse(second._quit_requested)

    def test_works_without_calling_super_init(self):
        """A subclass with its own __init__ must not break quit()."""

        class Subclass(Game):
            def __init__(self):
                self.value = 1  # deliberately no super().__init__()

        game = Subclass()
        game.quit()
        self.assertTrue(game._quit_requested)


class TestOverriding(unittest.TestCase):
    def test_callbacks_can_be_overridden(self):
        calls = []

        class Overriding(Game):
            def on_start(self):
                calls.append("on_start")

            def on_event(self, event):
                calls.append(("on_event", event))

            def on_update(self, dt):
                calls.append(("on_update", dt))

            def on_stop(self):
                calls.append("on_stop")

        game = Overriding()
        game.on_start()
        game.on_event(WindowResized(2, 3))
        game.on_update(0.5)
        game.on_stop()

        self.assertEqual(
            calls,
            [
                "on_start",
                ("on_event", WindowResized(2, 3)),
                ("on_update", 0.5),
                "on_stop",
            ],
        )

    def test_a_game_can_quit_from_a_callback(self):
        """The documented pattern for honouring a close request."""

        class Closing(Game):
            def on_event(self, event):
                if isinstance(event, WindowCloseRequested):
                    self.quit()

        game = Closing()
        game.on_event(WindowResized(1, 1))
        self.assertFalse(game._quit_requested)

        game.on_event(WindowCloseRequested())
        self.assertTrue(game._quit_requested)


class TestPublicApi(unittest.TestCase):
    def test_game_is_exposed(self):
        self.assertIs(trjoludus.Game, Game)

    def test_has_no_draw_callback_yet(self):
        """on_draw() arrives in Milestone 3, with the renderer."""
        self.assertFalse(hasattr(Game, "on_draw"))

    def test_has_no_input_callbacks_yet(self):
        for name in ("on_key_down", "on_key_up", "on_mouse_move", "on_mouse_down"):
            self.assertFalse(hasattr(Game, name), name)


if __name__ == "__main__":
    unittest.main()
