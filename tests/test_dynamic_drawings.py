"""Tests for changing a drawing after it has been made.

Two kinds of checking happen here. Most tests draw into a
:class:`~trjoludus.rendering_python.Framebuffer` and count pixels, because that is where
a change either happened or did not. The rest run a real game on the null
backend and read the frames it handed to the window, which proves a change
made in ``on_update`` reaches the screen on the very next frame rather than
only living in the engine's own state.

Everything is headless. Nothing waits for input.
"""

import unittest

from trjoludus import Game, color, draw, font
from trjoludus.app import Application
from trjoludus.events import MouseButtonPressed, MouseMoved
from trjoludus.platform.null import NullBackend
from trjoludus import ui as ui_module
from trjoludus.rendering_python import DEFAULT_CLEAR_COLOUR, Framebuffer
from trjoludus.ui import UiError, current_ui


class RecordingBackend(NullBackend):
    """Null backend that keeps every frame and can inject mouse events."""

    def __init__(self, script=()):
        super().__init__()
        self.script = list(script)
        self.frames = []
        self.polls = 0

    def create_window(self, title, width, height):
        window = super().create_window(title, width, height)
        backend = self
        poll = window.poll_events
        present = window.present

        def poll_events():
            backend.polls += 1
            for when, event in list(backend.script):
                if backend.polls >= when:
                    window.simulate_event(event)
                    backend.script.remove((when, event))
            return poll()

        def recording_present(pixels, width, height):
            present(pixels, width, height)
            backend.frames.append(bytes(pixels))

        window.poll_events = poll_events
        window.present = recording_present
        return window


def pixel_in(frame, width, x, y):
    """The ``(red, green, blue)`` at a point of a presented BGRA frame."""
    index = (y * width + x) * 4
    blue, green, red, _ = frame[index:index + 4]
    return (red, green, blue)


class DrawingTestCase(unittest.TestCase):
    def setUp(self):
        current_ui().clear()
        self.addCleanup(current_ui().clear)
        self.buffer = Framebuffer(60, 30)

    # --- drawing straight into a framebuffer ------------------------------

    def paint(self):
        """Draw every list as it is now and return the buffer."""
        self.buffer.clear()
        current_ui().render(self.buffer)
        return self.buffer

    def pixel(self, x, y):
        index = (y * self.buffer.width + x) * 4
        blue, green, red, _ = self.buffer.pixels[index:index + 4]
        return (red, green, blue)

    def lit(self):
        """Every pixel that is not the background, and what colour it is."""
        found = {}
        for y in range(self.buffer.height):
            for x in range(self.buffer.width):
                colour = self.pixel(x, y)
                if colour != DEFAULT_CLEAR_COLOUR:
                    found[(x, y)] = colour
        return found

    # --- running a real game ----------------------------------------------

    def play(self, build, act, frames=3, script=(), size=(60, 30)):
        """Run a game that changes its UI, and return the frames it drew.

        ``act(subject, frame_number)`` runs each update. The engine draws once
        before the first update, so ``frames[0]`` is the untouched UI and
        ``frames[n]`` is what the *n*th update produced.
        """
        backend = RecordingBackend(script)
        answers = []

        class G(Game):
            number = 0

            def on_start(self):
                self.subject = build()

            def on_update(self, dt):
                answers.append(act(self.subject, self.number))
                self.number += 1
                if self.number >= frames:
                    self.quit()

        Application(G(), size=size, max_fps=None, backend=backend).run()
        return backend.frames, answers


class TestChangingText(DrawingTestCase):
    def test_the_text_changes(self):
        label = draw.list("hud").text(0, 0, "Score: 0", color.white)
        label.set.text("Score: 100")
        self.assertEqual(label.message, "Score: 100")

    def test_the_new_text_is_what_gets_drawn(self):
        label = draw.list("hud").text(0, 0, "AA", color.white)
        self.paint()
        both = len(self.lit())

        label.set.text("A")
        self.paint()
        # The same glyph twice, then once: exactly half the pixels remain.
        self.assertEqual(len(self.lit()), both // 2)
        self.assertGreater(both, 0)

    def test_longer_text_lights_more_pixels(self):
        label = draw.list("hud").text(0, 0, "A", color.white)
        self.paint()
        short = len(self.lit())

        label.set.text("AAAA")
        self.paint()
        self.assertEqual(len(self.lit()), short * 4)

    def test_the_old_text_is_gone_rather_than_drawn_underneath(self):
        label = draw.list("hud").text(0, 0, "MMMM", color.white)
        self.paint()
        far_edge = max(x for (x, _) in self.lit())

        label.set.text("M")
        self.paint()
        self.assertLess(max(x for (x, _) in self.lit()), far_edge)

    def test_empty_text_draws_nothing(self):
        label = draw.list("hud").text(0, 0, "hello", color.white)
        label.set.text("")
        self.paint()
        self.assertEqual(self.lit(), {})

    def test_the_bounds_follow_the_new_text(self):
        label = draw.list("hud").text(5, 5, "A", color.white)
        narrow = label.bounds

        label.set.text("AAAA")
        self.assertGreater(label.bounds[2], narrow[2])
        self.assertEqual(label.bounds[:2], (5, 5))
        self.assertEqual(label.bounds[3], narrow[3])  # same height

    def test_the_measured_size_matches_the_font(self):
        label = draw.list("hud").text(0, 0, "x", color.white)
        label.set.text("longer words")
        width, height = font.measure("longer words")
        self.assertEqual(label.bounds, (0, 0, width, height))

    def test_text_must_be_a_string(self):
        label = draw.list("hud").text(0, 0, "hi", color.white)
        with self.assertRaises(TypeError) as caught:
            label.set.text(100)
        self.assertIn("must be a string", str(caught.exception))
        self.assertEqual(label.message, "hi")

    def test_a_rectangle_has_no_text(self):
        button = draw.list("hud").rect(0, 0, 10, 10, color.blue)
        with self.assertRaises(UiError) as caught:
            button.set.text("nope")
        message = str(caught.exception)
        self.assertIn("rectangle has no text", message)
        self.assertIn("color, scale", message)

    def test_a_line_has_no_text(self):
        line = draw.list("hud").line(0, 0, 10, 10, color.blue)
        with self.assertRaises(UiError):
            line.set.text("nope")


class TestChangingColour(DrawingTestCase):
    def test_a_rectangle_changes_colour_on_screen(self):
        box = draw.list("hud").rect(2, 2, 4, 4, color.blue)
        self.paint()
        self.assertEqual(self.pixel(3, 3), color.blue)

        box.set.color(color.red)
        self.paint()
        self.assertEqual(self.pixel(3, 3), color.red)
        self.assertEqual(set(self.lit().values()), {color.red})

    def test_text_changes_colour_on_screen(self):
        label = draw.list("hud").text(0, 0, "A", color.white)
        self.paint()
        self.assertEqual(set(self.lit().values()), {color.white})

        label.set.color(color.green)
        self.paint()
        self.assertEqual(set(self.lit().values()), {color.green})

    def test_a_line_changes_colour_on_screen(self):
        line = draw.list("hud").line(0, 5, 10, 5, color.blue)
        line.set.color(color.yellow)
        self.paint()
        self.assertEqual(set(self.lit().values()), {color.yellow})

    def test_the_colour_is_checked(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        for bad in ("blue", (300, 0, 0), (0, 0), None):
            with self.subTest(bad=bad):
                with self.assertRaises((TypeError, ValueError)):
                    box.set.color(bad)
        self.assertEqual(box.colour, color.blue)

    def test_a_plain_tuple_works(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        box.set.color((12, 34, 56))
        self.paint()
        self.assertEqual(self.pixel(1, 1), (12, 34, 56))


class TestChangingScale(DrawingTestCase):
    def test_scaling_after_creation_draws_it_bigger(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        self.paint()
        self.assertEqual(len(self.lit()), 16)

        box.set.scale(2)
        self.paint()
        self.assertEqual(len(self.lit()), 64)

    def test_shrinking_after_creation(self):
        box = draw.list("hud").rect(0, 0, 8, 8, color.blue)
        box.set.scale(0.5)
        self.paint()
        self.assertEqual(len(self.lit()), 16)

    def test_scaled_text_covers_more_pixels(self):
        label = draw.list("hud").text(0, 0, "A", color.white)
        self.paint()
        normal = len(self.lit())

        label.set.scale(3)
        self.paint()
        self.assertEqual(len(self.lit()), normal * 9)

    def test_add_and_remove_scale_still_work(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        box.add.scale(1.5)
        self.assertEqual(box.scale, 2.5)
        box.remove.scale(0.5)
        self.assertEqual(box.scale, 2.0)

    def test_scaling_back_to_normal_restores_the_pixels(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        self.paint()
        before = self.lit()

        box.set.scale(2)
        box.set.scale(1)
        self.paint()
        self.assertEqual(self.lit(), before)

    def test_scale_is_checked(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        with self.assertRaises(ValueError):
            box.set.scale(0)
        with self.assertRaises(ValueError):
            box.set.scale(-1)
        with self.assertRaises(TypeError):
            box.set.scale("big")
        self.assertEqual(box.scale, 1.0)

    def test_removing_more_scale_than_there_is_is_refused(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        with self.assertRaises(ValueError) as caught:
            box.remove.scale(2)
        self.assertIn("greater than zero", str(caught.exception))
        self.assertEqual(box.scale, 1.0)


class TestMoving(DrawingTestCase):
    def test_moving_a_rectangle_moves_its_pixels(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        box.move.x(10)
        box.move.y(5)
        self.paint()
        self.assertEqual(self.pixel(11, 6), color.blue)
        self.assertEqual(self.pixel(1, 1), DEFAULT_CLEAR_COLOUR)

    def test_moving_is_relative_and_adds_up(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        box.move.x(5)
        box.move.x(5)
        box.move.y(-2)
        self.assertEqual(box.position, (10, -2))

    def test_moving_text(self):
        label = draw.list("hud").text(0, 0, "A", color.white)
        label.move.x(20)
        self.assertEqual(label.position, (20, 0))
        self.assertEqual(label.bounds[0], 20)

    def test_moving_a_line_moves_both_ends(self):
        line = draw.list("hud").line(0, 0, 10, 4, color.blue)
        line.move.x(3)
        line.move.y(2)
        self.assertEqual((line.x, line.y), (3, 2))
        self.assertEqual((line.end_x, line.end_y), (13, 6))

    def test_movement_may_be_fractional(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        box.move.x(1.5)
        self.assertEqual(box.position, (1.5, 0))

    def test_movement_must_still_be_a_number(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        with self.assertRaises(TypeError):
            box.move.x("1")
        self.assertEqual(box.position, (0, 0))

    def test_position_cannot_be_added_to_or_removed_from(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        for namespace, name in ((box.add, "add"), (box.remove, "remove")):
            for attribute in ("x", "y", "position"):
                with self.subTest(namespace=name, attribute=attribute):
                    self.assertFalse(hasattr(namespace, attribute))
        # Relative movement has a word already, and it is not "add".
        self.assertFalse(hasattr(box.set, "position"))


class TestUnsupportedProperties(DrawingTestCase):
    def test_only_scale_can_be_added_and_removed(self):
        menu = draw.list("hud")
        box = menu.rect(0, 0, 4, 4, color.blue)
        label = menu.text(0, 0, "A", color.white)
        for drawing in (box, label):
            for namespace in (drawing.add, drawing.remove):
                self.assertTrue(hasattr(namespace, "scale"))
                self.assertFalse(hasattr(namespace, "color"))
                self.assertFalse(hasattr(namespace, "text"))

    def test_what_set_offers(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        offered = {name for name in dir(box.set) if not name.startswith("_")}
        self.assertEqual(offered, {"x", "y", "scale", "color", "text"})

    def test_each_kind_lists_what_it_has(self):
        menu = draw.list("hud")
        self.assertEqual(menu.rect(0, 0, 4, 4, color.blue).PROPERTIES["rect"],
                         ("x", "y", "color", "scale"))
        self.assertEqual(menu.line(0, 0, 4, 4, color.blue).PROPERTIES["line"],
                         ("x", "y", "color", "scale"))
        self.assertEqual(menu.text(0, 0, "a", color.blue).PROPERTIES["text"],
                         ("x", "y", "text", "color", "scale"))

    def test_the_error_says_what_to_use_instead(self):
        line = draw.list("hud").line(0, 0, 4, 4, color.blue)
        with self.assertRaises(UiError) as caught:
            line.set.text("hello")
        message = str(caught.exception)
        self.assertIn("A line has no text", message)
        self.assertIn("text drawings", message)


class TestChangingRepeatedly(DrawingTestCase):
    def test_many_changes_in_a_row(self):
        label = draw.list("hud").text(0, 0, "0", color.white)
        for number in range(20):
            label.set.text(f"Score: {number}")
            label.set.color((number * 10, 0, 0))
        self.assertEqual(label.message, "Score: 19")
        self.assertEqual(label.colour, (190, 0, 0))
        self.paint()
        self.assertEqual(set(self.lit().values()), {(190, 0, 0)})

    def test_changing_everything_at_once(self):
        label = draw.list("hud").text(1, 1, "hi", color.white)
        label.set.text("bye")
        label.set.color(color.red)
        label.set.scale(2)
        label.move.x(4)
        width, height = font.measure("bye")
        self.assertEqual(label.bounds, (5, 1, 5 + width * 2, 1 + height * 2))
        self.paint()
        self.assertEqual(set(self.lit().values()), {color.red})

    def test_the_drawing_stays_in_its_list_in_the_same_place(self):
        menu = draw.list("hud")
        first = menu.rect(0, 0, 4, 4, color.blue)
        second = menu.rect(0, 0, 4, 4, color.red)
        first.set.color(color.green)
        first.set.scale(3)
        self.assertEqual(menu.drawings(), (first, second))
        # Still drawn first, so the red one still covers it.
        self.paint()
        self.assertEqual(self.pixel(1, 1), color.red)

    def test_setters_return_the_drawing(self):
        label = draw.list("hud").text(0, 0, "a", color.white)
        self.assertIs(label.set.text("b"), label)
        self.assertIs(label.set.color(color.red), label)
        self.assertIs(label.set.scale(2), label)
        self.assertIs(label.add.scale(1), label)
        self.assertIs(label.remove.scale(1), label)
        self.assertIs(label.move.x(1), label)
        self.assertIs(label.move.y(1), label)


class TestVisibility(DrawingTestCase):
    def test_changing_a_hidden_drawing_then_showing_it(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        box.hide()
        box.set.color(color.red)
        box.set.scale(2)
        self.paint()
        self.assertEqual(self.lit(), {})

        box.show()
        self.paint()
        self.assertEqual(len(self.lit()), 64)
        self.assertEqual(set(self.lit().values()), {color.red})

    def test_a_hidden_drawing_still_answers_about_itself(self):
        label = draw.list("hud").text(0, 0, "A", color.white)
        label.hide()
        label.set.text("AAAA")
        self.assertEqual(label.message, "AAAA")
        self.assertGreater(label.bounds[2], 0)
        self.assertFalse(label.showing)

    def test_changing_a_drawing_in_a_hidden_list(self):
        menu = draw.list("hud")
        box = menu.rect(0, 0, 4, 4, color.blue)
        menu.hide()
        box.set.color(color.red)
        self.paint()
        self.assertEqual(self.lit(), {})

        menu.show()
        self.paint()
        self.assertEqual(set(self.lit().values()), {color.red})


class TestGoneDrawings(DrawingTestCase):
    def cleared(self):
        menu = draw.list("hud")
        box = menu.rect(0, 0, 4, 4, color.blue)
        label = menu.text(0, 0, "a", color.white)
        menu.clear()
        return box, label

    def test_a_cleared_drawing_refuses_every_change(self):
        box, label = self.cleared()
        with self.assertRaises(UiError):
            label.set.text("nope")
        with self.assertRaises(UiError):
            box.set.color(color.red)
        with self.assertRaises(UiError):
            box.set.scale(2)
        with self.assertRaises(UiError):
            box.add.scale(1)
        with self.assertRaises(UiError):
            box.move.x(1)

    def test_the_error_explains_what_happened(self):
        box, _ = self.cleared()
        with self.assertRaises(UiError) as caught:
            box.set.color(color.red)
        self.assertIn("no longer part of 'hud'", str(caught.exception))

    def test_a_destroyed_lists_drawings_refuse_changes(self):
        menu = draw.list("hud")
        box = menu.rect(0, 0, 4, 4, color.blue)
        menu.destroy()
        with self.assertRaises(UiError):
            box.set.color(color.red)
        with self.assertRaises(UiError):
            box.move.y(1)

    def test_changes_refused_after_the_ui_is_cleared(self):
        box = draw.list("hud").rect(0, 0, 4, 4, color.blue)
        current_ui().clear()
        with self.assertRaises(UiError):
            box.set.scale(2)


class TestChangesReachTheScreen(DrawingTestCase):
    """Changes made while a game runs must show up on the next frame."""

    def test_a_colour_change_appears_in_the_next_frame(self):
        def build():
            return draw.list("hud").rect(0, 0, 10, 10, color.blue)

        def act(box, number):
            if number == 0:
                box.set.color(color.red)

        frames, _ = self.play(build, act, frames=2)
        self.assertEqual(pixel_in(frames[0], 60, 5, 5), color.blue)
        self.assertEqual(pixel_in(frames[1], 60, 5, 5), color.red)

    def test_a_text_change_appears_in_the_next_frame(self):
        def build():
            return draw.list("hud").text(0, 0, "AAAA", color.white)

        def act(label, number):
            if number == 0:
                label.set.text("A")

        frames, _ = self.play(build, act, frames=2)
        tail = font.measure("AAA")[0]

        def any_lit_beyond(frame):
            return any(pixel_in(frame, 60, x, y) != DEFAULT_CLEAR_COLOUR
                       for x in range(tail, 60) for y in range(10))

        self.assertTrue(any_lit_beyond(frames[0]))
        self.assertFalse(any_lit_beyond(frames[1]))

    def test_a_scale_change_appears_in_the_next_frame(self):
        def build():
            return draw.list("hud").rect(0, 0, 5, 5, color.blue)

        def act(box, number):
            if number == 0:
                box.set.scale(3)

        frames, _ = self.play(build, act, frames=2)
        self.assertEqual(pixel_in(frames[0], 60, 10, 10), DEFAULT_CLEAR_COLOUR)
        self.assertEqual(pixel_in(frames[1], 60, 10, 10), color.blue)

    def test_a_move_appears_in_the_next_frame(self):
        def build():
            return draw.list("hud").rect(0, 0, 5, 5, color.blue)

        def act(box, number):
            if number == 0:
                box.move.x(20)

        frames, _ = self.play(build, act, frames=2)
        self.assertEqual(pixel_in(frames[0], 60, 2, 2), color.blue)
        self.assertEqual(pixel_in(frames[1], 60, 2, 2), DEFAULT_CLEAR_COLOUR)
        self.assertEqual(pixel_in(frames[1], 60, 22, 2), color.blue)

    def test_changing_every_frame_keeps_working(self):
        shades = [(60, 0, 0), (120, 0, 0), (180, 0, 0), (240, 0, 0)]

        def build():
            return draw.list("hud").rect(0, 0, 10, 10, color.blue)

        def act(box, number):
            box.set.color(shades[number])

        frames, _ = self.play(build, act, frames=4)
        drawn = [pixel_in(frame, 60, 5, 5) for frame in frames]
        # The frame before the first update still shows the original colour;
        # after that each update's shade appears in the frame that follows it.
        self.assertEqual(drawn, [color.blue] + shades)


class TestInteractionAfterChanges(DrawingTestCase):
    """A changed drawing is hovered and clicked where it is now."""

    def hover_at(self, build, act, x, y):
        answers = []

        def watch(subject, number):
            if number == 0:
                act(subject)
                return None
            return subject.mouse.hover()

        _, results = self.play(
            build, watch, frames=3,
            script=((1, MouseMoved(x=x, y=y)),),
        )
        answers.extend(result for result in results if result is not None)
        return answers

    def test_hover_follows_a_moved_drawing(self):
        def build():
            return draw.list("hud").rect(0, 0, 10, 10, color.blue)

        moved = self.hover_at(build, lambda box: box.move.x(20), 25, 5)
        self.assertTrue(all(moved))

    def test_the_old_place_stops_being_hoverable(self):
        def build():
            return draw.list("hud").rect(0, 0, 10, 10, color.blue)

        left = self.hover_at(build, lambda box: box.move.x(20), 5, 5)
        self.assertFalse(any(left))

    def test_hover_follows_a_scaled_drawing(self):
        def build():
            return draw.list("hud").rect(0, 0, 5, 5, color.blue)

        grown = self.hover_at(build, lambda box: box.set.scale(4), 15, 15)
        self.assertTrue(all(grown))

    def test_hover_follows_new_text(self):
        def build():
            return draw.list("hud").text(0, 0, "A", color.white)

        far = font.measure("AAA")[0]
        wider = self.hover_at(build, lambda label: label.set.text("AAAA"),
                              far, 2)
        self.assertTrue(all(wider))

    def test_a_hidden_drawing_is_not_hovered_after_changing(self):
        def build():
            return draw.list("hud").rect(0, 0, 10, 10, color.blue)

        def change(box):
            box.set.scale(2)
            box.hide()

        self.assertFalse(any(self.hover_at(build, change, 5, 5)))

    def test_clicking_a_moved_drawing(self):
        def build():
            return draw.list("hud").rect(0, 0, 10, 10, color.blue)

        def act(box, number):
            if number == 0:
                box.move.x(20)
                return None
            return box.mouse.clicked()

        _, results = self.play(
            build, act, frames=3,
            script=((2, MouseButtonPressed(button="left", x=25, y=5)),),
        )
        self.assertIn(True, results)

    def test_a_click_where_it_used_to_be_misses(self):
        def build():
            return draw.list("hud").rect(0, 0, 10, 10, color.blue)

        def act(box, number):
            if number == 0:
                box.move.x(20)
                return None
            return box.mouse.clicked()

        _, results = self.play(
            build, act, frames=3,
            script=((2, MouseButtonPressed(button="left", x=5, y=5)),),
        )
        self.assertNotIn(True, results)

    def test_growing_on_hover_does_not_flicker(self):
        """The classic pattern: grow while hovered, shrink when not."""
        def build():
            return draw.list("hud").rect(0, 0, 20, 20, color.blue)

        def act(box, number):
            hovered = box.mouse.hover()
            box.set.scale(1.5 if hovered else 1.0)
            return hovered

        _, results = self.play(
            build, act, frames=6,
            script=((1, MouseMoved(x=10, y=10)),),
        )
        # Once the pointer is inside, it stays hovered: growing must not
        # move the drawing out from under the pointer.
        self.assertEqual(results[-3:], [True, True, True])


class TestOtherWindows(DrawingTestCase):
    def other_window_list(self, name):
        menu = draw.list(name)
        menu._window = object()
        return menu

    def test_a_drawing_in_another_window_still_changes(self):
        menu = self.other_window_list("elsewhere")
        label = menu.text(0, 0, "a", color.white)
        label.set.text("changed")
        label.set.color(color.red)
        label.set.scale(2)
        self.assertEqual(label.message, "changed")
        self.assertEqual(label.colour, color.red)
        self.assertEqual(label.scale, 2.0)

    def test_changing_it_does_not_make_it_hoverable_here(self):
        def build():
            return self.other_window_list("elsewhere").rect(
                30, 10, 20, 20, color.blue)

        def act(box, number):
            if number == 0:
                box.set.scale(2)
                return None
            return box.mouse.hover()

        _, results = self.play(
            build, act, frames=3,
            script=((1, MouseMoved(x=40, y=20)),),
        )
        self.assertNotIn(True, results)

    def test_a_changed_drawing_elsewhere_does_not_cover_this_window(self):
        def build():
            here = draw.list("here").rect(0, 0, 20, 20, color.blue)
            there = self.other_window_list("elsewhere").rect(
                0, 0, 20, 20, color.red)
            there.set.scale(3)  # would cover it, if windows did not matter
            return here

        def act(here, number):
            return here.mouse.hover()

        _, results = self.play(
            build, act, frames=3,
            script=((1, MouseMoved(x=10, y=10)),),
        )
        self.assertIn(True, results)


class TestNullBackend(DrawingTestCase):
    def test_a_game_that_changes_its_ui_runs_with_no_display(self):
        backend = RecordingBackend()

        class G(Game):
            number = 0

            def on_start(self):
                self.label = draw.list("hud").text(0, 0, "0", color.white)

            def on_update(self, dt):
                self.number += 1
                self.label.set.text(f"frame {self.number}")
                self.label.set.color((self.number * 20, 0, 0))
                if self.number >= 5:
                    self.quit()

        game = G()
        Application(game, size=(60, 30), max_fps=None, backend=backend).run()
        self.assertEqual(game.label.message, "frame 5")
        # One frame before the first update, then one per update.
        self.assertEqual(len(backend.frames), 6)

    def test_changes_work_before_a_game_ever_runs(self):
        label = draw.list("hud").text(0, 0, "a", color.white)
        label.set.text("no game needed")
        label.set.color(color.red)
        self.assertEqual(label.message, "no game needed")


class TestImportIsolation(unittest.TestCase):
    def test_the_ui_module_needs_no_platform_code(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c",
             "import sys, trjoludus.ui as ui;"
             "print(int('ctypes' in sys.modules));"
             "print(int(any(n.startswith('trjoludus.platform.linux')"
             " or n.startswith('trjoludus.platform.windows')"
             " for n in sys.modules)))"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        ctypes_loaded, backend_loaded = result.stdout.split()
        self.assertEqual(ctypes_loaded, "0", "ui.py must not need ctypes")
        self.assertEqual(backend_loaded, "0",
                         "ui.py must not pull in a real backend")

    def test_the_ui_module_imports_nothing_platform_specific(self):
        import ast
        import pathlib

        source = pathlib.Path(ui_module.__file__).read_text()
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertNotIn("ctypes", imported)
        self.assertFalse([name for name in imported
                          if "platform" in name or name in ("os", "sys")],
                         f"ui.py imports {imported}")

    def test_changing_drawings_needs_no_display(self):
        import os
        import subprocess
        import sys

        environment = dict(os.environ)
        environment.pop("DISPLAY", None)
        environment.pop("WAYLAND_DISPLAY", None)
        result = subprocess.run(
            [sys.executable, "-c",
             "from trjoludus import color, draw;"
             "d = draw.list('m').text(0, 0, 'a', color.white);"
             "d.set.text('b'); d.set.color(color.red); d.set.scale(2);"
             "d.move.x(3);"
             "print(d.message, d.scale, d.position)"],
            capture_output=True, text=True, timeout=60, env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "b 2.0 (3, 0)")


if __name__ == "__main__":
    unittest.main()
