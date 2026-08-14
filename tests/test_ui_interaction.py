"""Tests for interactive UI: hover, clicking, scale and draw order.

All headless. Mouse events are injected through the null backend, so what a
player would experience is checked exactly rather than by hand.

Interaction depends on a running game -- it needs a window and a pointer -- so
these run a real Application. Every test that blocks provides its own way out;
none of them wait for input.
"""

import unittest

from trjoludus import Game, color, draw, mouse
from trjoludus.app import Application
from trjoludus.events import MouseButtonPressed, MouseButtonReleased, MouseMoved
from trjoludus.platform.null import NullBackend
from trjoludus.ui import Drawable, UiError, current_ui


class Backend(NullBackend):
    """Null backend that can put mouse events into its window."""

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


class InteractionTestCase(unittest.TestCase):
    def setUp(self):
        current_ui().clear()
        mouse._reset()
        self.addCleanup(current_ui().clear)
        self.addCleanup(mouse._reset)

    def probe(self, build, ask, script=(), frames=1, size=(200, 200)):
        """Build some UI, then ask something about it while a game runs.

        ``build`` makes the UI and returns whatever the question needs;
        ``ask`` is called each frame with that, and its answers collected.
        """
        answers = []
        backend = Backend(script)

        class G(Game):
            count = 0

            def on_start(self):
                self.subject = build()

            def on_update(self, dt):
                self.count += 1
                answers.append(ask(self.subject))
                if self.count >= frames:
                    self.quit()

        Application(G(), size=size, max_fps=None, backend=backend).run()
        return answers


class TestHover(InteractionTestCase):
    def button(self):
        return draw.list("menu").rect(20, 20, 60, 40, color.blue)

    def test_inside_the_bounds(self):
        answers = self.probe(self.button, lambda b: b.mouse.hover(),
                             script=[(1, MouseMoved(30, 30))])
        self.assertTrue(answers[0])

    def test_outside_the_bounds(self):
        answers = self.probe(self.button, lambda b: b.mouse.hover(),
                             script=[(1, MouseMoved(150, 150))])
        self.assertFalse(answers[0])

    def test_the_edges(self):
        """Top-left is inside; one past bottom-right is not."""
        for point, expected in (((20, 20), True), ((79, 59), True),
                                ((19, 20), False), ((20, 19), False),
                                ((80, 40), False), ((40, 60), False)):
            with self.subTest(point=point):
                answers = self.probe(
                    self.button, lambda b: b.mouse.hover(),
                    script=[(1, MouseMoved(*point))])
                self.assertEqual(answers[0], expected)

    def test_moving_away_stops_the_hover(self):
        answers = self.probe(
            self.button, lambda b: b.mouse.hover(),
            script=[(1, MouseMoved(30, 30)), (2, MouseMoved(150, 150))],
            frames=2)
        self.assertEqual(answers, [True, False])

    def test_a_hidden_drawing_cannot_be_hovered(self):
        def build():
            button = draw.list("menu").rect(20, 20, 60, 40, color.blue)
            button.hide()
            return button

        answers = self.probe(build, lambda b: b.mouse.hover(),
                             script=[(1, MouseMoved(30, 30))])
        self.assertFalse(answers[0])

    def test_a_drawing_in_a_hidden_list_cannot_be_hovered(self):
        def build():
            menu = draw.list("menu")
            button = menu.rect(20, 20, 60, 40, color.blue)
            menu.hide()
            return button

        answers = self.probe(build, lambda b: b.mouse.hover(),
                             script=[(1, MouseMoved(30, 30))])
        self.assertFalse(answers[0])

    def test_showing_it_again_restores_hover(self):
        def build():
            button = draw.list("menu").rect(20, 20, 60, 40, color.blue)
            button.hide()
            button.show()
            return button

        answers = self.probe(build, lambda b: b.mouse.hover(),
                             script=[(1, MouseMoved(30, 30))])
        self.assertTrue(answers[0])

    def test_text_can_be_hovered(self):
        def build():
            return draw.list("menu").text(10, 10, "Play", color.white)

        answers = self.probe(build, lambda b: b.mouse.hover(),
                             script=[(1, MouseMoved(12, 12))])
        self.assertTrue(answers[0])

    def test_no_hover_without_a_running_game(self):
        menu = draw.list("menu")
        button = menu.rect(0, 0, 50, 50, color.blue)
        self.assertFalse(button.mouse.hover())


class TestScale(InteractionTestCase):
    def test_scale_starts_at_one(self):
        self.assertEqual(draw.list("m").rect(0, 0, 10, 10, color.blue).scale,
                         1.0)

    def test_set_scale(self):
        button = draw.list("m").rect(0, 0, 10, 10, color.blue)
        button.set.scale(1.25)
        self.assertEqual(button.scale, 1.25)

    def test_add_scale(self):
        button = draw.list("m").rect(0, 0, 10, 10, color.blue)
        button.add.scale(0.25)
        self.assertEqual(button.scale, 1.25)

    def test_remove_scale(self):
        button = draw.list("m").rect(0, 0, 10, 10, color.blue)
        button.remove.scale(0.25)
        self.assertEqual(button.scale, 0.75)

    def test_scaling_returns_the_drawing(self):
        button = draw.list("m").rect(0, 0, 10, 10, color.blue)
        self.assertIs(button.set.scale(2), button)

    def test_bounds_grow_with_scale(self):
        button = draw.list("m").rect(10, 10, 20, 20, color.blue)
        self.assertEqual(button.bounds, (10, 10, 30, 30))
        button.set.scale(2)
        self.assertEqual(button.bounds, (10, 10, 50, 50))

    def test_scaling_keeps_the_corner_where_it_was_put(self):
        button = draw.list("m").rect(40, 50, 10, 10, color.blue)
        button.set.scale(3)
        left, top, _, _ = button.bounds
        self.assertEqual((left, top), (40, 50))

    def test_hover_uses_the_scaled_bounds(self):
        """A point outside at normal size is inside once it grows."""

        def build():
            button = draw.list("m").rect(20, 20, 20, 20, color.blue)
            button.set.scale(3)
            return button

        answers = self.probe(build, lambda b: b.mouse.hover(),
                             script=[(1, MouseMoved(70, 70))])
        self.assertTrue(answers[0])

    def test_shrinking_takes_a_point_back_outside(self):
        def build():
            button = draw.list("m").rect(20, 20, 40, 40, color.blue)
            button.set.scale(0.25)
            return button

        answers = self.probe(build, lambda b: b.mouse.hover(),
                             script=[(1, MouseMoved(50, 50))])
        self.assertFalse(answers[0])

    def test_text_bounds_scale(self):
        label = draw.list("m").text(0, 0, "AB", color.white)
        normal = label.bounds
        label.set.scale(2)
        bigger = label.bounds
        self.assertGreater(bigger[2] - bigger[0], normal[2] - normal[0])
        self.assertGreater(bigger[3] - bigger[1], normal[3] - normal[1])

    def test_a_scale_must_be_a_number(self):
        button = draw.list("m").rect(0, 0, 10, 10, color.blue)
        for bad in ("2", None, True):
            with self.subTest(value=bad), self.assertRaises(TypeError):
                button.set.scale(bad)

    def test_a_scale_must_be_positive(self):
        button = draw.list("m").rect(0, 0, 10, 10, color.blue)
        for bad in (0, -1):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                button.set.scale(bad)

    def test_removing_too_much_scale_is_refused(self):
        button = draw.list("m").rect(0, 0, 10, 10, color.blue)
        with self.assertRaises(ValueError):
            button.remove.scale(1.0)
        self.assertEqual(button.scale, 1.0)

    def test_position_is_absolute_or_relative_and_nothing_else(self):
        """set puts it somewhere, move nudges it; add and remove do neither."""
        button = draw.list("m").rect(0, 0, 10, 10, color.blue)
        for attribute in ("x", "y"):
            with self.subTest(attribute=attribute):
                self.assertTrue(hasattr(button.set, attribute))
                self.assertTrue(hasattr(button.move, attribute))
                self.assertFalse(hasattr(button.add, attribute))
                self.assertFalse(hasattr(button.remove, attribute))


class TestClick(InteractionTestCase):
    def button(self):
        return draw.list("menu").rect(20, 20, 60, 40, color.blue)

    def test_a_press_on_the_drawing_counts(self):
        answers = self.probe(
            self.button, lambda b: b.mouse.clicked(),
            script=[(1, MouseButtonPressed("LEFT", 30, 30))])
        self.assertTrue(answers[0])

    def test_a_press_elsewhere_does_not(self):
        answers = self.probe(
            self.button, lambda b: b.mouse.clicked(),
            script=[(1, MouseButtonPressed("LEFT", 150, 150))])
        self.assertFalse(answers[0])

    def test_hovering_without_pressing_is_not_a_click(self):
        answers = self.probe(self.button, lambda b: b.mouse.clicked(),
                             script=[(1, MouseMoved(30, 30))])
        self.assertFalse(answers[0])

    def test_a_held_button_does_not_stay_clicked(self):
        """The press is a moment; holding must not repeat it every frame."""
        answers = self.probe(
            self.button, lambda b: b.mouse.clicked(),
            script=[(1, MouseButtonPressed("LEFT", 30, 30))],
            frames=4)
        self.assertEqual(answers, [True, False, False, False])

    def test_the_button_is_still_held_while_it_stays_down(self):
        """Clicking is a moment; holding is state, and both stay true to that."""
        answers = self.probe(
            self.button,
            lambda b: (b.mouse.clicked(), mouse.pressed("LEFT")),
            script=[(1, MouseButtonPressed("LEFT", 30, 30))],
            frames=3)
        self.assertEqual(answers, [(True, True), (False, True), (False, True)])

    def test_releasing_and_pressing_again_is_a_second_click(self):
        answers = self.probe(
            self.button, lambda b: b.mouse.clicked(),
            script=[(1, MouseButtonPressed("LEFT", 30, 30)),
                    (2, MouseButtonReleased("LEFT", 30, 30)),
                    (3, MouseButtonPressed("LEFT", 30, 30))],
            frames=4)
        self.assertEqual(answers.count(True), 2)

    def test_asking_twice_in_a_frame_gives_the_same_answer(self):
        """It is a question about the frame, not something that is used up."""
        answers = self.probe(
            self.button,
            lambda b: (b.mouse.clicked(), b.mouse.clicked()),
            script=[(1, MouseButtonPressed("LEFT", 30, 30))])
        self.assertEqual(answers[0], (True, True))

    def test_any_button_counts(self):
        for name in ("LEFT", "RIGHT", "MIDDLE"):
            with self.subTest(button=name):
                answers = self.probe(
                    self.button, lambda b: b.mouse.clicked(),
                    script=[(1, MouseButtonPressed(name, 30, 30))])
                self.assertTrue(answers[0])

    def test_a_hidden_drawing_cannot_be_clicked(self):
        def build():
            button = draw.list("menu").rect(20, 20, 60, 40, color.blue)
            button.hide()
            return button

        answers = self.probe(build, lambda b: b.mouse.clicked(),
                             script=[(1, MouseButtonPressed("LEFT", 30, 30))])
        self.assertFalse(answers[0])

    def test_scaled_bounds_are_used(self):
        def build():
            button = draw.list("m").rect(20, 20, 20, 20, color.blue)
            button.set.scale(3)
            return button

        answers = self.probe(build, lambda b: b.mouse.clicked(),
                             script=[(1, MouseButtonPressed("LEFT", 70, 70))])
        self.assertTrue(answers[0])

    def test_no_click_without_a_running_game(self):
        button = draw.list("m").rect(0, 0, 50, 50, color.blue)
        self.assertFalse(button.mouse.clicked())


class TestOverlapping(InteractionTestCase):
    def stack(self):
        """Two overlapping rectangles; the second is drawn on top."""
        menu = draw.list("menu")
        under = menu.rect(0, 0, 100, 100, color.gray)
        over = menu.rect(20, 20, 40, 40, color.blue)
        return under, over

    def test_the_topmost_is_hovered(self):
        answers = self.probe(self.stack,
                             lambda pair: (pair[0].mouse.hover(),
                                           pair[1].mouse.hover()),
                             script=[(1, MouseMoved(30, 30))])
        self.assertEqual(answers[0], (False, True))

    def test_the_one_underneath_is_hovered_where_it_is_not_covered(self):
        answers = self.probe(self.stack,
                             lambda pair: (pair[0].mouse.hover(),
                                           pair[1].mouse.hover()),
                             script=[(1, MouseMoved(80, 80))])
        self.assertEqual(answers[0], (True, False))

    def test_the_topmost_receives_the_click(self):
        answers = self.probe(self.stack,
                             lambda pair: (pair[0].mouse.clicked(),
                                           pair[1].mouse.clicked()),
                             script=[(1, MouseButtonPressed("LEFT", 30, 30))])
        self.assertEqual(answers[0], (False, True))

    def test_hiding_the_top_one_uncovers_the_other(self):
        def build():
            under, over = self.stack()
            over.hide()
            return under, over

        answers = self.probe(build,
                             lambda pair: (pair[0].mouse.hover(),
                                           pair[1].mouse.hover()),
                             script=[(1, MouseMoved(30, 30))])
        self.assertEqual(answers[0], (True, False))

    def test_a_later_list_is_on_top_of_an_earlier_one(self):
        """Draw order across lists is creation order, as it is on screen."""

        def build():
            under = draw.list("under").rect(0, 0, 100, 100, color.gray)
            over = draw.list("over").rect(0, 0, 100, 100, color.blue)
            return under, over

        answers = self.probe(build,
                             lambda pair: (pair[0].mouse.hover(),
                                           pair[1].mouse.hover()),
                             script=[(1, MouseMoved(50, 50))])
        self.assertEqual(answers[0], (False, True))

    def test_hiding_a_covering_list_uncovers_what_is_below(self):
        def build():
            under = draw.list("under").rect(0, 0, 100, 100, color.gray)
            top_list = draw.list("over")
            over = top_list.rect(0, 0, 100, 100, color.blue)
            top_list.hide()
            return under, over

        answers = self.probe(build,
                             lambda pair: (pair[0].mouse.hover(),
                                           pair[1].mouse.hover()),
                             script=[(1, MouseMoved(50, 50))])
        self.assertEqual(answers[0], (True, False))

    def test_topmost_at_reports_nothing_where_there_is_nothing(self):
        draw.list("menu").rect(0, 0, 10, 10, color.blue)
        self.assertIsNone(current_ui().topmost_at(500, 500))


class TestWindowOwnership(InteractionTestCase):
    """Only the mouse in a drawing's own window may touch it."""

    def test_a_drawing_belongs_to_the_games_window_by_default(self):
        seen = {}

        class G(Game):
            def on_start(self):
                from trjoludus.app import current_application

                app = current_application()
                button = draw.list("m").rect(0, 0, 10, 10, color.blue)
                seen["window"] = button.list.window_or(app)
                seen["app_window"] = app._window

            def on_update(self, dt):
                self.quit()

        Application(G(), size=(64, 64), max_fps=None, backend=Backend()).run()
        self.assertIs(seen["window"], seen["app_window"])

    def test_a_drawing_in_another_window_is_not_hovered(self):
        backend = Backend([(1, MouseMoved(30, 30))])
        answers = []

        class G(Game):
            def on_start(self):
                other = backend.create_window("second", 64, 64)
                menu = current_ui().add("elsewhere", window=other)
                self.button = menu.rect(20, 20, 60, 40, color.blue)

            def on_update(self, dt):
                answers.append(self.button.mouse.hover())
                self.quit()

        Application(G(), size=(200, 200), max_fps=None, backend=backend).run()
        self.assertFalse(answers[0], "another window's pointer hovered it")

    def test_a_click_in_another_window_does_not_reach_it(self):
        backend = Backend()
        answers = []

        class G(Game):
            def on_start(self):
                other = backend.create_window("second", 64, 64)
                other.simulate_event(MouseButtonPressed("LEFT", 30, 30))
                menu = current_ui().add("elsewhere", window=other)
                self.button = menu.rect(20, 20, 60, 40, color.blue)

            def on_update(self, dt):
                answers.append(self.button.mouse.clicked())
                self.quit()

        Application(G(), size=(200, 200), max_fps=None, backend=backend).run()
        self.assertFalse(answers[0], "another window's click reached it")

    def test_a_drawing_elsewhere_does_not_cover_one_here(self):
        backend = Backend([(1, MouseMoved(30, 30))])
        answers = []

        class G(Game):
            def on_start(self):
                mine = draw.list("mine").rect(0, 0, 100, 100, color.gray)
                other = backend.create_window("second", 64, 64)
                # Drawn later, so it would be on top if windows were ignored.
                current_ui().add("theirs", window=other).rect(
                    0, 0, 100, 100, color.blue)
                self.mine = mine

            def on_update(self, dt):
                answers.append(self.mine.mouse.hover())
                self.quit()

        Application(G(), size=(200, 200), max_fps=None, backend=backend).run()
        self.assertTrue(answers[0], "a drawing in another window blocked it")


class TestDestroyed(InteractionTestCase):
    def test_a_drawing_in_a_destroyed_list_cannot_be_used(self):
        menu = draw.list("menu")
        button = menu.rect(0, 0, 10, 10, color.blue)
        menu.destroy()
        for action in (button.mouse.hover, button.mouse.clicked,
                       lambda: button.set.scale(2), button.show, button.hide):
            with self.subTest(), self.assertRaises(UiError):
                action()

    def test_a_cleared_drawing_cannot_be_used(self):
        menu = draw.list("menu")
        button = menu.rect(0, 0, 10, 10, color.blue)
        menu.clear()
        with self.assertRaises(UiError) as caught:
            button.mouse.hover()
        self.assertIn("cleared or destroyed", str(caught.exception))

    def test_a_destroyed_drawing_is_not_found_by_the_mouse(self):
        menu = draw.list("menu")
        menu.rect(0, 0, 100, 100, color.blue)
        menu.destroy()
        self.assertIsNone(current_ui().topmost_at(50, 50))


class TestRendering(InteractionTestCase):
    """Scale has to change what is drawn, not just what can be hovered."""

    def frame(self, build, size=(60, 60)):
        windows = []

        class Recording(Backend):
            def create_window(self, title, width, height):
                window = super().create_window(title, width, height)
                windows.append(window)
                return window

        class G(Game):
            def on_start(self):
                build()

            def on_update(self, dt):
                self.quit()

        Application(G(), size=size, max_fps=None, backend=Recording()).run()
        return windows[0]

    def pixel(self, window, x, y):
        width = window.last_frame_size[0]
        i = (y * width + x) * 4
        blue, green, red, _ = window.last_frame[i:i + 4]
        return (red, green, blue)

    def test_a_scaled_rectangle_is_drawn_bigger(self):
        def build():
            draw.list("m").rect(5, 5, 10, 10, color.blue).set.scale(3)

        window = self.frame(build)
        self.assertEqual(self.pixel(window, 30, 30), color.blue)
        self.assertNotEqual(self.pixel(window, 40, 40), color.blue)

    def test_an_unscaled_rectangle_keeps_its_size(self):
        def build():
            draw.list("m").rect(5, 5, 10, 10, color.blue)

        window = self.frame(build)
        self.assertEqual(self.pixel(window, 10, 10), color.blue)
        self.assertNotEqual(self.pixel(window, 20, 20), color.blue)

    def test_scaled_text_covers_more_pixels(self):
        def count(scale):
            def build():
                label = draw.list("m").text(2, 2, "A", color.white)
                label.set.scale(scale)

            window = self.frame(build)
            width, height = window.last_frame_size
            return sum(
                1
                for y in range(height)
                for x in range(width)
                if self.pixel(window, x, y) == color.white
            )

        self.assertGreater(count(3), count(1))

    def test_a_hidden_drawing_is_not_rendered(self):
        def build():
            draw.list("m").rect(0, 0, 20, 20, color.blue).hide()

        window = self.frame(build)
        self.assertNotEqual(self.pixel(window, 5, 5), color.blue)


class TestNullBackend(InteractionTestCase):
    def test_interaction_works_headlessly(self):
        answers = self.probe(
            lambda: draw.list("m").rect(0, 0, 50, 50, color.blue),
            lambda b: (b.mouse.hover(), b.mouse.clicked()),
            script=[(1, MouseButtonPressed("LEFT", 10, 10))])
        self.assertEqual(answers[0], (True, True))

    def test_the_null_backend_needs_no_display(self):
        import os

        self.assertTrue(
            True, f"ran with DISPLAY={os.environ.get('DISPLAY')!r}"
        )


class TestDrawableShape(unittest.TestCase):
    def test_a_drawing_offers_what_the_documented_style_needs(self):
        for name in ("mouse", "set", "add", "remove", "scale", "visible",
                     "bounds", "show", "hide"):
            with self.subTest(member=name):
                self.assertTrue(hasattr(Drawable, name))


if __name__ == "__main__":
    unittest.main()
