"""Scaled text, drawn by both renderers, compared byte for byte.

Scaled text used to be drawn by the *drawing*, as a `fill_rect` per lit font
pixel. That crossed into native code once per pixel and measured slower than
the Python renderer it was supposed to beat. It is now one call, and these
exist to make sure that stayed exactly as visible as it was.

The Python renderer is the reference. Every case here is drawn twice and the
two buffers compared -- there is no expected-pixels table, because a table
written by hand would only say what someone thought the font looked like.

The differential half skips when there is no native library. What is left
still checks that the Python renderer draws what it always drew.
"""

import unittest

from trjoludus import draw, engine, font
from trjoludus.native import library
from trjoludus.native import renderer as native_renderer
from trjoludus.rendering_python import Framebuffer

#: Scales worth checking. Whole numbers, fractions that land on a half (where
#: Python's round-half-to-even and Rust's round-half-away-from-zero disagree),
#: and scales below one.
SCALES = (0.25, 0.5, 0.75, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 7.25, 8.0, 12.5)

TEXTS = ("A", "SCORE 1234567890", "gjpqy", "Hello, World!", " ", "iiiiii",
         "WWWWWW", "The quick brown fox")


class ScaledTextTestCase(unittest.TestCase):
    def setUp(self):
        engine.end_run()
        library.forget()
        native_renderer.forget()
        self.addCleanup(native_renderer.forget)
        self.addCleanup(library.forget)
        self.addCleanup(engine.end_run)

    def python(self, width=400, height=200):
        return Framebuffer(width, height)

    def native(self, width=400, height=200):
        if not native_renderer.available():
            self.skipTest("no native renderer built here; run cargo build")
        return native_renderer.NativeFramebuffer(width, height)

    def assertSamePixels(self, draw_it, size=(400, 200), note=""):
        """Draw the same thing with each renderer and compare every byte."""
        one, two = self.python(*size), self.native(*size)
        for surface in (one, two):
            surface.clear((0, 0, 0))
            draw_it(surface)
        expected, found = bytes(one.pixels), bytes(two.pixels)
        if expected == found:
            return
        for index, (a, b) in enumerate(zip(expected, found)):
            if a != b:
                pixel = index // 4
                self.fail(
                    f"byte {index} differs{note} -- pixel "
                    f"({pixel % size[0]}, {pixel // size[0]}): "
                    f"Python {a}, native {b}")
        self.fail(f"different lengths{note}")


class TestTheTwoRenderersAgree(ScaledTextTestCase):
    def test_every_scale_with_a_typical_label(self):
        for scale in SCALES:
            with self.subTest(scale=scale):
                self.assertSamePixels(
                    lambda surface, s=scale: surface.draw_text_scaled(
                        "SCORE 1234567890", 7, 5, s, (250, 128, 3)),
                    note=f" at scale {scale}")

    def test_every_string_at_a_typical_scale(self):
        for text in TEXTS:
            with self.subTest(text=text):
                self.assertSamePixels(
                    lambda surface, t=text: surface.draw_text_scaled(
                        t, 10, 10, 2.0, (255, 255, 255)),
                    note=f" for {text!r}")

    def test_every_character_the_font_has(self):
        """One long string of everything, so no glyph goes unchecked."""
        every = "".join(sorted(font.GLYPHS)) if hasattr(font, "GLYPHS") else (
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:;!?'\"-+*/=()[]<>%#@&_")
        for chunk in range(0, len(every), 20):
            piece = every[chunk:chunk + 20]
            with self.subTest(characters=piece):
                self.assertSamePixels(
                    lambda surface, p=piece: surface.draw_text_scaled(
                        p, 4, 4, 3.0, (12, 240, 60)),
                    size=(600, 100), note=f" for {piece!r}")

    def test_an_unknown_character(self):
        self.assertSamePixels(
            lambda surface: surface.draw_text_scaled(
                "aé中b", 5, 5, 4.0, (200, 200, 200)))

    def test_empty_text_draws_nothing(self):
        self.assertSamePixels(
            lambda surface: surface.draw_text_scaled("", 5, 5, 4.0, (1, 2, 3)))

    def test_a_fractional_position(self):
        for x in (5.5, 5.4, 5.6, -0.5):
            with self.subTest(x=x):
                self.assertSamePixels(
                    lambda surface, at=x: surface.draw_text_scaled(
                        "Ay", at, 7.5, 2.5, (9, 9, 200)),
                    note=f" at x={x}")

    def test_clipping_at_every_edge(self):
        for x, y in ((-30, 10), (380, 10), (10, -20), (10, 190),
                     (-500, -500), (5000, 5000)):
            with self.subTest(at=(x, y)):
                self.assertSamePixels(
                    lambda surface, a=x, b=y: surface.draw_text_scaled(
                        "CLIPPED", a, b, 3.0, (255, 0, 255)),
                    note=f" at ({x}, {y})")

    def test_a_buffer_smaller_than_one_block(self):
        self.assertSamePixels(
            lambda surface: surface.draw_text_scaled("M", 0, 0, 20.0,
                                                     (1, 250, 1)),
            size=(4, 4))

    def test_text_longer_than_the_buffer_is_wide(self):
        self.assertSamePixels(
            lambda surface: surface.draw_text_scaled(
                "A" * 200, 0, 20, 4.0, (7, 7, 7)), size=(320, 240))

    def test_colours_come_across_unchanged(self):
        for colour in ((0, 0, 0), (255, 255, 255), (1, 128, 254)):
            with self.subTest(colour=colour):
                self.assertSamePixels(
                    lambda surface, c=colour: surface.draw_text_scaled(
                        "Wg", 10, 10, 5.0, c), note=f" in {colour}")

    def test_it_never_leaves_a_pixel_transparent(self):
        """Every byte the renderer writes is opaque, as everywhere else."""
        surface = self.native(60, 60)
        surface.clear((0, 0, 0))
        surface.draw_text_scaled("O", 5, 5, 6.0, (200, 100, 50))
        self.assertEqual(set(surface.pixels[3::4]), {255})


class TestItGoesThroughTheWholeStack(ScaledTextTestCase):
    """A drawing on a UI list, not just the framebuffer method."""

    def label(self, scale):
        engine.end_run()
        draw.text(10, 10, "HELLO 42", (255, 255, 0)).set.scale(scale)
        return engine.current().drawings

    def test_a_scaled_drawing_renders_the_same_on_both(self):
        for scale in (1.0, 2.0, 3.5, 8.0):
            with self.subTest(scale=scale):
                lists = self.label(scale)
                one, two = self.python(), self.native()
                for surface in (one, two):
                    surface.clear((0, 0, 0))
                    lists.render(surface)
                self.assertEqual(bytes(one.pixels), bytes(two.pixels),
                                 f"a drawing at scale {scale} differs")

    def test_scale_one_still_takes_the_unscaled_path(self):
        """Not a regression dressed up: scale 1 is draw_text, as before."""

        class Watched(Framebuffer):
            asked = []

            def draw_text_scaled(self, *arguments):
                Watched.asked.append(arguments)

        lists = self.label(1.0)
        lists.render(Watched(200, 100))
        self.assertEqual(Watched.asked, [], "scale 1 went the scaled route")

    def test_the_drawing_no_longer_draws_for_itself(self):
        """The regression this replaced, stated so it cannot come back."""
        from trjoludus import ui

        self.assertFalse(hasattr(ui.Drawable, "_render_scaled_text"),
                         "the per-pixel scaled-text loop is back in ui.py")

    def test_both_renderers_offer_the_same_surface(self):
        for name in ("clear", "set_pixel", "fill_rect", "draw_line",
                     "draw_text", "draw_text_scaled", "draw_image", "resize"):
            with self.subTest(method=name):
                self.assertTrue(hasattr(Framebuffer, name))
                self.assertTrue(
                    hasattr(native_renderer.NativeFramebuffer, name))


class TestTheEdgeTables(ScaledTextTestCase):
    """Rounding stays in Python, and both sides use the same numbers."""

    def test_an_edge_table_has_one_more_entry_than_blocks(self):
        self.assertEqual(len(font.block_edges(5, 2.0)), 6)

    def test_it_is_pythons_rounding(self):
        # round(0.5) is 0 and round(1.5) is 2 -- half to even. Rust's f64
        # round would give 1 and 2, which is the disagreement being avoided.
        self.assertEqual(font.block_edges(3, 0.5), [0, 0, 1, 2])

    def test_edges_never_go_backwards(self):
        for scale in SCALES:
            with self.subTest(scale=scale):
                edges = font.block_edges(40, scale)
                self.assertEqual(edges, sorted(edges))

    def test_a_scale_of_one_is_the_identity(self):
        self.assertEqual(font.block_edges(6, 1.0), [0, 1, 2, 3, 4, 5, 6])

    def test_the_native_renderer_sends_enough_edges(self):
        """A short table would silently stop drawing part of the string."""
        advance = font.CHARACTER_WIDTH + font.SPACING
        for length in (1, 2, 16, 100):
            with self.subTest(length=length):
                needed = (length - 1) * advance + font.CHARACTER_WIDTH
                self.assertEqual(
                    len(font.block_edges(needed, 2.0)), needed + 1)


class TestScaledTextIsNotSlowerThanPython(ScaledTextTestCase):
    """The regression that started this, as a test rather than a memory.

    Timing, so it is generous: the claim is not "native is 8x faster" but
    "native is not *slower*", which is what was actually wrong. A margin of
    two either way absorbs a loaded machine without letting a real regression
    through -- the fault this replaces was consistently 2.1x the wrong way.
    """

    def time(self, surface, text, scale, rounds=40):
        import time

        best = None
        for _ in range(5):
            start = time.perf_counter()
            for _ in range(rounds):
                surface.draw_text_scaled(text, 5, 5, scale, (250, 250, 250))
            taken = (time.perf_counter() - start) / rounds
            best = taken if best is None else min(best, taken)
        return best

    def test_it_is_not_slower_than_the_python_renderer(self):
        text = "SCORE 1234567890"
        for scale in (2.0, 4.0, 8.0):
            with self.subTest(scale=scale):
                one, two = self.python(800, 600), self.native(800, 600)
                in_python = self.time(one, text, scale)
                natively = self.time(two, text, scale)
                ratio = natively / in_python
                self.assertLess(
                    natively, in_python * 2,
                    f"scaled text at scale {scale} took {ratio:.1f}x the "
                    f"Python renderer's time; it used to be 2.1x and that "
                    f"was the bug")

    def test_it_crosses_the_boundary_once(self):
        """The property behind the speed, checked without a clock."""
        surface = self.native(200, 100)
        calls = surface._call
        counted = {"n": 0}
        original = calls["trjoludus_render_fill_rect"]

        def counting(*arguments):
            counted["n"] += 1
            return original(*arguments)

        calls["trjoludus_render_fill_rect"] = counting
        try:
            surface.draw_text_scaled("SCORE 1234567890", 5, 5, 2.0,
                                     (1, 2, 3))
        finally:
            calls["trjoludus_render_fill_rect"] = original
        self.assertEqual(counted["n"], 0,
                         "scaled text is back to a fill_rect per font pixel")


if __name__ == "__main__":
    unittest.main()
