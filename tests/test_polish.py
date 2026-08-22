"""Tests for the polish pass: lifecycle, position, PNG damage, mouse meaning.

These are regression tests for things that were wrong or unstated rather than
for a new feature. Each one is here because the behaviour it checks was either
a bug (a game instance could only be run once) or a distinction that was true
in the code but not written down anywhere (``pressed`` versus ``button``).

Headless throughout. Nothing waits for input.
"""

import struct
import unittest
import zlib

from trjoludus import Game, color, draw, mouse
from trjoludus.app import Application
from trjoludus.events import (
    MouseButtonPressed,
    MouseButtonReleased,
    MouseMoved,
)
from trjoludus.image import ImageError, decode_png
from trjoludus.platform.null import NullBackend
from trjoludus.rendering_python import DEFAULT_CLEAR_COLOUR, Framebuffer
from trjoludus.scene import SceneError, current_scene
from trjoludus.ui import UiError, current_ui

SIGNATURE = b"\x89PNG\r\n\x1a\n"


def chunk(tag, body):
    """One well-formed PNG chunk, checksum and all."""
    return (struct.pack(">I", len(body)) + tag + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))


def ihdr(width, height, colour_type=6):
    """An IHDR body: size, 8 bits per channel, no interlacing."""
    return struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0)


def good_png(width=2, height=2):
    """A small, valid, opaque RGBA PNG."""
    stride = width * 4
    rows = b"".join(b"\x00" + bytes([10, 20, 30, 255]) * width
                    for _ in range(height))
    return (SIGNATURE
            + chunk(b"IHDR", ihdr(width, height))
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b""))


class TestRunningAGameTwice(unittest.TestCase):
    """A Game instance that quit must be able to run again."""

    def setUp(self):
        current_scene().clear()
        current_ui().clear()
        mouse._reset()
        self.addCleanup(current_scene().clear)
        self.addCleanup(current_ui().clear)
        self.addCleanup(mouse._reset)

    def run_game(self, game):
        Application(game, size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()

    def test_the_same_instance_runs_twice(self):
        class Counting(Game):
            runs = 0
            frames = 0

            def on_start(self):
                self.runs += 1

            def on_update(self, dt):
                self.frames += 1
                self.quit()

        game = Counting()
        self.run_game(game)
        self.run_game(game)
        self.assertEqual(game.runs, 2)
        self.assertEqual(game.frames, 2, "the second run did no frames")

    def test_the_second_run_gets_its_full_share_of_frames(self):
        class ThreeFrames(Game):
            def on_start(self):
                self.frames = 0

            def on_update(self, dt):
                self.frames += 1
                if self.frames >= 3:
                    self.quit()

        game = ThreeFrames()
        self.run_game(game)
        first = game.frames
        self.run_game(game)
        self.assertEqual(first, 3)
        self.assertEqual(game.frames, 3)

    def test_every_callback_happens_again(self):
        class Recording(Game):
            def __init__(self):
                self.calls = []

            def on_start(self):
                self.calls.append("start")

            def on_update(self, dt):
                self.calls.append("update")
                self.quit()

            def on_stop(self):
                self.calls.append("stop")

        game = Recording()
        self.run_game(game)
        self.run_game(game)
        self.assertEqual(game.calls, ["start", "update", "stop"] * 2)

    def test_the_request_is_readable_after_the_run(self):
        """Cleared as a run begins, not as it ends, so this still answers."""
        class Quitting(Game):
            def on_update(self, dt):
                self.quit()

        game = Quitting()
        self.run_game(game)
        self.assertTrue(game.quit_requested)

    def test_a_run_starts_with_no_request_outstanding(self):
        seen = []

        class Watching(Game):
            def on_start(self):
                seen.append(self.quit_requested)

            def on_update(self, dt):
                self.quit()

        game = Watching()
        self.run_game(game)
        self.run_game(game)
        self.assertEqual(seen, [False, False])

    def test_quitting_from_on_start_is_still_heard(self):
        """The clearing happens before on_start, so this must still stop."""
        class QuitsEarly(Game):
            frames = 0

            def on_start(self):
                self.quit()

            def on_update(self, dt):
                self.frames += 1

        game = QuitsEarly()
        self.run_game(game)
        self.assertEqual(game.frames, 0)

    def test_a_run_that_raised_can_still_be_run_again(self):
        class Breaking(Game):
            fail = True
            frames = 0

            def on_update(self, dt):
                if self.fail:
                    self.fail = False
                    raise RuntimeError("boom")
                self.frames += 1
                self.quit()

        game = Breaking()
        with self.assertRaises(RuntimeError):
            self.run_game(game)
        self.run_game(game)
        self.assertEqual(game.frames, 1)

    def test_the_second_run_starts_with_an_empty_scene_and_ui(self):
        class Building(Game):
            def on_start(self):
                draw.list("menu").rect(0, 0, 4, 4, color.blue)
                self.lists = len(current_ui()._lists)
                self.objects = len(current_scene())

            def on_update(self, dt):
                self.quit()

        game = Building()
        self.run_game(game)
        self.run_game(game)
        self.assertEqual((game.lists, game.objects), (1, 0))

    def test_the_application_never_touches_the_private_flag(self):
        """The reset belongs to Game; app.py reads the public answer only."""
        import pathlib

        from trjoludus import app

        source = pathlib.Path(app.__file__).read_text()
        self.assertNotIn("_quit_requested", source)
        self.assertIn("_begin_run", source)


class PositionTestCase(unittest.TestCase):
    def setUp(self):
        current_ui().clear()
        current_scene().clear()
        self.addCleanup(current_ui().clear)
        self.addCleanup(current_scene().clear)


class TestDrawingPosition(PositionTestCase):
    def box(self):
        return draw.list("menu").rect(10, 10, 20, 20, color.blue)

    def test_set_x_is_absolute(self):
        box = self.box()
        box.set.x(200)
        box.set.x(200)
        self.assertEqual(box.position, (200, 10), "set must not accumulate")

    def test_set_y_is_absolute(self):
        box = self.box()
        box.set.y(100)
        box.set.y(100)
        self.assertEqual(box.position, (10, 100))

    def test_move_is_relative(self):
        box = self.box()
        box.move.x(25)
        box.move.x(25)
        box.move.y(-10)
        self.assertEqual(box.position, (60, 0))

    def test_set_then_move(self):
        box = self.box()
        box.set.x(200).set.y(100)
        box.move.x(25).move.y(-10)
        self.assertEqual(box.position, (225, 90))

    def test_negative_and_zero_positions_are_allowed(self):
        box = self.box()
        box.set.x(-50)
        box.set.y(0)
        self.assertEqual(box.position, (-50, 0))

    def test_a_position_must_be_a_number(self):
        box = self.box()
        for bad in ("200", True, None):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    box.set.x(bad)
                with self.assertRaises(TypeError):
                    box.set.y(bad)
        self.assertEqual(box.position, (10, 10))

    def test_a_position_may_be_fractional(self):
        box = self.box()
        box.set.x(1.5)
        box.set.y(2.25)
        self.assertEqual(box.position, (1.5, 2.25))

    def test_setting_a_lines_position_moves_the_whole_line(self):
        line = draw.list("menu").line(0, 0, 10, 4, color.blue)
        line.set.x(100)
        line.set.y(50)
        self.assertEqual((line.x, line.y), (100, 50))
        self.assertEqual((line.end_x, line.end_y), (110, 54),
                         "the line must keep its shape")

    def test_the_values_a_drawing_does_not_own_stay_read_only(self):
        """Size, text, colour and kind are still set through `set`."""
        box = self.box()
        for attribute in ("width", "height", "message", "colour", "kind"):
            with self.subTest(attribute=attribute):
                with self.assertRaises(AttributeError):
                    setattr(box, attribute, 5)

    def test_assigning_a_position_is_checked_like_every_other_route(self):
        """x and y are assignable now, as a game object's are -- but every
        route still goes through the same check, so nothing can be written
        straight into a position."""
        box = self.box()
        for attribute in ("x", "y"):
            for bad in ("five", None, True, [1]):
                with self.subTest(attribute=attribute, value=bad):
                    with self.assertRaises(TypeError):
                        setattr(box, attribute, bad)
            with self.subTest(attribute=attribute, value="infinity"):
                with self.assertRaises(ValueError):
                    setattr(box, attribute, float("inf"))

    def test_assigning_a_position_does_what_set_does(self):
        box = self.box()
        box.x = 40
        box.y = 25
        self.assertEqual((box.x, box.y), (40, 25))
        self.assertEqual(box.position, (40, 25))

    def test_a_gone_drawing_refuses_to_be_assigned_to(self):
        box = self.box()
        current_ui().clear()
        with self.assertRaises(UiError):
            box.x = 10

    def test_a_gone_drawing_refuses_to_be_placed(self):
        box = self.box()
        current_ui().clear()
        with self.assertRaises(UiError):
            box.set.x(10)
        with self.assertRaises(UiError):
            box.set.y(10)

    def test_setters_return_the_drawing(self):
        box = self.box()
        self.assertIs(box.set.x(1), box)
        self.assertIs(box.set.y(1), box)


class TestGameObjectPosition(PositionTestCase):
    def setUp(self):
        super().setUp()
        # A tiny real image, so nothing here depends on a file on disk.
        from trjoludus.image import Image
        from trjoludus.scene import SceneObject
        image = Image(2, 2, bytes([0, 0, 0, 255]) * 4)
        current_scene().add(SceneObject("player", image, 10, 10))
        from trjoludus.scene import GameObject
        self.subject = GameObject("player")

    def test_set_x_is_absolute(self):
        self.subject.set.x(200)
        self.subject.set.x(200)
        self.assertEqual(self.subject.position, (200, 10))

    def test_set_y_is_absolute(self):
        self.subject.set.y(100)
        self.assertEqual(self.subject.position, (10, 100))

    def test_move_is_still_relative(self):
        self.subject.move.x(25)
        self.subject.move.x(25)
        self.assertEqual(self.subject.position, (60, 10))

    def test_assigning_x_still_works(self):
        """The spelling Step 2 shipped is not taken away."""
        self.subject.x = 300
        self.assertEqual(self.subject.x, 300)

    def test_both_spellings_agree(self):
        self.subject.x = 42
        by_assignment = self.subject.position
        self.subject.set.x(7)
        self.subject.set.x(42)
        self.assertEqual(self.subject.position, by_assignment)

    def test_a_position_must_be_a_number(self):
        for bad in ("200", True, None):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    self.subject.set.x(bad)

    def test_a_position_may_be_fractional(self):
        self.subject.set.x(1.5)
        self.assertEqual(self.subject.x, 1.5)

    def test_a_removed_object_refuses_to_be_placed(self):
        self.subject.destroy()
        with self.assertRaises(SceneError):
            self.subject.set.x(10)

    def test_drawings_and_objects_share_the_spelling(self):
        box = draw.list("menu").rect(0, 0, 4, 4, color.blue)
        for thing in (box, self.subject):
            with self.subTest(thing=type(thing).__name__):
                self.assertTrue(hasattr(thing.set, "x"))
                self.assertTrue(hasattr(thing.set, "y"))
                self.assertTrue(hasattr(thing.move, "x"))
                self.assertTrue(hasattr(thing.move, "y"))


class TestPositionReachesTheScreen(PositionTestCase):
    """Rendering and hit-testing must read the same current position."""

    def paint(self):
        buffer = Framebuffer(60, 40)
        buffer.clear()
        current_ui().render(buffer)
        return buffer

    def pixel(self, buffer, x, y):
        index = (y * buffer.width + x) * 4
        blue, green, red, _ = buffer.pixels[index:index + 4]
        return (red, green, blue)

    def test_set_x_moves_the_pixels(self):
        box = draw.list("menu").rect(0, 0, 5, 5, color.blue)
        box.set.x(30)
        buffer = self.paint()
        self.assertEqual(self.pixel(buffer, 2, 2), DEFAULT_CLEAR_COLOUR)
        self.assertEqual(self.pixel(buffer, 32, 2), color.blue)

    def test_move_moves_the_pixels(self):
        box = draw.list("menu").rect(0, 0, 5, 5, color.blue)
        box.move.x(20)
        box.move.y(10)
        buffer = self.paint()
        self.assertEqual(self.pixel(buffer, 22, 12), color.blue)

    def test_what_is_drawn_and_what_is_clickable_agree(self):
        box = draw.list("menu").rect(0, 0, 5, 5, color.blue)
        for x, y in ((30, 10), (0, 0), (55, 35), (12, 3)):
            with self.subTest(position=(x, y)):
                box.set.x(x)
                box.set.y(y)
                buffer = self.paint()
                left, top, right, bottom = box.bounds
                self.assertEqual(self.pixel(buffer, left, top), color.blue,
                                 "the top-left of the hitbox is not drawn")
                self.assertEqual(
                    self.pixel(buffer, right - 1, bottom - 1), color.blue,
                    "the bottom-right of the hitbox is not drawn")
                self.assertTrue(box.contains(left, top))
                self.assertFalse(box.contains(right, bottom))

    def test_scaling_and_placing_together_stay_in_step(self):
        box = draw.list("menu").rect(0, 0, 5, 5, color.blue)
        box.set.scale(3)
        box.set.x(20)
        buffer = self.paint()
        self.assertEqual(box.bounds, (20, 0, 35, 15))
        self.assertEqual(self.pixel(buffer, 34, 14), color.blue)
        self.assertEqual(self.pixel(buffer, 35, 15), DEFAULT_CLEAR_COLOUR)


class TestHitTestingFollowsPosition(PositionTestCase):
    """A placed drawing is hovered where it is now, in a running game."""

    def hover_after(self, place, x, y):
        answers = []
        backend = NullBackend()
        window_events = [MouseMoved(x=x, y=y)]

        class G(Game):
            count = 0

            def on_start(self):
                self.box = draw.list("menu").rect(0, 0, 10, 10, color.blue)
                place(self.box)

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    for event in window_events:
                        backend.windows[0].simulate_event(event)
                    return
                answers.append(self.box.mouse.hover())
                if self.count >= 3:
                    self.quit()

        Application(G(), size=(80, 60), max_fps=None, backend=backend).run()
        return answers

    def test_hover_finds_it_where_set_put_it(self):
        answers = self.hover_after(lambda box: box.set.x(40), 45, 5)
        self.assertTrue(all(answers), answers)

    def test_hover_misses_where_it_used_to_be(self):
        answers = self.hover_after(lambda box: box.set.x(40), 5, 5)
        self.assertFalse(any(answers), answers)

    def test_hover_finds_it_after_a_move(self):
        answers = self.hover_after(lambda box: box.move.y(30), 5, 35)
        self.assertTrue(all(answers), answers)


class TestMouseSemantics(unittest.TestCase):
    """pressed() is current state; button is the last input that was read."""

    def setUp(self):
        mouse._reset()
        current_ui().clear()
        self.addCleanup(mouse._reset)
        self.addCleanup(current_ui().clear)

    def observe(self, events, ask, frames=4):
        """Run a game, feed events on the first frame, ask on every frame."""
        answers = []
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_start(self):
                pass

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    for event in events:
                        backend.windows[0].simulate_event(event)
                    return
                answers.append(ask())
                if self.count >= frames:
                    self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        return answers

    def test_pressed_is_true_while_the_button_is_down(self):
        answers = self.observe(
            [MouseButtonPressed(button="LEFT", x=1, y=1)],
            lambda: mouse.pressed("LEFT"),
        )
        self.assertTrue(all(answers), answers)

    def test_pressed_goes_false_when_it_comes_up(self):
        answers = self.observe(
            [MouseButtonPressed(button="LEFT", x=1, y=1),
             MouseButtonReleased(button="LEFT", x=1, y=1)],
            lambda: mouse.pressed("LEFT"),
        )
        self.assertFalse(any(answers), answers)

    def test_reading_pressed_does_not_use_it_up(self):
        answers = self.observe(
            [MouseButtonPressed(button="LEFT", x=1, y=1)],
            lambda: (mouse.pressed("LEFT"), mouse.pressed("LEFT")),
        )
        self.assertTrue(all(first and second for first, second in answers))

    def test_button_is_none_until_input_is_read(self):
        answers = self.observe(
            [MouseButtonPressed(button="LEFT", x=1, y=1)],
            lambda: mouse.button,
        )
        self.assertEqual(answers, [None] * len(answers),
                         "button must not change until a wait reads a press")

    def test_button_names_what_the_wait_read(self):
        from trjoludus import input as input_module

        answers = []
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    backend.windows[0].simulate_event(
                        MouseButtonPressed(button="RIGHT", x=3, y=4))
                    return
                mouse.wait(input_module.mouse)
                answers.append((mouse.button, mouse.position))
                self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertEqual(answers, [("RIGHT", (3, 4))])

    def test_button_outlives_the_press_but_pressed_does_not(self):
        """The distinction, in one test."""
        from trjoludus import input as input_module

        answers = []
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    window = backend.windows[0]
                    window.simulate_event(
                        MouseButtonPressed(button="LEFT", x=1, y=1))
                    window.simulate_event(
                        MouseButtonReleased(button="LEFT", x=1, y=1))
                    return
                mouse.wait(input_module.mouse)
                answers.append((mouse.button, mouse.pressed("LEFT")))
                self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertEqual(answers, [("LEFT", False)])

    def test_pressed_still_rejects_an_unknown_button(self):
        with self.assertRaises(ValueError):
            mouse.pressed("SIDE")
        with self.assertRaises(TypeError):
            mouse.pressed(1)


class TestMalformedPng(unittest.TestCase):
    def test_a_good_png_still_decodes(self):
        image = decode_png(good_png())
        self.assertEqual(image.size, (2, 2))

    def test_not_a_png_at_all(self):
        with self.assertRaises(ImageError) as caught:
            decode_png(b"GIF89a and then some")
        self.assertIn("PNG signature", str(caught.exception))

    def test_nothing_after_the_signature(self):
        with self.assertRaises(ImageError) as caught:
            decode_png(SIGNATURE)
        self.assertIn("truncated", str(caught.exception))

    def test_half_a_chunk_header(self):
        with self.assertRaises(ImageError) as caught:
            decode_png(SIGNATURE + b"\x00\x00\x00")
        self.assertIn("truncated", str(caught.exception))

    def test_a_chunk_that_runs_past_the_end(self):
        good = good_png()
        # Claim the IHDR body is far longer than the file.
        broken = (SIGNATURE + struct.pack(">I", 5000) + b"IHDR"
                  + good[16:29] + b"\x00\x00\x00\x00")
        with self.assertRaises(ImageError) as caught:
            decode_png(broken)
        self.assertIn("past the end", str(caught.exception))

    def test_an_impossible_chunk_length(self):
        broken = (SIGNATURE + struct.pack(">I", 0xFFFFFFFF) + b"IDAT"
                  + b"\x00" * 8)
        with self.assertRaises(ImageError) as caught:
            decode_png(broken)
        self.assertIn("not a valid chunk length", str(caught.exception))

    def test_a_chunk_type_that_is_not_a_chunk_type(self):
        broken = (SIGNATURE + struct.pack(">I", 0) + b"\x00\x01\x02\x03"
                  + b"\x00" * 4)
        with self.assertRaises(ImageError) as caught:
            decode_png(broken)
        self.assertIn("malformed", str(caught.exception))

    def test_a_file_cut_off_partway_through(self):
        good = good_png()
        for cut in (20, 30, len(good) - 5, len(good) - 1):
            with self.subTest(cut=cut):
                with self.assertRaises(ImageError):
                    decode_png(good[:cut])

    def test_a_flipped_bit_in_the_body_is_caught(self):
        good = bytearray(good_png())
        good[20] ^= 0xFF                       # inside the IHDR body
        with self.assertRaises(ImageError) as caught:
            decode_png(bytes(good))
        self.assertIn("checksum", str(caught.exception))

    def test_a_flipped_bit_in_the_pixels_is_caught(self):
        good = bytearray(good_png())
        good[good.index(b"IDAT") + 6] ^= 0xFF   # inside the IDAT body
        with self.assertRaises(ImageError) as caught:
            decode_png(bytes(good))
        self.assertIn("checksum", str(caught.exception))

    def test_no_iend(self):
        without = good_png()
        without = without[:without.rindex(b"IEND") - 4]
        with self.assertRaises(ImageError) as caught:
            decode_png(without)
        self.assertIn("IEND", str(caught.exception))

    def test_a_file_that_does_not_start_with_ihdr(self):
        broken = (SIGNATURE + chunk(b"IDAT", b"nonsense")
                  + chunk(b"IEND", b""))
        with self.assertRaises(ImageError) as caught:
            decode_png(broken)
        self.assertIn("IHDR", str(caught.exception))

    def test_a_truncated_header_chunk(self):
        broken = (SIGNATURE + chunk(b"IHDR", b"\x00" * 5)
                  + chunk(b"IEND", b""))
        with self.assertRaises(ImageError) as caught:
            decode_png(broken)
        self.assertIn("truncated", str(caught.exception))

    def test_a_png_with_no_pixel_data(self):
        broken = (SIGNATURE
                  + chunk(b"IHDR", ihdr(2, 2))
                  + chunk(b"IEND", b""))
        with self.assertRaises(ImageError) as caught:
            decode_png(broken)
        self.assertIn("no image data", str(caught.exception))

    def test_pixel_data_that_is_not_deflate(self):
        broken = (SIGNATURE
                  + chunk(b"IHDR", ihdr(2, 2))
                  + chunk(b"IDAT", b"not compressed at all")
                  + chunk(b"IEND", b""))
        with self.assertRaises(ImageError) as caught:
            decode_png(broken)
        self.assertIn("corrupt", str(caught.exception))

    def test_too_few_pixels_for_the_stated_size(self):
        rows = b"\x00" + bytes([1, 2, 3, 4]) * 2       # one row, not two
        broken = (SIGNATURE
                  + chunk(b"IHDR", ihdr(2, 2))
                  + chunk(b"IDAT", zlib.compress(rows))
                  + chunk(b"IEND", b""))
        with self.assertRaises(ImageError) as caught:
            decode_png(broken)
        self.assertIn("truncated", str(caught.exception))

    def test_an_unknown_filter_type(self):
        rows = b"\x09" + bytes([1, 2, 3, 4]) * 2
        broken = (SIGNATURE
                  + chunk(b"IHDR", ihdr(2, 1))
                  + chunk(b"IDAT", zlib.compress(rows))
                  + chunk(b"IEND", b""))
        with self.assertRaises(ImageError) as caught:
            decode_png(broken)
        self.assertIn("filter type", str(caught.exception))

    def test_a_zero_sized_png(self):
        broken = (SIGNATURE
                  + chunk(b"IHDR", ihdr(0, 0))
                  + chunk(b"IEND", b""))
        with self.assertRaises(ImageError) as caught:
            decode_png(broken)
        self.assertIn("zero size", str(caught.exception))

    def test_every_failure_is_an_image_error(self):
        """No crash may reach a game as IndexError or struct.error."""
        good = good_png()
        for cut in range(len(SIGNATURE), len(good)):
            with self.subTest(cut=cut):
                try:
                    decode_png(good[:cut])
                except ImageError:
                    pass

    def test_random_damage_never_escapes_as_another_exception(self):
        good = good_png(4, 4)
        for position in range(8, len(good)):
            damaged = bytearray(good)
            damaged[position] ^= 0xA5
            with self.subTest(position=position):
                try:
                    decode_png(bytes(damaged))
                except ImageError:
                    pass


class TestMultiWindowGroundwork(unittest.TestCase):
    """The groundwork stays; the public model stays single-window."""

    def setUp(self):
        current_ui().clear()
        mouse._reset()
        self.addCleanup(current_ui().clear)
        self.addCleanup(mouse._reset)

    def test_input_records_the_window_it_came_from(self):
        from trjoludus.app import PendingInput

        self.assertIn("window", PendingInput.__slots__)

    def test_mouse_state_is_per_window(self):
        backend = NullBackend()
        seen = {}

        class G(Game):
            def on_update(self, dt):
                from trjoludus.app import current_application

                application = current_application()
                other = object()
                seen["default"] = application.mouse_state()
                seen["other"] = application.mouse_state(other)
                self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertIsNot(seen["default"], seen["other"])

    def test_a_drawing_list_can_belong_to_a_window(self):
        menu = draw.list("menu")
        self.assertIn("_window", type(menu).__slots__)

    def test_there_is_no_public_way_to_make_a_second_window(self):
        import trjoludus

        public = set(trjoludus.__all__)
        for name in ("window", "Window", "create_window", "windows"):
            self.assertNotIn(name, public)


if __name__ == "__main__":
    unittest.main()
