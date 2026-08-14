"""Python and Rust must draw the same pixels.

Every test here renders the same scene twice -- once through
:class:`trjoludus.rendering_python.Framebuffer`, once through
:class:`trjoludus.native.renderer.NativeFramebuffer` -- and compares the two
buffers byte for byte. Not "looks the same": the same bytes.

A single differing pixel fails, and says which one and what the two renderers
put there, because a renderer that is *nearly* right is the hardest kind of
bug to find later.

These skip when there is no native library to compare against. That is the one
thing that cannot be arranged: you cannot compare against a renderer that has
not been built.
"""

import unittest

from trjoludus.image import Image
from trjoludus.native import library, renderer
from trjoludus.rendering_python import DEFAULT_CLEAR_COLOUR, Framebuffer

RED = (250, 0, 0)
GREEN = (0, 250, 0)
BLUE = (0, 0, 250)
WHITE = (250, 250, 250)


def opaque_image(width, height, colour=(10, 200, 30)):
    """An image with no transparency, which takes the row-copy path."""
    red, green, blue = colour
    return Image(width, height,
                 bytes([blue, green, red, 255]) * (width * height))


def patterned_image(width, height):
    """Every pixel different, so a mis-mapped scale cannot pass unnoticed."""
    pixels = bytearray()
    for index in range(width * height):
        pixels += bytes([index % 251, (index * 7) % 251,
                         (index * 13) % 251, 255])
    return Image(width, height, bytes(pixels))


def transparent_image(width, height):
    """A mix of opaque, invisible and half-there pixels."""
    pixels = bytearray()
    for index in range(width * height):
        alpha = (0, 255, 128, 64)[index % 4]
        pixels += bytes([(index * 3) % 251, (index * 5) % 251,
                         (index * 11) % 251, alpha])
    return Image(width, height, bytes(pixels))


class RendererEquivalence(unittest.TestCase):
    """Runs one scene through both renderers and compares the pixels."""

    WIDTH = 40
    HEIGHT = 30

    @classmethod
    def setUpClass(cls):
        library.forget()
        renderer.forget()
        if not renderer.available():
            raise unittest.SkipTest(
                "no native renderer built here; run cargo build and copy the "
                "library into trjoludus/native/lib/")

    def both(self, scene, width=None, height=None):
        """Run ``scene`` on each renderer and return the two buffers."""
        width = self.WIDTH if width is None else width
        height = self.HEIGHT if height is None else height

        python = Framebuffer(width, height)
        native = renderer.NativeFramebuffer(width, height)
        for buffer in (python, native):
            buffer.clear()
            scene(buffer)
        return bytes(python.pixels), bytes(native.pixels)

    def assertSamePixels(self, scene, width=None, height=None):
        """Fail on the first pixel the two renderers disagree about."""
        expected, found = self.both(scene, width, height)
        self.assertEqual(len(expected), len(found), "different buffer sizes")
        if expected == found:
            return

        stride = (self.WIDTH if width is None else width) * 4
        for index in range(0, len(expected), 4):
            if expected[index:index + 4] != found[index:index + 4]:
                pixel = index // 4
                x, y = pixel % (stride // 4), pixel // (stride // 4)
                self.fail(
                    f"pixel ({x}, {y}) differs: Python drew "
                    f"{tuple(expected[index:index + 4])}, Rust drew "
                    f"{tuple(found[index:index + 4])} (BGRA)"
                )
        self.fail("buffers differ but no pixel does")   # pragma: no cover


class TestClearing(RendererEquivalence):
    def test_the_default_colour(self):
        self.assertSamePixels(lambda buffer: None)

    def test_a_chosen_colour(self):
        self.assertSamePixels(lambda buffer: buffer.clear((1, 2, 3)))

    def test_black_and_white(self):
        for colour in ((0, 0, 0), (255, 255, 255)):
            with self.subTest(colour=colour):
                self.assertSamePixels(lambda b, c=colour: b.clear(c))


class TestPixels(RendererEquivalence):
    def test_one_pixel(self):
        self.assertSamePixels(lambda b: b.set_pixel(5, 5, RED))

    def test_every_corner(self):
        def scene(buffer):
            for x, y in ((0, 0), (self.WIDTH - 1, 0), (0, self.HEIGHT - 1),
                         (self.WIDTH - 1, self.HEIGHT - 1)):
                buffer.set_pixel(x, y, GREEN)

        self.assertSamePixels(scene)

    def test_pixels_outside_the_buffer(self):
        def scene(buffer):
            for x, y in ((-1, 0), (0, -1), (self.WIDTH, 0),
                         (0, self.HEIGHT), (-100, -100), (999, 999)):
                buffer.set_pixel(x, y, RED)

        self.assertSamePixels(scene)

    def test_fractional_pixel_positions(self):
        def scene(buffer):
            for offset in (0.0, 0.4, 0.5, 0.6, 1.5, 2.5, -0.5, -1.5):
                buffer.set_pixel(10 + offset, 10 + offset, BLUE)

        self.assertSamePixels(scene)


class TestRectangles(RendererEquivalence):
    def test_a_plain_rectangle(self):
        self.assertSamePixels(lambda b: b.fill_rect(4, 5, 10, 6, RED))

    def test_one_pixel_wide(self):
        self.assertSamePixels(lambda b: b.fill_rect(3, 3, 1, 20, GREEN))

    def test_no_area(self):
        def scene(buffer):
            buffer.fill_rect(3, 3, 0, 10, RED)
            buffer.fill_rect(3, 3, 10, 0, RED)
            buffer.fill_rect(3, 3, -5, 10, RED)

        self.assertSamePixels(scene)

    def test_clipped_at_every_edge(self):
        def scene(buffer):
            buffer.fill_rect(-5, -5, 10, 10, RED)
            buffer.fill_rect(self.WIDTH - 5, -3, 10, 10, GREEN)
            buffer.fill_rect(-3, self.HEIGHT - 4, 10, 10, BLUE)
            buffer.fill_rect(self.WIDTH - 2, self.HEIGHT - 2, 10, 10, WHITE)

        self.assertSamePixels(scene)

    def test_entirely_outside(self):
        def scene(buffer):
            buffer.fill_rect(-100, -100, 10, 10, RED)
            buffer.fill_rect(500, 500, 10, 10, RED)

        self.assertSamePixels(scene)

    def test_covering_everything(self):
        self.assertSamePixels(
            lambda b: b.fill_rect(-10, -10, 500, 500, GREEN))

    def test_fractional_positions(self):
        def scene(buffer):
            for offset in (0.0, 0.25, 0.5, 0.75, 1.5, 2.5):
                buffer.fill_rect(2 + offset, 2 + offset, 4, 4, RED)

        self.assertSamePixels(scene)

    def test_one_over_another(self):
        def scene(buffer):
            buffer.fill_rect(2, 2, 20, 20, RED)
            buffer.fill_rect(6, 6, 12, 12, GREEN)
            buffer.fill_rect(10, 10, 4, 4, BLUE)

        self.assertSamePixels(scene)


class TestLines(RendererEquivalence):
    def test_horizontal(self):
        self.assertSamePixels(lambda b: b.draw_line(2, 5, 30, 5, RED))

    def test_vertical(self):
        self.assertSamePixels(lambda b: b.draw_line(5, 2, 5, 25, RED))

    def test_diagonal(self):
        self.assertSamePixels(lambda b: b.draw_line(0, 0, 39, 29, GREEN))

    def test_every_direction(self):
        def scene(buffer):
            middle = (20, 15)
            for end in ((0, 0), (39, 0), (0, 29), (39, 29), (20, 0),
                        (0, 15), (39, 15), (20, 29)):
                buffer.draw_line(*middle, *end, BLUE)

        self.assertSamePixels(scene)

    def test_shallow_and_steep(self):
        def scene(buffer):
            buffer.draw_line(0, 1, 39, 8, RED)
            buffer.draw_line(1, 0, 8, 29, GREEN)

        self.assertSamePixels(scene)

    def test_a_line_of_no_length(self):
        self.assertSamePixels(lambda b: b.draw_line(7, 7, 7, 7, RED))

    def test_drawn_from_either_end(self):
        def scene(buffer):
            buffer.draw_line(3, 3, 30, 17, RED)
            buffer.draw_line(30, 17, 3, 3, RED)

        self.assertSamePixels(scene)

    def test_clipped_lines(self):
        def scene(buffer):
            buffer.draw_line(-20, -20, 20, 20, RED)
            buffer.draw_line(-10, 15, 60, 15, GREEN)
            buffer.draw_line(15, -10, 15, 60, BLUE)

        self.assertSamePixels(scene)

    def test_fractional_ends(self):
        def scene(buffer):
            buffer.draw_line(1.4, 1.6, 20.5, 10.5, RED)
            buffer.draw_line(2.5, 3.5, 25.5, 4.5, GREEN)

        self.assertSamePixels(scene)


class TestText(RendererEquivalence):
    def test_one_word(self):
        self.assertSamePixels(lambda b: b.draw_text("Score", 2, 2, WHITE))

    def test_every_printable_character(self):
        def scene(buffer):
            characters = "".join(chr(code) for code in range(32, 127))
            for index in range(0, len(characters), 6):
                buffer.draw_text(characters[index:index + 6],
                                 1, 1 + (index // 6) * 8, WHITE)

        self.assertSamePixels(scene, width=60, height=140)

    def test_a_character_the_font_does_not_have(self):
        self.assertSamePixels(lambda b: b.draw_text("aéb→c", 2, 2,
                                                    WHITE))

    def test_empty_text(self):
        self.assertSamePixels(lambda b: b.draw_text("", 5, 5, WHITE))

    def test_text_off_the_edges(self):
        def scene(buffer):
            buffer.draw_text("edge", -8, 2, WHITE)
            buffer.draw_text("edge", 36, 10, WHITE)
            buffer.draw_text("edge", 2, -3, WHITE)
            buffer.draw_text("edge", 2, 28, WHITE)

        self.assertSamePixels(scene)

    def test_fractional_text_positions(self):
        def scene(buffer):
            for offset in (0.0, 0.5, 1.5, 2.4, 2.6):
                buffer.draw_text("x", 2 + offset, 2 + offset, WHITE)

        self.assertSamePixels(scene)

    def test_a_long_line(self):
        self.assertSamePixels(
            lambda b: b.draw_text("the quick brown fox jumps", 0, 10, WHITE))


class TestImages(RendererEquivalence):
    def test_an_opaque_image(self):
        image = opaque_image(8, 6)
        self.assertSamePixels(lambda b: b.draw_image(image, 4, 4))

    def test_a_patterned_image(self):
        image = patterned_image(9, 7)
        self.assertSamePixels(lambda b: b.draw_image(image, 3, 3))

    def test_a_transparent_image(self):
        image = transparent_image(8, 8)
        self.assertSamePixels(lambda b: b.draw_image(image, 5, 5))

    def test_blending_over_something(self):
        image = transparent_image(10, 10)

        def scene(buffer):
            buffer.fill_rect(0, 0, 40, 30, (120, 60, 200))
            buffer.draw_image(image, 4, 4)

        self.assertSamePixels(scene)

    def test_clipped_at_every_edge(self):
        image = patterned_image(10, 10)

        def scene(buffer):
            buffer.draw_image(image, -4, -4)
            buffer.draw_image(image, 35, -2)
            buffer.draw_image(image, -2, 25)
            buffer.draw_image(image, 36, 26)

        self.assertSamePixels(scene)

    def test_entirely_offscreen(self):
        image = opaque_image(4, 4)

        def scene(buffer):
            buffer.draw_image(image, -100, -100)
            buffer.draw_image(image, 500, 500)

        self.assertSamePixels(scene)

    def test_a_transparent_image_clipped(self):
        image = transparent_image(10, 10)

        def scene(buffer):
            buffer.fill_rect(0, 0, 40, 30, (30, 30, 30))
            buffer.draw_image(image, -5, -5)
            buffer.draw_image(image, 36, 25)

        self.assertSamePixels(scene)

    def test_fractional_positions(self):
        image = opaque_image(5, 5)

        def scene(buffer):
            for offset in (0.0, 0.4, 0.5, 0.6, 1.5, 2.5):
                buffer.draw_image(image, 2 + offset, 2 + offset)

        self.assertSamePixels(scene)

    def test_a_one_pixel_image(self):
        image = opaque_image(1, 1)
        self.assertSamePixels(lambda b: b.draw_image(image, 10, 10))


class TestScaledImages(RendererEquivalence):
    def test_doubled(self):
        image = patterned_image(4, 4)
        self.assertSamePixels(lambda b: b.draw_image(image, 4, 4, 2.0))

    def test_halved(self):
        image = patterned_image(8, 8)
        self.assertSamePixels(lambda b: b.draw_image(image, 4, 4, 0.5))

    def test_many_scales(self):
        image = patterned_image(6, 6)
        for scale in (0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0,
                      4.0):
            with self.subTest(scale=scale):
                self.assertSamePixels(
                    lambda b, s=scale: b.draw_image(image, 3, 3, s))

    def test_a_scale_that_rounds_to_nothing(self):
        image = patterned_image(4, 4)
        self.assertSamePixels(lambda b: b.draw_image(image, 4, 4, 0.05))

    def test_scaled_and_transparent(self):
        image = transparent_image(5, 5)

        def scene(buffer):
            buffer.fill_rect(0, 0, 40, 30, (80, 80, 80))
            buffer.draw_image(image, 3, 3, 3.0)

        self.assertSamePixels(scene)

    def test_scaled_and_clipped(self):
        image = patterned_image(6, 6)

        def scene(buffer):
            buffer.draw_image(image, -6, -6, 2.0)
            buffer.draw_image(image, 34, 24, 2.0)

        self.assertSamePixels(scene)

    def test_a_non_square_image_scaled(self):
        image = patterned_image(3, 7)
        self.assertSamePixels(lambda b: b.draw_image(image, 5, 2, 2.5))

    def test_scaled_at_a_fractional_position(self):
        image = patterned_image(4, 4)

        def scene(buffer):
            for offset in (0.4, 0.5, 0.6):
                buffer.draw_image(image, 2 + offset, 2 + offset, 1.5)

        self.assertSamePixels(scene)


class TestWholeScenes(RendererEquivalence):
    """Everything at once, in the order a game would draw it."""

    def test_a_scene_in_draw_order(self):
        sprite = transparent_image(8, 8)
        background = opaque_image(12, 12, (20, 40, 60))

        def scene(buffer):
            buffer.fill_rect(0, 0, 40, 30, (15, 15, 25))
            buffer.draw_image(background, 2, 2)
            buffer.draw_image(sprite, 6, 6)
            buffer.fill_rect(10, 10, 12, 8, (200, 40, 40))
            buffer.draw_line(0, 0, 39, 29, (250, 250, 0))
            buffer.draw_text("HUD", 2, 22, WHITE)
            buffer.set_pixel(39, 0, GREEN)

        self.assertSamePixels(scene)

    def test_layering_is_the_same(self):
        def scene(buffer):
            for index, colour in enumerate((RED, GREEN, BLUE, WHITE)):
                buffer.fill_rect(index * 2, index * 2, 20, 20, colour)

        self.assertSamePixels(scene)

    def test_drawing_the_same_thing_repeatedly(self):
        image = transparent_image(6, 6)

        def scene(buffer):
            for _ in range(10):
                buffer.draw_image(image, 5, 5)

        self.assertSamePixels(scene)

    def test_a_scene_redrawn_after_clearing(self):
        def scene(buffer):
            buffer.fill_rect(2, 2, 10, 10, RED)
            buffer.clear()
            buffer.fill_rect(4, 4, 10, 10, GREEN)

        self.assertSamePixels(scene)

    def test_an_awkward_buffer_size(self):
        def scene(buffer):
            buffer.fill_rect(0, 0, 3, 3, RED)
            buffer.draw_line(0, 0, 6, 4, GREEN)
            buffer.draw_text("i", 1, 1, WHITE)

        self.assertSamePixels(scene, width=7, height=5)

    def test_a_one_pixel_buffer(self):
        self.assertSamePixels(lambda b: b.fill_rect(0, 0, 1, 1, RED),
                              width=1, height=1)


class TestTheSurfacesMatch(RendererEquivalence):
    """The two renderers must be interchangeable, not merely similar."""

    def test_they_offer_the_same_methods(self):
        expected = {name for name in dir(Framebuffer)
                    if not name.startswith("_")}
        found = {name for name in dir(renderer.NativeFramebuffer)
                 if not name.startswith("_")}
        self.assertEqual(expected, found)

    def test_pixels_is_a_bytearray_either_way(self):
        self.assertIsInstance(Framebuffer(4, 4).pixels, bytearray)
        self.assertIsInstance(
            renderer.NativeFramebuffer(4, 4).pixels, bytearray)

    def test_size_reads_the_same(self):
        self.assertEqual(Framebuffer(7, 3).size,
                         renderer.NativeFramebuffer(7, 3).size)

    def test_both_refuse_an_impossible_size(self):
        for width, height in ((0, 4), (4, 0), (-1, 4)):
            with self.subTest(size=(width, height)):
                with self.assertRaises(ValueError):
                    Framebuffer(width, height)
                with self.assertRaises(ValueError):
                    renderer.NativeFramebuffer(width, height)

    def test_resizing_matches(self):
        python = Framebuffer(10, 10)
        native = renderer.NativeFramebuffer(10, 10)
        for size in ((20, 5), (20, 5), (3, 3)):
            python.resize(*size)
            native.resize(*size)
            python.clear()
            native.clear()
            self.assertEqual(python.size, native.size)
            self.assertEqual(bytes(python.pixels), bytes(native.pixels))

    def test_resizing_keeps_drawing_correctly(self):
        python = Framebuffer(10, 10)
        native = renderer.NativeFramebuffer(10, 10)
        for buffer in (python, native):
            buffer.resize(25, 12)
            buffer.clear()
            buffer.fill_rect(3, 3, 8, 5, RED)
            buffer.draw_text("ok", 1, 1, WHITE)
        self.assertEqual(bytes(python.pixels), bytes(native.pixels))


class TestFailuresAreReported(RendererEquivalence):
    """A frame that did not draw must not look like one that did."""

    def test_a_bad_status_becomes_a_trjoludus_error(self):
        buffer = renderer.NativeFramebuffer(4, 4)
        with self.assertRaises(renderer.RenderingError) as caught:
            buffer._check(-2)
        message = str(caught.exception)
        self.assertIn("native renderer refused to draw", message)
        self.assertIn('rendering.engine = "python"', message)

    def test_every_status_has_something_to_say(self):
        buffer = renderer.NativeFramebuffer(4, 4)
        for status in (-1, -2, -3, -99):
            with self.subTest(status=status):
                with self.assertRaises(renderer.RenderingError):
                    buffer._check(status)

    def test_success_says_nothing(self):
        self.assertIsNone(renderer.NativeFramebuffer(4, 4)._check(0))

    def test_a_rendering_error_is_a_trjoludus_error(self):
        from trjoludus.errors import TrjoLudusError

        self.assertTrue(issubclass(renderer.RenderingError, TrjoLudusError))

    def test_no_rust_wording_reaches_the_message(self):
        buffer = renderer.NativeFramebuffer(4, 4)
        try:
            buffer._check(-3)
        except renderer.RenderingError as error:
            message = str(error).lower()
        for word in ("panic", "unwind", "ffi", "ctypes", "abi", "0x"):
            with self.subTest(word=word):
                self.assertNotIn(word, message)


if __name__ == "__main__":
    unittest.main()
