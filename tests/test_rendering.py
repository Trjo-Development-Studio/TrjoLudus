"""Tests for image decoding and frame compositing.

Both are pure computation over bytes, so all of this runs headlessly. That is
deliberate: it means the parts of rendering that are easy to get subtly wrong
-- colour channel order, alpha blending, clipping -- are checked without
needing a window, and the graphical tests only have to prove that finished
pixels reach the screen.
"""

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from trjoludus.image import Image, ImageError, decode_png, load_image
from trjoludus.render import DEFAULT_CLEAR_COLOUR, Framebuffer


def build_png(width, height, pixels, colour_type=6, palette=b"",
              transparency=b"", bit_depth=8, interlace=0):
    """Assemble a PNG from raw, unfiltered sample rows."""
    samples = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour_type]
    stride = width * samples
    rows = b"".join(
        b"\x00" + pixels[row * stride:(row + 1) * stride]
        for row in range(height)
    )

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    out = b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR",
        struct.pack(">IIBBBBB", width, height, bit_depth, colour_type, 0, 0,
                    interlace),
    )
    if palette:
        out += chunk(b"PLTE", palette)
    if transparency:
        out += chunk(b"tRNS", transparency)
    return out + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


class TestPngDecoding(unittest.TestCase):
    def test_rgba_channels_end_up_in_bgra_order(self):
        """The whole rendering path assumes BGRA; getting this wrong swaps
        red and blue everywhere, which is easy to miss on grey test images."""
        png = build_png(1, 1, bytes([10, 20, 30, 40]))
        image = decode_png(png)
        self.assertEqual(image.pixels, bytes([30, 20, 10, 40]))

    def test_rgb_gets_an_opaque_alpha(self):
        png = build_png(1, 1, bytes([10, 20, 30]), colour_type=2)
        self.assertEqual(decode_png(png).pixels, bytes([30, 20, 10, 255]))

    def test_greyscale(self):
        png = build_png(1, 1, bytes([77]), colour_type=0)
        self.assertEqual(decode_png(png).pixels, bytes([77, 77, 77, 255]))

    def test_greyscale_with_alpha(self):
        png = build_png(1, 1, bytes([77, 128]), colour_type=4)
        self.assertEqual(decode_png(png).pixels, bytes([77, 77, 77, 128]))

    def test_indexed_colour(self):
        png = build_png(1, 1, bytes([1]), colour_type=3,
                        palette=bytes([0, 0, 0, 10, 20, 30]))
        self.assertEqual(decode_png(png).pixels, bytes([30, 20, 10, 255]))

    def test_indexed_colour_with_transparency(self):
        png = build_png(1, 1, bytes([0]), colour_type=3,
                        palette=bytes([10, 20, 30]), transparency=bytes([64]))
        self.assertEqual(decode_png(png).pixels, bytes([30, 20, 10, 64]))

    def test_dimensions(self):
        image = decode_png(build_png(3, 2, bytes([1, 2, 3, 4]) * 6))
        self.assertEqual(image.size, (3, 2))

    def test_row_order_is_top_down(self):
        pixels = bytes([1, 1, 1, 255]) + bytes([9, 9, 9, 255])
        image = decode_png(build_png(1, 2, pixels))
        self.assertEqual(image.pixels[0], 1)
        self.assertEqual(image.pixels[4], 9)

    def test_opacity_is_detected(self):
        opaque = decode_png(build_png(1, 1, bytes([0, 0, 0, 255])))
        transparent = decode_png(build_png(1, 1, bytes([0, 0, 0, 128])))
        self.assertTrue(opaque.is_opaque)
        self.assertFalse(transparent.is_opaque)

    def test_all_filter_types_decode(self):
        """Filters are how PNG compresses; a wrong one corrupts the image."""
        width, height = 4, 4
        raw = bytes(range(width * 4)) * height
        for filter_type in range(5):
            with self.subTest(filter=filter_type):
                stride = width * 4
                rows = b"".join(
                    bytes([filter_type]) + raw[r * stride:(r + 1) * stride]
                    for r in range(height)
                )

                def chunk(tag, data):
                    return (
                        struct.pack(">I", len(data)) + tag + data
                        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
                    )

                png = (
                    b"\x89PNG\r\n\x1a\n"
                    + chunk(b"IHDR",
                            struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(rows))
                    + chunk(b"IEND", b"")
                )
                image = decode_png(png)
                self.assertEqual(len(image.pixels), width * height * 4)


class TestPngErrors(unittest.TestCase):
    def test_not_a_png(self):
        with self.assertRaises(ImageError) as caught:
            decode_png(b"GIF89a and then some")
        self.assertIn("PNG", str(caught.exception))

    def test_sixteen_bit_is_refused_with_advice(self):
        png = build_png(1, 1, bytes([0, 0, 0, 0]), bit_depth=16)
        with self.assertRaises(ImageError) as caught:
            decode_png(png)
        self.assertIn("8 bits", str(caught.exception))

    def test_interlaced_is_refused_with_advice(self):
        png = build_png(1, 1, bytes([0, 0, 0, 0]), interlace=1)
        with self.assertRaises(ImageError) as caught:
            decode_png(png)
        self.assertIn("interlac", str(caught.exception).lower())

    def test_truncated_pixel_data(self):
        png = build_png(4, 4, bytes([0, 0, 0, 0]) * 16)
        broken = png.replace(zlib.compress(
            b"".join(b"\x00" + bytes([0, 0, 0, 0]) * 4 for _ in range(4))),
            zlib.compress(b"\x00\x00"))
        with self.assertRaises(ImageError):
            decode_png(broken)

    def test_missing_file(self):
        with self.assertRaises(ImageError) as caught:
            load_image("definitely-not-here.png")
        self.assertIn("definitely-not-here.png", str(caught.exception))

    def test_load_reports_the_filename_on_a_bad_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.png"
            path.write_bytes(b"not a png at all")
            with self.assertRaises(ImageError) as caught:
                load_image(path)
            self.assertIn("broken.png", str(caught.exception))

    def test_image_rejects_mismatched_data(self):
        with self.assertRaises(ImageError):
            Image(2, 2, b"\x00" * 4)


class TestFramebuffer(unittest.TestCase):
    def pixel(self, buffer, x, y):
        i = (y * buffer.width + x) * 4
        return tuple(buffer.pixels[i:i + 4])

    def test_starts_at_the_requested_size(self):
        self.assertEqual(Framebuffer(30, 20).size, (30, 20))

    def test_rejects_a_non_positive_size(self):
        with self.assertRaises(ValueError):
            Framebuffer(0, 10)

    def test_clear_fills_with_an_opaque_colour(self):
        buffer = Framebuffer(2, 2)
        buffer.clear((10, 20, 30))
        self.assertEqual(self.pixel(buffer, 1, 1), (30, 20, 10, 255))

    def test_default_clear_colour(self):
        buffer = Framebuffer(1, 1)
        buffer.clear()
        red, green, blue = DEFAULT_CLEAR_COLOUR
        self.assertEqual(self.pixel(buffer, 0, 0), (blue, green, red, 255))

    def test_resize_changes_size(self):
        buffer = Framebuffer(4, 4)
        buffer.resize(8, 2)
        self.assertEqual(buffer.size, (8, 2))
        self.assertEqual(len(buffer.pixels), 8 * 2 * 4)

    def test_resize_to_the_same_size_is_a_no_op(self):
        buffer = Framebuffer(4, 4)
        buffer.clear((1, 2, 3))
        before = bytes(buffer.pixels)
        buffer.resize(4, 4)
        self.assertEqual(bytes(buffer.pixels), before)

    def test_draws_an_opaque_image_at_a_position(self):
        buffer = Framebuffer(4, 4)
        buffer.clear((0, 0, 0))
        image = Image(2, 2, bytes([1, 2, 3, 255]) * 4)
        buffer.draw_image(image, 1, 1)

        self.assertEqual(self.pixel(buffer, 1, 1), (1, 2, 3, 255))
        self.assertEqual(self.pixel(buffer, 2, 2), (1, 2, 3, 255))
        self.assertEqual(self.pixel(buffer, 0, 0), (0, 0, 0, 255))

    def test_fully_transparent_pixels_leave_the_background(self):
        buffer = Framebuffer(2, 2)
        buffer.clear((10, 20, 30))
        buffer.draw_image(Image(1, 1, bytes([9, 9, 9, 0])), 0, 0)
        self.assertEqual(self.pixel(buffer, 0, 0), (30, 20, 10, 255))

    def test_semi_transparent_pixels_blend(self):
        buffer = Framebuffer(1, 1)
        buffer.clear((0, 0, 0))
        buffer.draw_image(Image(1, 1, bytes([100, 100, 100, 128])), 0, 0)
        blue, green, red, alpha = self.pixel(buffer, 0, 0)
        self.assertEqual(alpha, 255)
        self.assertTrue(0 < blue < 100, blue)

    def test_later_images_cover_earlier_ones(self):
        buffer = Framebuffer(1, 1)
        buffer.clear((0, 0, 0))
        buffer.draw_image(Image(1, 1, bytes([1, 1, 1, 255])), 0, 0)
        buffer.draw_image(Image(1, 1, bytes([2, 2, 2, 255])), 0, 0)
        self.assertEqual(self.pixel(buffer, 0, 0), (2, 2, 2, 255))

    def test_clips_at_the_right_and_bottom_edges(self):
        buffer = Framebuffer(2, 2)
        buffer.clear((0, 0, 0))
        buffer.draw_image(Image(2, 2, bytes([5, 5, 5, 255]) * 4), 1, 1)
        self.assertEqual(self.pixel(buffer, 1, 1), (5, 5, 5, 255))
        self.assertEqual(self.pixel(buffer, 0, 0), (0, 0, 0, 255))

    def test_clips_at_the_left_and_top_edges(self):
        buffer = Framebuffer(2, 2)
        buffer.clear((0, 0, 0))
        buffer.draw_image(Image(2, 2, bytes([5, 5, 5, 255]) * 4), -1, -1)
        self.assertEqual(self.pixel(buffer, 0, 0), (5, 5, 5, 255))
        self.assertEqual(self.pixel(buffer, 1, 1), (0, 0, 0, 255))

    def test_a_fully_offscreen_image_draws_nothing(self):
        buffer = Framebuffer(2, 2)
        buffer.clear((0, 0, 0))
        before = bytes(buffer.pixels)
        buffer.draw_image(Image(1, 1, bytes([9, 9, 9, 255])), 50, 50)
        buffer.draw_image(Image(1, 1, bytes([9, 9, 9, 255])), -50, -50)
        self.assertEqual(bytes(buffer.pixels), before)

    def test_transparent_images_clip_too(self):
        """The alpha path has its own loop, so it needs its own clipping."""
        buffer = Framebuffer(2, 2)
        buffer.clear((0, 0, 0))
        buffer.draw_image(Image(2, 2, bytes([5, 5, 5, 128]) * 4), -1, -1)
        self.assertNotEqual(self.pixel(buffer, 0, 0), (0, 0, 0, 255))
        self.assertEqual(self.pixel(buffer, 1, 1), (0, 0, 0, 255))


class TestRenderingThroughTheApplication(unittest.TestCase):
    """The whole path, headlessly: draw.image -> loop -> backend.present.

    The null backend keeps the last frame it was given, so what the engine
    would have put on screen can be inspected without a display.
    """

    def setUp(self):
        from trjoludus.scene import current_scene

        current_scene().clear()
        self.addCleanup(current_scene().clear)

    def run_game(self, on_start, frames=2, size=(16, 12)):
        import trjoludus as tl
        from trjoludus.platform.null import NullBackend

        windows = []

        class Backend(NullBackend):
            def create_window(self, title, width, height):
                window = super().create_window(title, width, height)
                windows.append(window)
                return window

        class Recorded(tl.Game):
            def __init__(self):
                self.count = 0

            def on_start(self):
                on_start()

            def on_update(self, dt):
                self.count += 1
                if self.count >= frames:
                    self.quit()

        tl.Application(Recorded(), size=size, max_fps=None,
                       backend=Backend()).run()
        return windows[0]

    def pixel(self, window, x, y):
        width = window.last_frame_size[0]
        i = (y * width + x) * 4
        return tuple(window.last_frame[i:i + 4])

    def test_frames_reach_the_backend(self):
        window = self.run_game(lambda: None, frames=3)
        self.assertEqual(window.frames_presented, 3)

    def test_frames_match_the_window_size(self):
        window = self.run_game(lambda: None, size=(20, 10))
        self.assertEqual(window.last_frame_size, (20, 10))
        self.assertEqual(len(window.last_frame), 20 * 10 * 4)

    def test_an_empty_scene_renders_the_clear_colour(self):
        window = self.run_game(lambda: None)
        red, green, blue = DEFAULT_CLEAR_COLOUR
        self.assertEqual(self.pixel(window, 0, 0), (blue, green, red, 255))

    def test_a_drawn_object_appears_in_the_frame(self):
        path = _sprite(self, 4, 4, (200, 100, 50))

        def start():
            import trjoludus as tl

            tl.draw.image(2, 3, path, "player")

        window = self.run_game(start)
        self.assertEqual(self.pixel(window, 2, 3), (50, 100, 200, 255))

    def test_an_object_lands_where_it_was_placed(self):
        """Top-left origin, y downward: (2, 3) is two right and three down."""
        path = _sprite(self, 1, 1, (200, 100, 50))

        def start():
            import trjoludus as tl

            tl.draw.image(2, 3, path, "player")

        window = self.run_game(start)
        red, green, blue = DEFAULT_CLEAR_COLOUR
        self.assertEqual(self.pixel(window, 2, 3), (50, 100, 200, 255))
        self.assertEqual(self.pixel(window, 3, 2), (blue, green, red, 255))

    def test_moving_an_object_moves_what_is_drawn(self):
        path = _sprite(self, 1, 1, (200, 100, 50))
        state = {}

        def start():
            import trjoludus as tl

            state["player"] = tl.draw.image(0, 0, path, "player")

        original_run = self.run_game

        def start_and_move():
            start()
            state["player"].x = 5

        window = original_run(start_and_move)
        self.assertEqual(self.pixel(window, 5, 0), (50, 100, 200, 255))

    def test_an_invisible_object_is_not_drawn(self):
        path = _sprite(self, 2, 2, (200, 100, 50))

        def start():
            import trjoludus as tl

            tl.draw.image(0, 0, path, "player").visible = False

        window = self.run_game(start)
        red, green, blue = DEFAULT_CLEAR_COLOUR
        self.assertEqual(self.pixel(window, 0, 0), (blue, green, red, 255))

    def test_the_scene_is_cleared_when_a_run_finishes(self):
        """A second run must not inherit the first game's objects."""
        from trjoludus.scene import current_scene

        path = _sprite(self, 1, 1, (1, 2, 3))

        def start():
            import trjoludus as tl

            tl.draw.image(0, 0, path, "player")

        self.run_game(start)
        self.assertEqual(len(current_scene()), 0)
        self.run_game(start)  # the same name again must not collide


def _sprite(test, width, height, rgb):
    """Write an opaque single-colour PNG and return its path."""
    red, green, blue = rgb
    pixels = bytes([red, green, blue, 255]) * (width * height)
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    path = Path(directory.name) / "sprite.png"
    path.write_bytes(build_png(width, height, pixels))
    return path


if __name__ == "__main__":
    unittest.main()
