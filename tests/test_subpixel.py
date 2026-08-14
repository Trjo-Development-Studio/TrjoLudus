"""Tests for fractional positions.

A position is a number; a pixel is not. These check that the two stay
separate: an object or drawing keeps whatever position it was given, exactly,
and rounding happens once -- when something is turned into pixels.

The reason it matters is movement measured in seconds. At 60 frames a second,
100 pixels a second is 1.67 pixels a frame. An engine that could only hold
whole pixels would either drop that fraction every frame or round it up every
frame, and neither ends up 100 pixels along after a second.

Timing here is a fake time source, never the real clock, so the frame-rate
comparisons are exact rather than raced.
"""

import unittest

from trjoludus import Game, color, create, draw
from trjoludus.app import Application
from trjoludus.clock import Clock
from trjoludus.image import Image
from trjoludus.platform.null import NullBackend
from trjoludus.render import DEFAULT_CLEAR_COLOUR, Framebuffer
from trjoludus.scene import GameObject, SceneObject, current_scene
from trjoludus.ui import current_ui

RED = (250, 0, 0)


def fake_clock(step, frames):
    """A clock whose every frame is exactly ``step`` seconds long."""
    ticks = iter([step * index for index in range(frames + 3)])
    return Clock(max_fps=None, time_source=lambda: next(ticks),
                 sleep_function=lambda seconds: None)


class SubPixelTestCase(unittest.TestCase):
    def setUp(self):
        current_scene().clear()
        current_ui().clear()
        self.addCleanup(current_scene().clear)
        self.addCleanup(current_ui().clear)
        self.image = Image(4, 4, bytes([0, 0, 250, 255]) * 16)

    def player(self, x=0, y=0):
        current_scene().add(SceneObject("player", self.image, x, y))
        return GameObject("player")

    def paint(self, width=60, height=40):
        buffer = Framebuffer(width, height)
        buffer.clear()
        for obj in current_scene().objects():
            if obj.visible:
                buffer.draw_image(obj.image, obj.x, obj.y, obj.scale)
        current_ui().render(buffer)
        return buffer

    def pixel(self, buffer, x, y):
        index = (y * buffer.width + x) * 4
        blue, green, red, _ = buffer.pixels[index:index + 4]
        return (red, green, blue)

    def leftmost_drawn(self, buffer, y):
        for x in range(buffer.width):
            if self.pixel(buffer, x, y) != DEFAULT_CLEAR_COLOUR:
                return x
        return None


class TestFractionalObjectPositions(SubPixelTestCase):
    def test_set_x_keeps_the_fraction(self):
        player = self.player()
        player.set.x(100.5)
        self.assertEqual(player.x, 100.5)

    def test_set_y_keeps_the_fraction(self):
        player = self.player()
        player.set.y(50.25)
        self.assertEqual(player.y, 50.25)

    def test_assignment_keeps_the_fraction(self):
        player = self.player()
        player.set.x = 100.5
        player.set.y = 0.75
        self.assertEqual(player.position, (100.5, 0.75))

    def test_the_plain_attribute_keeps_it_too(self):
        player = self.player()
        player.x = 7.5
        self.assertEqual(player.x, 7.5)

    def test_move_keeps_the_fraction(self):
        player = self.player()
        player.move.x(1.5)
        player.move.y(-0.25)
        self.assertEqual(player.position, (1.5, -0.25))

    def test_fractions_add_up_exactly(self):
        player = self.player()
        for _ in range(4):
            player.move.x(0.25)
        self.assertEqual(player.x, 1.0)

    def test_a_fraction_is_not_lost_between_frames(self):
        """Sixty steps of 1/60 of 100 pixels is 100 pixels, not 60 or 120."""
        player = self.player()
        for _ in range(60):
            player.move.x(100 * (1 / 60))
        self.assertAlmostEqual(player.x, 100.0, places=6)

    def test_creation_takes_a_fraction(self):
        import pathlib
        import struct
        import tempfile
        import zlib

        def chunk(tag, body):
            return (struct.pack(">I", len(body)) + tag + body
                    + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

        rows = b"".join(b"\x00" + bytes([250, 0, 0, 255]) * 4
                        for _ in range(4))
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "block.png"
            path.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows))
                + chunk(b"IEND", b""))
            create.image(1.5, 2.5, str(path), "block")

        self.assertEqual(GameObject("block").position, (1.5, 2.5))

    def test_position_reports_the_exact_value(self):
        """There is no second, more precise API: this is the position."""
        player = self.player()
        player.set.x(3.75)
        self.assertEqual(player.position, (3.75, 0))
        self.assertNotIsInstance(player.x, int)

    def test_what_is_not_a_position(self):
        player = self.player()
        for bad in ("1", None, True, [1], {}):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    player.set.x(bad)
        for bad in (float("inf"), float("-inf"), float("nan")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    player.set.x(bad)
        self.assertEqual(player.x, 0)


class TestIntegersAreUnchanged(SubPixelTestCase):
    def test_an_integer_position_stays_an_integer(self):
        player = self.player()
        player.set.x(100)
        self.assertIsInstance(player.x, int)
        self.assertEqual(player.x, 100)

    def test_integer_movement_stays_an_integer(self):
        player = self.player(10, 10)
        player.move.x(50)
        player.move.y(-5)
        self.assertIsInstance(player.x, int)
        self.assertEqual(player.position, (60, 5))

    def test_an_integer_drawing_position_stays_an_integer(self):
        box = draw.list("menu").rect(10, 10, 5, 5, color.blue)
        box.move.x(5)
        self.assertIsInstance(box.x, int)
        self.assertEqual(box.position, (15, 10))

    def test_whole_pixels_land_exactly_where_they_did(self):
        player = self.player(7, 3)
        buffer = self.paint()
        self.assertEqual(self.pixel(buffer, 7, 3), RED)
        self.assertEqual(self.pixel(buffer, 6, 3), DEFAULT_CLEAR_COLOUR)
        self.assertEqual(player.position, (7, 3))

    def test_a_whole_number_given_as_a_float_still_draws_there(self):
        self.player(7.0, 3.0)
        buffer = self.paint()
        self.assertEqual(self.pixel(buffer, 7, 3), RED)


class TestTheRendererRounds(SubPixelTestCase):
    def test_an_object_lands_on_a_whole_pixel(self):
        self.player(10.4, 0)
        self.assertEqual(self.leftmost_drawn(self.paint(), 2), 10)

    def test_it_rounds_rather_than_truncating(self):
        self.player(10.6, 0)
        self.assertEqual(self.leftmost_drawn(self.paint(), 2), 11)

    def test_a_fraction_below_a_pixel_does_not_move_it(self):
        self.player(10, 0)
        before = self.leftmost_drawn(self.paint(), 2)
        current_scene().require("player").x = 10.2
        self.assertEqual(self.leftmost_drawn(self.paint(), 2), before)

    def test_crossing_the_halfway_point_moves_it_one_pixel(self):
        player = self.player(10, 0)
        seen = []
        for offset in (0.0, 0.4, 0.6, 1.0):
            player.set.x(10 + offset)
            seen.append(self.leftmost_drawn(self.paint(), 2))
        self.assertEqual(seen, [10, 10, 11, 11])

    def test_a_drawing_lands_on_a_whole_pixel(self):
        draw.list("menu").rect(5.6, 0, 4, 4, color.red)
        self.assertEqual(self.leftmost_drawn(self.paint(), 2), 6)

    def test_a_scaled_object_rounds_its_position_too(self):
        player = self.player(10.6, 0)
        player.set.scale(2)
        self.assertEqual(self.leftmost_drawn(self.paint(), 2), 11)

    def test_the_renderer_accepts_a_fraction_directly(self):
        buffer = Framebuffer(20, 20)
        buffer.clear()
        buffer.fill_rect(2.6, 2.4, 4, 4, color.red)
        self.assertEqual(self.pixel(buffer, 3, 2), RED)
        self.assertEqual(self.pixel(buffer, 2, 2), DEFAULT_CLEAR_COLOUR)

    def test_every_drawing_method_takes_a_fraction(self):
        buffer = Framebuffer(20, 20)
        buffer.clear()
        buffer.set_pixel(1.6, 1.6, color.red)
        buffer.draw_line(0.4, 5.4, 6.4, 5.4, color.red)
        buffer.draw_text("i", 0.6, 10.6, color.red)
        buffer.draw_image(self.image, 12.6, 12.6)
        self.assertEqual(self.pixel(buffer, 2, 2), RED)
        self.assertEqual(self.pixel(buffer, 3, 5), RED)
        self.assertEqual(self.pixel(buffer, 13, 13), RED)


class TestHitTestingMatchesTheRendering(SubPixelTestCase):
    def test_bounds_are_whole_pixels(self):
        box = draw.list("menu").rect(10.6, 20.4, 5, 5, color.blue)
        self.assertEqual(box.bounds, (11, 20, 16, 25))

    def test_screen_position_is_the_rounded_position(self):
        box = draw.list("menu").rect(10.6, 20.4, 5, 5, color.blue)
        self.assertEqual(box.position, (10.6, 20.4))
        self.assertEqual(box.screen_position, (11, 20))

    def test_the_hitbox_covers_exactly_what_is_drawn(self):
        for offset in (0.0, 0.2, 0.5, 0.6, 0.9):
            with self.subTest(offset=offset):
                current_ui().clear()
                box = draw.list("menu").rect(10 + offset, 5, 6, 6,
                                             color.red)
                buffer = self.paint()
                left, top, right, bottom = box.bounds
                self.assertEqual(self.pixel(buffer, left, top), RED,
                                 "the hitbox starts before the pixels")
                self.assertEqual(self.pixel(buffer, right - 1, bottom - 1),
                                 RED, "the hitbox ends after the pixels")
                self.assertEqual(self.pixel(buffer, left - 1, top),
                                 DEFAULT_CLEAR_COLOUR,
                                 "a pixel outside the hitbox was drawn")

    def test_contains_follows_the_rounded_position(self):
        box = draw.list("menu").rect(10.6, 0, 5, 5, color.blue)
        self.assertTrue(box.contains(11, 0))
        self.assertFalse(box.contains(10, 0))

    def test_a_line_keeps_its_length_when_its_ends_are_fractional(self):
        line = draw.list("menu").line(0.4, 0, 10.4, 0, color.blue)
        left, top, right, bottom = line.bounds
        self.assertEqual(right - left, 11)

    def test_moving_by_fractions_moves_the_hitbox_when_it_crosses(self):
        box = draw.list("menu").rect(10, 0, 5, 5, color.blue)
        seen = []
        for _ in range(4):
            box.move.x(0.25)
            seen.append(box.bounds[0])
        # 10.25, 10.5, 10.75, 11.0 -- Python rounds .5 to even, so 10 then 11.
        self.assertEqual(seen, [10, 10, 11, 11])
        self.assertEqual(box.x, 11.0)

    def test_hover_uses_the_rounded_position(self):
        from trjoludus.events import MouseMoved

        answers = []
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_start(self):
                self.box = draw.list("menu").rect(10.6, 0, 5, 5, color.blue)

            def on_update(self, dt):
                self.count += 1
                if self.count == 1:
                    backend.windows[0].simulate_event(MouseMoved(x=11, y=2))
                    return
                answers.append(self.box.mouse.hover())
                if self.count >= 3:
                    self.quit()

        Application(G(), size=(40, 30), max_fps=None, backend=backend).run()
        self.assertTrue(all(answers), answers)


class TestFrameRateIndependence(SubPixelTestCase):
    """The same seconds cover the same distance at any frame rate."""

    def travel(self, step, frames, speed=100):
        player = self.player()
        clock = fake_clock(step, frames)
        for _ in range(frames + 1):      # +1: the first tick is the baseline
            player.move.x(speed * clock.tick())
        return player.x

    def test_ten_frames_a_second_and_a_hundred_agree(self):
        slow = self.travel(0.1, 10)
        current_scene().clear()
        fast = self.travel(0.01, 100)
        self.assertAlmostEqual(slow, fast, places=6)
        self.assertAlmostEqual(fast, 100.0, places=6)

    def test_sixty_frames_a_second_lands_on_the_hundredth_pixel(self):
        self.assertAlmostEqual(self.travel(1 / 60, 60), 100.0, places=6)

    def test_no_drift_over_many_seconds(self):
        travelled = self.travel(1 / 60, 600)     # ten seconds
        self.assertAlmostEqual(travelled, 1000.0, places=4)

    def test_a_drawing_moves_the_same_way(self):
        box = draw.list("menu").rect(0, 0, 4, 4, color.blue)
        clock = fake_clock(1 / 60, 60)
        for _ in range(61):
            box.move.x(100 * clock.tick())
        self.assertAlmostEqual(box.x, 100.0, places=6)
        self.assertEqual(box.screen_position[0], 100)

    def test_it_ends_up_on_screen_where_it_should(self):
        player = self.player()
        clock = fake_clock(1 / 60, 30)
        for _ in range(31):
            player.move.x(100 * clock.tick())     # half a second: 50 pixels
        self.assertEqual(self.leftmost_drawn(self.paint(), 2), 50)


class TestScaleStillWorks(SubPixelTestCase):
    def test_a_fractional_position_with_a_scale(self):
        player = self.player(10.6, 5.4)
        player.set.scale(2)
        self.assertEqual(player.scale, 2.0)
        self.assertEqual(player.size, (8, 8))
        self.assertEqual(self.leftmost_drawn(self.paint(), 6), 11)

    def test_scaling_does_not_disturb_the_fraction(self):
        player = self.player()
        player.set.x(10.75)
        player.set.scale(3)
        player.remove.scale(1)
        self.assertEqual(player.x, 10.75)

    def test_a_scaled_drawing_keeps_hitbox_and_pixels_together(self):
        box = draw.list("menu").rect(10.6, 5, 4, 4, color.red)
        box.set.scale(2)
        buffer = self.paint()
        left, top, right, bottom = box.bounds
        self.assertEqual(self.pixel(buffer, left, top), RED)
        self.assertEqual(self.pixel(buffer, right - 1, bottom - 1), RED)
        self.assertEqual(self.pixel(buffer, right, bottom),
                         DEFAULT_CLEAR_COLOUR)

    def test_moving_a_scaled_object_by_fractions(self):
        player = self.player()
        player.set.scale(2)
        for _ in range(4):
            player.move.x(0.25)
        self.assertEqual(player.x, 1.0)
        self.assertEqual(player.scale, 2.0)


class TestThroughARealRun(SubPixelTestCase):
    def test_fractional_movement_reaches_the_frame(self):
        frames = []
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_start(self):
                current_scene().add(
                    SceneObject("player", Image(4, 4,
                                                bytes([0, 0, 250, 255]) * 16),
                                0, 0))
                self.player = GameObject("player")

            def on_update(self, dt):
                self.count += 1
                self.player.move.x(0.5)
                if self.count >= 20:
                    frames.append(bytes(backend.windows[0].last_frame))
                    self.travelled = self.player.x
                    self.quit()

        game = G()
        Application(game, size=(60, 40), max_fps=None, backend=backend).run()
        # Twenty half-pixels is ten whole ones, with nothing lost on the way.
        self.assertEqual(game.travelled, 10.0)

        frame = frames[0]
        lit = [index // 4 % 60 for index in range(0, len(frame), 4)
               if (frame[index + 2], frame[index + 1],
                   frame[index]) != DEFAULT_CLEAR_COLOUR]
        self.assertEqual(min(lit), 10)

    def test_a_second_run_starts_from_the_same_place(self):
        seen = []

        class G(Game):
            def on_start(self):
                current_scene().add(
                    SceneObject("player", Image(2, 2,
                                                bytes([0, 0, 250, 255]) * 4),
                                0.5, 0))
                seen.append(GameObject("player").x)


            def on_update(self, dt):
                self.quit()

        game = G()
        for _ in range(2):
            Application(game, size=(40, 30), max_fps=None,
                        backend=NullBackend()).run()
        self.assertEqual(seen, [0.5, 0.5])


if __name__ == "__main__":
    unittest.main()
