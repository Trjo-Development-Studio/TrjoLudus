"""Tests for named object handles and the setter API.

The model these check: ``create.image(...)`` makes an object and registers it
under a name; ``GameObject(name)`` finds that object and never makes a second
one. A handle is a way of reaching a record, not the record itself, so any
number of handles can name the same thing and all of them see the same
changes -- including a handle made, used and thrown away in one expression.

Headless throughout. Nothing waits for input.
"""

import struct
import unittest
import zlib

from trjoludus import Game, GameObject, create
from trjoludus.app import Application
from trjoludus.image import Image
from trjoludus.platform.null import NullBackend
from trjoludus.render import DEFAULT_CLEAR_COLOUR, Framebuffer
from trjoludus.scene import SceneError, SceneObject, current_scene
from trjoludus.ui import current_ui

RED = (250, 0, 0)


def solid_png(width=4, height=4, colour=RED, path=None):
    """Write a small solid-colour PNG and return its path."""
    red, green, blue = colour
    rows = b"".join(b"\x00" + bytes([red, green, blue, 255]) * width
                    for _ in range(height))

    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    data = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6,
                                         0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b""))
    path.write_bytes(data)
    return str(path)


class ObjectTestCase(unittest.TestCase):
    """Puts one object called "player" in the scene, without touching disk."""

    def setUp(self):
        current_scene().clear()
        current_ui().clear()
        self.addCleanup(current_scene().clear)
        self.addCleanup(current_ui().clear)
        self.image = Image(4, 4, bytes([0, 0, 250, 255]) * 16)
        current_scene().add(SceneObject("player", self.image, 10, 10))

    def record(self):
        """The scene's own record, reached without going through a handle."""
        return current_scene().require("player")


class TestCreatingAndRetrieving(unittest.TestCase):
    def setUp(self):
        current_scene().clear()
        self.addCleanup(current_scene().clear)

    def test_create_image_registers_the_object(self):
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = solid_png(path=pathlib.Path(folder) / "player.png")
            create.image(100, 100, path, "player")

        self.assertIn("player", current_scene())
        self.assertEqual(current_scene().names, ("player",))

    def test_the_registered_object_is_where_it_was_put(self):
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = solid_png(path=pathlib.Path(folder) / "player.png")
            create.image(100, 100, path, "player")

        self.assertEqual(GameObject("player").position, (100, 100))

    def test_game_object_retrieves_it(self):
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = solid_png(path=pathlib.Path(folder) / "player.png")
            created = create.image(100, 100, path, "player")

        found = GameObject("player")
        self.assertEqual(found.name, "player")
        if isinstance(created, GameObject):
            self.assertEqual(created.position, found.position)

    def test_game_object_does_not_create_anything(self):
        with self.assertRaises(SceneError):
            GameObject("nobody")
        self.assertEqual(len(current_scene()), 0)

    def test_the_error_lists_what_does_exist(self):
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = solid_png(path=pathlib.Path(folder) / "player.png")
            create.image(0, 0, path, "player")

        with self.assertRaises(SceneError) as caught:
            GameObject("plyaer")
        self.assertIn("player", str(caught.exception))

    def test_a_name_must_be_a_string(self):
        with self.assertRaises(TypeError):
            GameObject(7)


class TestHandlesShareOneRecord(ObjectTestCase):
    def test_two_handles_reach_the_same_record(self):
        a = GameObject("player")
        b = GameObject("player")
        self.assertIsNot(a, b, "these are separate handles")
        self.assertIs(a._object, b._object, "onto one record")

    def test_a_change_through_one_is_seen_through_the_other(self):
        a = GameObject("player")
        b = GameObject("player")
        a.set.x(200)
        self.assertEqual(b.x, 200)
        b.move.y(30)
        self.assertEqual(a.y, 40)

    def test_a_change_through_a_handle_reaches_the_scene(self):
        GameObject("player").set.x(123)
        self.assertEqual(self.record().x, 123)

    def test_visibility_is_shared(self):
        a = GameObject("player")
        b = GameObject("player")
        a.visible = False
        self.assertFalse(b.visible)
        self.assertFalse(self.record().visible)

    def test_handles_compare_equal(self):
        self.assertEqual(GameObject("player"), GameObject("player"))

    def test_a_handle_made_after_a_change_sees_it(self):
        GameObject("player").set.x(77)
        self.assertEqual(GameObject("player").x, 77)


class TestDirectHandles(ObjectTestCase):
    """No variable required: make the handle, use it, drop it."""

    def test_move_through_a_direct_handle(self):
        GameObject("player").move.x(50)
        GameObject("player").move.y(-5)
        self.assertEqual(GameObject("player").position, (60, 5))

    def test_set_through_a_direct_handle(self):
        GameObject("player").set.x(100)
        GameObject("player").set.y(50)
        self.assertEqual(GameObject("player").position, (100, 50))

    def test_scale_through_a_direct_handle(self):
        GameObject("player").set.scale(1.25)
        self.assertEqual(GameObject("player").scale, 1.25)

    def test_assignment_through_a_direct_handle(self):
        GameObject("player").set.x = 100
        GameObject("player").set.scale = 2
        self.assertEqual(GameObject("player").position, (100, 10))
        self.assertEqual(GameObject("player").scale, 2.0)

    def test_destroy_through_a_direct_handle(self):
        GameObject("player").destroy()
        self.assertNotIn("player", current_scene())

    def test_reading_through_a_direct_handle(self):
        GameObject("player").set.x(64)
        self.assertEqual(GameObject("player").x, 64)
        self.assertEqual(GameObject("player").size, (4, 4))
        self.assertTrue(GameObject("player").visible)

    def test_the_variable_form_still_works(self):
        player = GameObject("player")
        player.move.x(50)
        player.set.y(5)
        self.assertEqual(player.position, (60, 5))
        self.assertEqual(GameObject("player").position, (60, 5))

    def test_mixing_the_two_forms(self):
        player = GameObject("player")
        GameObject("player").set.x(200)
        self.assertEqual(player.x, 200)
        player.move.x(-100)
        self.assertEqual(GameObject("player").x, 100)


class TestAbsoluteAndRelative(ObjectTestCase):
    def setUp(self):
        super().setUp()
        self.player = GameObject("player")

    def test_set_x_is_absolute(self):
        self.player.set.x(100)
        self.player.set.x(100)
        self.assertEqual(self.player.x, 100)

    def test_set_y_is_absolute(self):
        self.player.set.y(50)
        self.player.set.y(50)
        self.assertEqual(self.player.y, 50)

    def test_move_x_is_relative(self):
        self.player.move.x(50)
        self.player.move.x(50)
        self.assertEqual(self.player.x, 110)

    def test_move_y_is_relative(self):
        self.player.move.y(-4)
        self.player.move.y(-4)
        self.assertEqual(self.player.y, 2)

    def test_assignment_is_absolute_too(self):
        self.player.set.x = 100
        self.player.set.x = 100
        self.player.set.y = 50
        self.assertEqual(self.player.position, (100, 50))

    def test_both_forms_do_the_same_thing(self):
        self.player.set.x(321)
        by_call = self.player.x
        self.player.set.x(0)
        self.player.set.x = 321
        self.assertEqual(self.player.x, by_call)

    def test_assignment_is_checked_the_same_way(self):
        for bad in ("100", True, None):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    self.player.set.x = bad
                with self.assertRaises(TypeError):
                    self.player.set.x(bad)
        self.assertEqual(self.player.x, 10)

    def test_assignment_takes_a_fraction_too(self):
        self.player.set.x = 100.5
        self.assertEqual(self.player.x, 100.5)

    def test_there_is_no_relative_position_outside_move(self):
        for namespace in (self.player.add, self.player.remove):
            for attribute in ("x", "y", "position"):
                with self.subTest(attribute=attribute):
                    self.assertFalse(hasattr(namespace, attribute))

    def test_set_offers_exactly_what_it_should(self):
        offered = {name for name in dir(self.player.set)
                   if not name.startswith("_")}
        self.assertEqual(offered, {"x", "y", "scale"})

    def test_an_unknown_name_cannot_be_assigned(self):
        with self.assertRaises(AttributeError):
            self.player.set.width = 10


class TestObjectScale(ObjectTestCase):
    def setUp(self):
        super().setUp()
        self.player = GameObject("player")

    def test_it_starts_at_normal_size(self):
        self.assertEqual(self.player.scale, 1.0)

    def test_set_scale_is_absolute(self):
        self.player.set.scale(1.25)
        self.player.set.scale(1.25)
        self.assertEqual(self.player.scale, 1.25)

    def test_add_scale_is_relative(self):
        self.player.add.scale(0.25)
        self.player.add.scale(0.25)
        self.assertEqual(self.player.scale, 1.5)

    def test_remove_scale_is_relative(self):
        self.player.set.scale(2)
        self.player.remove.scale(0.5)
        self.assertEqual(self.player.scale, 1.5)

    def test_scale_by_assignment(self):
        self.player.set.scale = 3
        self.assertEqual(self.player.scale, 3.0)

    def test_scale_is_checked(self):
        for bad in (0, -1):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.player.set.scale(bad)
        for bad in ("big", None, True):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    self.player.set.scale(bad)
        self.assertEqual(self.player.scale, 1.0)

    def test_shrinking_past_nothing_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self.player.remove.scale(1)
        self.assertIn("greater than zero", str(caught.exception))
        self.assertEqual(self.player.scale, 1.0)

    def test_size_reports_the_drawn_size(self):
        self.assertEqual(self.player.size, (4, 4))
        self.player.set.scale(3)
        self.assertEqual(self.player.size, (12, 12))

    def test_scale_is_shared_between_handles(self):
        GameObject("player").set.scale(2)
        self.assertEqual(self.player.scale, 2.0)
        self.assertEqual(self.record().scale, 2.0)

    def test_scaling_does_not_move_it(self):
        self.player.set.x(30)
        self.player.set.scale(4)
        self.assertEqual(self.player.position, (30, 10))


class TestScaledRendering(ObjectTestCase):
    """Scale has to change the pixels, not just the number."""

    def paint(self, width=40, height=40):
        buffer = Framebuffer(width, height)
        buffer.clear()
        for obj in current_scene().objects():
            if obj.visible:
                buffer.draw_image(obj.image, obj.x, obj.y, obj.scale)
        return buffer

    def pixel(self, buffer, x, y):
        index = (y * buffer.width + x) * 4
        blue, green, red, _ = buffer.pixels[index:index + 4]
        return (red, green, blue)

    def lit(self, buffer):
        return sum(
            1
            for y in range(buffer.height)
            for x in range(buffer.width)
            if self.pixel(buffer, x, y) != DEFAULT_CLEAR_COLOUR
        )

    def test_an_unscaled_object_covers_its_own_size(self):
        GameObject("player").set.x(0)
        GameObject("player").set.y(0)
        self.assertEqual(self.lit(self.paint()), 16)

    def test_doubling_the_scale_quadruples_the_pixels(self):
        GameObject("player").set.x(0)
        GameObject("player").set.y(0)
        GameObject("player").set.scale(2)
        self.assertEqual(self.lit(self.paint()), 64)

    def test_halving_the_scale_quarters_the_pixels(self):
        GameObject("player").set.x(0)
        GameObject("player").set.y(0)
        GameObject("player").set.scale(0.5)
        self.assertEqual(self.lit(self.paint()), 4)

    def test_it_grows_from_the_top_left_corner(self):
        player = GameObject("player")
        player.set.x(10)
        player.set.y(10)
        player.set.scale(3)
        buffer = self.paint()
        self.assertEqual(self.pixel(buffer, 10, 10), RED)
        self.assertEqual(self.pixel(buffer, 21, 21), RED)
        self.assertEqual(self.pixel(buffer, 22, 22), DEFAULT_CLEAR_COLOUR)
        self.assertEqual(self.pixel(buffer, 9, 9), DEFAULT_CLEAR_COLOUR)

    def test_scaling_back_to_one_restores_the_pixels(self):
        player = GameObject("player")
        player.set.x(4)
        player.set.y(4)
        before = bytes(self.paint().pixels)
        player.set.scale(2.5)
        player.set.scale(1)
        self.assertEqual(bytes(self.paint().pixels), before)

    def test_a_scaled_object_clips_at_the_edges(self):
        player = GameObject("player")
        player.set.x(-4)
        player.set.y(-4)
        player.set.scale(2)      # 8x8 at (-4, -4): a quarter is on screen
        self.assertEqual(self.lit(self.paint()), 16)

    def test_a_scaled_object_entirely_offscreen_draws_nothing(self):
        player = GameObject("player")
        player.set.x(100)
        player.set.y(100)
        player.set.scale(2)
        self.assertEqual(self.lit(self.paint()), 0)

    def test_a_scale_that_rounds_to_nothing_draws_nothing(self):
        player = GameObject("player")
        player.set.x(0)
        player.set.y(0)
        player.set.scale(0.05)   # 4 * 0.05 rounds to 0
        self.assertEqual(self.lit(self.paint()), 0)

    def test_transparency_survives_scaling(self):
        pixels = bytearray()
        for index in range(4):
            # Two opaque pixels, two fully transparent ones.
            opaque = index < 2
            pixels += bytes([0, 0, 250, 255 if opaque else 0])
        current_scene().clear()
        current_scene().add(SceneObject("half", Image(2, 2, bytes(pixels)),
                                        0, 0))
        buffer = self.paint()
        self.assertEqual(self.lit(buffer), 2)

        current_scene().require("half").scale = 2.0
        self.assertEqual(self.lit(self.paint()), 8)

    def test_the_scaled_frame_reaches_the_backend(self):
        """End to end: a real run, with a scaled object in the scene."""
        frames = []
        backend = NullBackend()

        class G(Game):
            def on_start(self):
                GameObject("player").set.x(0)
                GameObject("player").set.y(0)
                GameObject("player").set.scale(2)

            def on_update(self, dt):
                frames.append(bytes(backend.windows[0].last_frame))
                self.quit()

        Application(G(), size=(40, 40), max_fps=None, backend=backend).run()
        lit = sum(
            1
            for index in range(0, len(frames[0]), 4)
            if (frames[0][index + 2], frames[0][index + 1],
                frames[0][index]) != DEFAULT_CLEAR_COLOUR
        )
        self.assertEqual(lit, 64)


class TestStaleHandles(ObjectTestCase):
    def test_destroying_through_one_handle_invalidates_the_others(self):
        held = GameObject("player")
        GameObject("player").destroy()
        with self.assertRaises(SceneError):
            held.move.x(1)

    def test_every_way_of_using_a_stale_handle_raises(self):
        held = GameObject("player")
        held.destroy()
        with self.assertRaises(SceneError):
            held.x
        with self.assertRaises(SceneError):
            held.set.x(1)
        with self.assertRaises(SceneError):
            held.set.y(1)
        with self.assertRaises(SceneError):
            held.set.scale(2)
        with self.assertRaises(SceneError):
            held.add.scale(1)
        with self.assertRaises(SceneError):
            held.remove.scale(0.5)
        with self.assertRaises(SceneError):
            held.move.x(1)
        with self.assertRaises(SceneError):
            held.destroy()
        with self.assertRaises(SceneError):
            held.size
        with self.assertRaises(SceneError):
            held.scale

    def test_assignment_on_a_stale_handle_raises_too(self):
        held = GameObject("player")
        held.destroy()
        with self.assertRaises(SceneError):
            held.set.x = 1
        with self.assertRaises(SceneError):
            held.set.scale = 2

    def test_a_stale_handle_says_what_happened(self):
        held = GameObject("player")
        held.destroy()
        with self.assertRaises(SceneError) as caught:
            held.set.x(1)
        message = str(caught.exception)
        self.assertIn("player", message)
        self.assertIn("destroyed", message)

    def test_the_name_is_free_afterwards(self):
        GameObject("player").destroy()
        with self.assertRaises(SceneError):
            GameObject("player")
        current_scene().add(SceneObject("player", self.image, 0, 0))
        self.assertEqual(GameObject("player").position, (0, 0))

    def test_a_new_object_with_the_same_name_is_a_different_record(self):
        held = GameObject("player")
        held.destroy()
        current_scene().add(SceneObject("player", self.image, 0, 0))
        self.assertEqual(GameObject("player").x, 0)
        with self.assertRaises(SceneError):
            held.x        # the old handle stays stale, as it should


if __name__ == "__main__":
    unittest.main()
