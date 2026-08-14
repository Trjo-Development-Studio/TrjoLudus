"""Tests for colours, drawing and drawing lists.

All headless. Drawing is composition into a frame buffer, so what a game would
see on screen can be checked pixel by pixel without a display; the X11 tests
only have to prove those pixels reach a window.
"""

import unittest

import trjoludus
from trjoludus import Game, color, draw
from trjoludus.app import Application
from trjoludus.font import CHARACTER_HEIGHT, CHARACTER_WIDTH, columns_for, measure
from trjoludus.platform.null import NullBackend
from trjoludus.render import DEFAULT_CLEAR_COLOUR, Framebuffer
from trjoludus.ui import DrawList, UiError, current_ui


class UiTestCase(unittest.TestCase):
    """Leaves the shared UI empty, so tests cannot affect each other."""

    def setUp(self):
        current_ui().clear()
        self.addCleanup(current_ui().clear)


class TestColours(unittest.TestCase):
    def test_the_documented_values(self):
        self.assertEqual(color.black, (0, 0, 0))
        self.assertEqual(color.white, (250, 250, 250))
        self.assertEqual(color.blue, (0, 0, 250))

    def test_colours_are_plain_tuples(self):
        """So a custom colour works anywhere a named one does."""
        self.assertIsInstance(color.blue, tuple)
        self.assertEqual(len(color.blue), 3)

    def test_the_named_set(self):
        for name in ("black", "white", "red", "green", "blue", "yellow",
                     "cyan", "magenta", "gray"):
            with self.subTest(colour=name):
                value = getattr(color, name)
                self.assertEqual(len(value), 3)
                self.assertTrue(all(0 <= part <= 255 for part in value))

    def test_grey_and_gray_are_the_same(self):
        self.assertEqual(color.grey, color.gray)

    def test_check_accepts_a_custom_colour(self):
        self.assertEqual(color.check((128, 40, 200)), (128, 40, 200))

    def test_check_accepts_a_list(self):
        self.assertEqual(color.check([1, 2, 3]), (1, 2, 3))

    def test_check_rejects_the_wrong_shape(self):
        for bad in ((1, 2), (1, 2, 3, 4), 5, "blue", None):
            with self.subTest(value=bad), self.assertRaises(TypeError):
                color.check(bad)

    def test_check_rejects_out_of_range_parts(self):
        for bad in ((-1, 0, 0), (0, 256, 0), (0, 0, 999)):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                color.check(bad)

    def test_check_rejects_non_integer_parts(self):
        with self.assertRaises(TypeError):
            color.check((1.5, 0, 0))

    def test_the_error_says_what_a_colour_looks_like(self):
        with self.assertRaises(TypeError) as caught:
            color.check("blue")
        self.assertIn("color.blue", str(caught.exception))

    def test_is_exposed_publicly(self):
        self.assertIs(trjoludus.color, color)


class TestFont(unittest.TestCase):
    def test_character_size(self):
        self.assertEqual((CHARACTER_WIDTH, CHARACTER_HEIGHT), (5, 7))

    def test_every_printable_ascii_character_has_a_glyph(self):
        for code in range(0x20, 0x7F):
            with self.subTest(character=chr(code)):
                self.assertEqual(len(columns_for(chr(code))), CHARACTER_WIDTH)

    def test_a_space_is_blank(self):
        self.assertEqual(set(columns_for(" ")), {0})

    def test_letters_are_not_blank(self):
        for character in "AWgz09":
            with self.subTest(character=character):
                self.assertNotEqual(set(columns_for(character)), {0})

    def test_different_characters_look_different(self):
        self.assertNotEqual(columns_for("A"), columns_for("B"))

    def test_unknown_characters_get_a_visible_box(self):
        """Missing characters must be seen, not silently dropped."""
        for character in ("é", "→", "あ"):
            with self.subTest(character=character):
                glyph = columns_for(character)
                self.assertEqual(len(glyph), CHARACTER_WIDTH)
                self.assertNotEqual(set(glyph), {0})

    def test_measure(self):
        self.assertEqual(measure(""), (0, CHARACTER_HEIGHT))
        self.assertEqual(measure("A"), (5, 7))
        self.assertEqual(measure("AB"), (11, 7))


class TestFramebufferPrimitives(unittest.TestCase):
    def setUp(self):
        self.buffer = Framebuffer(20, 12)
        self.buffer.clear((0, 0, 0))

    def pixel(self, x, y):
        i = (y * self.buffer.width + x) * 4
        blue, green, red, _ = self.buffer.pixels[i:i + 4]
        return (red, green, blue)

    def test_set_pixel(self):
        self.buffer.set_pixel(3, 4, (250, 0, 0))
        self.assertEqual(self.pixel(3, 4), (250, 0, 0))

    def test_set_pixel_outside_is_ignored(self):
        for x, y in ((-1, 0), (0, -1), (20, 0), (0, 12)):
            with self.subTest(at=(x, y)):
                self.buffer.set_pixel(x, y, (250, 0, 0))  # must not raise

    def test_fill_rect(self):
        self.buffer.fill_rect(2, 3, 4, 2, (0, 0, 250))
        self.assertEqual(self.pixel(2, 3), (0, 0, 250))
        self.assertEqual(self.pixel(5, 4), (0, 0, 250))
        self.assertEqual(self.pixel(6, 3), (0, 0, 0))
        self.assertEqual(self.pixel(2, 5), (0, 0, 0))

    def test_fill_rect_is_clipped(self):
        self.buffer.fill_rect(-2, -2, 5, 5, (0, 250, 0))
        self.assertEqual(self.pixel(0, 0), (0, 250, 0))
        self.assertEqual(self.pixel(3, 3), (0, 0, 0))

    def test_fill_rect_with_no_area_draws_nothing(self):
        before = bytes(self.buffer.pixels)
        self.buffer.fill_rect(2, 2, 0, 5, (250, 0, 0))
        self.buffer.fill_rect(2, 2, 5, 0, (250, 0, 0))
        self.assertEqual(bytes(self.buffer.pixels), before)

    def test_horizontal_line(self):
        self.buffer.draw_line(2, 5, 8, 5, (250, 250, 250))
        for x in range(2, 9):
            with self.subTest(x=x):
                self.assertEqual(self.pixel(x, 5), (250, 250, 250))
        self.assertEqual(self.pixel(9, 5), (0, 0, 0))

    def test_vertical_line(self):
        self.buffer.draw_line(4, 1, 4, 6, (250, 250, 250))
        for y in range(1, 7):
            with self.subTest(y=y):
                self.assertEqual(self.pixel(4, y), (250, 250, 250))

    def test_a_line_includes_both_ends(self):
        self.buffer.draw_line(1, 1, 6, 4, (250, 0, 0))
        self.assertEqual(self.pixel(1, 1), (250, 0, 0))
        self.assertEqual(self.pixel(6, 4), (250, 0, 0))

    def test_a_diagonal_line_has_no_gaps(self):
        self.buffer.draw_line(0, 0, 9, 9, (250, 0, 0))
        for i in range(10):
            with self.subTest(i=i):
                self.assertEqual(self.pixel(i, i), (250, 0, 0))

    def test_a_line_drawn_backwards_covers_the_same_pixels(self):
        self.buffer.draw_line(2, 2, 8, 5, (250, 0, 0))
        forwards = bytes(self.buffer.pixels)
        self.buffer.clear((0, 0, 0))
        self.buffer.draw_line(8, 5, 2, 2, (250, 0, 0))
        self.assertEqual(bytes(self.buffer.pixels), forwards)

    def test_a_line_of_one_point(self):
        self.buffer.draw_line(3, 3, 3, 3, (250, 0, 0))
        self.assertEqual(self.pixel(3, 3), (250, 0, 0))

    def test_lines_off_screen_are_clipped_not_fatal(self):
        self.buffer.draw_line(-50, -50, 50, 50, (250, 0, 0))  # must not raise
        self.assertEqual(self.pixel(0, 0), (250, 0, 0))

    def test_text_draws_something(self):
        self.buffer.draw_text("A", 1, 1, (250, 250, 250))
        lit = sum(
            1
            for y in range(12)
            for x in range(20)
            if self.pixel(x, y) != (0, 0, 0)
        )
        self.assertGreater(lit, 5)

    def test_text_starts_at_the_given_corner(self):
        """The top-left of the first character, like every other coordinate."""
        self.buffer.draw_text("A", 2, 3, (250, 250, 250))
        column = columns_for("A")[0]
        for row in range(CHARACTER_HEIGHT):
            expected = (250, 250, 250) if column & (1 << row) else (0, 0, 0)
            with self.subTest(row=row):
                self.assertEqual(self.pixel(2, 3 + row), expected)

    def test_a_space_draws_nothing(self):
        before = bytes(self.buffer.pixels)
        self.buffer.draw_text(" ", 1, 1, (250, 250, 250))
        self.assertEqual(bytes(self.buffer.pixels), before)

    def test_empty_text_draws_nothing(self):
        before = bytes(self.buffer.pixels)
        self.buffer.draw_text("", 1, 1, (250, 250, 250))
        self.assertEqual(bytes(self.buffer.pixels), before)

    def test_text_off_screen_is_clipped_not_fatal(self):
        self.buffer.draw_text("Hello", -3, -3, (250, 250, 250))
        self.buffer.draw_text("Hello", 18, 10, (250, 250, 250))


class TestDrawingWithoutAList(UiTestCase):
    def test_drawing_is_remembered(self):
        draw.rect(0, 0, 5, 5, color.blue)
        self.assertEqual(len(current_ui().require("default")), 1)

    def test_several_things_accumulate(self):
        draw.rect(0, 0, 5, 5, color.blue)
        draw.line(0, 0, 5, 5, color.white)
        draw.text(0, 0, "hi", color.white)
        self.assertEqual(len(current_ui().require("default")), 3)

    def test_clear_forgets_them(self):
        draw.rect(0, 0, 5, 5, color.blue)
        draw.clear()
        self.assertEqual(len(current_ui().require("default")), 0)

    def test_clear_before_drawing_anything_is_safe(self):
        draw.clear()

    def test_clear_leaves_named_lists_alone(self):
        menu = draw.list("menu")
        menu.rect(0, 0, 5, 5, color.blue)
        draw.rect(0, 0, 5, 5, color.white)
        draw.clear()
        self.assertEqual(len(menu), 1)

    def test_is_exposed_publicly(self):
        self.assertIs(trjoludus.draw, draw)

    def test_there_is_no_draw_image(self):
        """Images are objects in the world, made with create.image."""
        self.assertFalse(hasattr(draw, "image"))


class TestDrawingLists(UiTestCase):
    def test_creating_a_list(self):
        menu = draw.list("start_menu")
        self.assertIsInstance(menu, DrawList)
        self.assertEqual(menu.name, "start_menu")

    def test_a_new_list_is_empty_and_visible(self):
        menu = draw.list("menu")
        self.assertEqual(len(menu), 0)
        self.assertTrue(menu.visible)

    def test_drawing_into_a_list(self):
        menu = draw.list("menu")
        menu.line(0, 0, 10, 10, color.white)
        menu.rect(0, 0, 5, 5, color.blue)
        menu.text(1, 1, "Play", color.white)
        self.assertEqual(len(menu), 3)

    def test_drawing_returns_the_thing_that_was_drawn(self):
        """So it can be held, scaled and asked about the mouse."""
        from trjoludus.ui import Drawable

        menu = draw.list("menu")
        button = menu.rect(0, 0, 5, 5, color.blue)
        self.assertIsInstance(button, Drawable)
        self.assertIs(button.list, menu)
        self.assertEqual(menu.drawings(), (button,))

    def test_contents_are_kept_until_changed(self):
        menu = draw.list("menu")
        menu.rect(0, 0, 5, 5, color.blue)
        menu.hide()
        menu.show()
        self.assertEqual(len(menu), 1)

    def test_hide_and_show(self):
        menu = draw.list("menu")
        menu.hide()
        self.assertFalse(menu.visible)
        menu.show()
        self.assertTrue(menu.visible)

    def test_hiding_keeps_the_contents(self):
        menu = draw.list("menu")
        menu.rect(0, 0, 5, 5, color.blue)
        menu.hide()
        self.assertEqual(len(menu), 1)

    def test_clear_empties_a_list_but_keeps_it(self):
        menu = draw.list("menu")
        menu.rect(0, 0, 5, 5, color.blue)
        menu.clear()
        self.assertEqual(len(menu), 0)
        self.assertIn("menu", current_ui())

    def test_multiple_lists_are_independent(self):
        first = draw.list("first")
        second = draw.list("second")
        first.rect(0, 0, 5, 5, color.blue)
        first.hide()

        self.assertEqual(len(second), 0)
        self.assertTrue(second.visible)
        self.assertEqual(len(first), 1)

    def test_lists_keep_creation_order(self):
        draw.list("a")
        draw.list("b")
        draw.list("c")
        self.assertEqual(current_ui().names, ("a", "b", "c"))

    def test_duplicate_names_are_rejected(self):
        draw.list("menu")
        with self.assertRaises(UiError) as caught:
            draw.list("menu")
        self.assertIn("menu", str(caught.exception))

    def test_a_rejected_duplicate_leaves_the_first_alone(self):
        menu = draw.list("menu")
        menu.rect(0, 0, 5, 5, color.blue)
        with self.assertRaises(UiError):
            draw.list("menu")
        self.assertEqual(len(menu), 1)

    def test_destroying_a_list(self):
        menu = draw.list("menu")
        menu.destroy()
        self.assertNotIn("menu", current_ui())

    def test_destroying_frees_the_name(self):
        draw.list("menu").destroy()
        draw.list("menu")  # must not raise

    def test_using_a_destroyed_list_raises(self):
        menu = draw.list("menu")
        menu.destroy()
        for action in (lambda: menu.rect(0, 0, 1, 1, color.blue),
                       lambda: menu.line(0, 0, 1, 1, color.blue),
                       lambda: menu.text(0, 0, "x", color.blue),
                       menu.show, menu.hide, menu.clear, menu.destroy):
            with self.subTest(), self.assertRaises(UiError):
                action()

    def test_the_destroyed_error_explains_itself(self):
        menu = draw.list("menu")
        menu.destroy()
        with self.assertRaises(UiError) as caught:
            menu.show()
        message = str(caught.exception)
        self.assertIn("menu", message)
        self.assertIn("destroyed", message)

    def test_a_missing_list_names_what_exists(self):
        draw.list("menu")
        with self.assertRaises(UiError) as caught:
            current_ui().require("nope")
        message = str(caught.exception)
        self.assertIn("nope", message)
        self.assertIn("menu", message)

    def test_a_missing_list_with_none_made_says_so(self):
        with self.assertRaises(UiError) as caught:
            current_ui().require("menu")
        self.assertIn("none have been", str(caught.exception))


class TestInvalidValues(UiTestCase):
    def test_a_list_name_must_be_a_string(self):
        with self.assertRaises(TypeError):
            draw.list(42)

    def test_a_list_name_cannot_be_empty(self):
        with self.assertRaises(ValueError):
            draw.list("")

    def test_coordinates_may_be_fractional(self):
        """Positions carry fractions; only drawing rounds them."""
        self.assertEqual(draw.rect(1.5, 0, 5, 5, color.blue).x, 1.5)
        self.assertEqual(draw.line(0, 0, 1.5, 5, color.blue).end_x, 1.5)
        self.assertEqual(draw.text(0.5, 0, "hi", color.blue).x, 0.5)

    def test_coordinates_must_still_be_numbers(self):
        with self.assertRaises(TypeError):
            draw.rect("1", 0, 5, 5, color.blue)
        with self.assertRaises(TypeError):
            draw.line(0, 0, True, 5, color.blue)
        with self.assertRaises(TypeError):
            draw.text(None, 0, "hi", color.blue)

    def test_a_size_is_still_a_whole_number_of_pixels(self):
        """A position can fall between pixels; a width cannot be half of one."""
        with self.assertRaises(TypeError):
            draw.rect(0, 0, 5.5, 5, color.blue)

    def test_a_rectangle_cannot_have_a_negative_size(self):
        with self.assertRaises(ValueError):
            draw.rect(0, 0, -5, 5, color.blue)

    def test_text_must_be_a_string(self):
        with self.assertRaises(TypeError):
            draw.text(0, 0, 42, color.blue)

    def test_a_bad_colour_is_rejected(self):
        with self.assertRaises(TypeError):
            draw.rect(0, 0, 5, 5, "blue")
        with self.assertRaises(ValueError):
            draw.line(0, 0, 5, 5, (0, 0, 999))

    def test_nothing_is_recorded_when_a_call_is_rejected(self):
        """A rejected call must leave nothing behind to be drawn."""
        with self.assertRaises(TypeError):
            draw.rect(0, 0, 5, 5, "blue")
        if "default" in current_ui():
            self.assertEqual(len(current_ui().require("default")), 0)


class TestRenderedThroughTheApplication(UiTestCase):
    """What a game would actually see, checked pixel by pixel."""

    def run_game(self, on_start, size=(30, 20)):
        windows = []

        class Backend(NullBackend):
            def create_window(self, title, width, height):
                window = super().create_window(title, width, height)
                windows.append(window)
                return window

        class G(Game):
            def on_start(self):
                on_start()

            def on_update(self, dt):
                self.quit()

        Application(G(), size=size, max_fps=None, backend=Backend()).run()
        return windows[0]

    def pixel(self, window, x, y):
        width = window.last_frame_size[0]
        i = (y * width + x) * 4
        blue, green, red, _ = window.last_frame[i:i + 4]
        return (red, green, blue)

    def test_a_rectangle_appears(self):
        window = self.run_game(lambda: draw.rect(2, 3, 6, 4, color.blue))
        self.assertEqual(self.pixel(window, 2, 3), color.blue)
        self.assertEqual(self.pixel(window, 7, 6), color.blue)
        self.assertEqual(self.pixel(window, 8, 3), DEFAULT_CLEAR_COLOUR)

    def test_a_line_appears(self):
        window = self.run_game(lambda: draw.line(1, 1, 10, 1, color.red))
        self.assertEqual(self.pixel(window, 5, 1), color.red)

    def test_text_appears(self):
        window = self.run_game(lambda: draw.text(1, 1, "A", color.white))
        lit = [
            (x, y)
            for y in range(7)
            for x in range(10)
            if self.pixel(window, x, y) == color.white
        ]
        self.assertGreater(len(lit), 5)

    def test_ui_is_drawn_on_top_of_the_game(self):
        """UI belongs in front, or a menu could be hidden by a sprite."""
        from trjoludus import create
        from trjoludus.scene import current_scene

        self.addCleanup(current_scene().clear)
        sprite = _sprite(self, 10, 10, (200, 100, 50))

        def start():
            create.image(0, 0, sprite, "player")
            draw.rect(0, 0, 5, 5, color.blue)

        window = self.run_game(start)
        self.assertEqual(self.pixel(window, 2, 2), color.blue)
        self.assertEqual(self.pixel(window, 7, 7), (200, 100, 50))

    def test_a_hidden_list_is_not_drawn(self):
        def start():
            menu = draw.list("menu")
            menu.rect(2, 2, 5, 5, color.blue)
            menu.hide()

        window = self.run_game(start)
        self.assertEqual(self.pixel(window, 3, 3), DEFAULT_CLEAR_COLOUR)

    def test_showing_a_list_again_draws_it(self):
        def start():
            menu = draw.list("menu")
            menu.rect(2, 2, 5, 5, color.blue)
            menu.hide()
            menu.show()

        window = self.run_game(start)
        self.assertEqual(self.pixel(window, 3, 3), color.blue)

    def test_a_destroyed_list_is_not_drawn(self):
        def start():
            menu = draw.list("menu")
            menu.rect(2, 2, 5, 5, color.blue)
            menu.destroy()

        window = self.run_game(start)
        self.assertEqual(self.pixel(window, 3, 3), DEFAULT_CLEAR_COLOUR)

    def test_lists_are_drawn_in_creation_order(self):
        def start():
            draw.list("under").rect(0, 0, 10, 10, color.red)
            draw.list("over").rect(0, 0, 10, 10, color.blue)

        window = self.run_game(start)
        self.assertEqual(self.pixel(window, 5, 5), color.blue)

    def test_a_custom_colour_appears(self):
        window = self.run_game(lambda: draw.rect(0, 0, 5, 5, (128, 40, 200)))
        self.assertEqual(self.pixel(window, 2, 2), (128, 40, 200))

    def test_the_ui_is_cleared_when_a_run_finishes(self):
        self.run_game(lambda: draw.list("menu").rect(0, 0, 5, 5, color.blue))
        self.assertEqual(len(current_ui()), 0)
        # The same names must be free for the next game.
        self.run_game(lambda: draw.list("menu"))


def _sprite(test, width, height, rgb):
    import struct
    import tempfile
    import zlib
    from pathlib import Path

    red, green, blue = rgb
    rows = b"".join(
        b"\x00" + bytes([red, green, blue, 255]) * width for _ in range(height)
    )

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    path = Path(directory.name) / "sprite.png"
    path.write_bytes(png)
    return path


if __name__ == "__main__":
    unittest.main()
