"""Tests for named game objects and the scene that holds them.

All of this runs headlessly: creating, naming, finding and moving an object
needs no display, which is the point of keeping the scene independent of the
platform layer.
"""

import unittest

import trjoludus
from trjoludus import create
from trjoludus.image import Image
from trjoludus.scene import (
    GameObject,
    Scene,
    SceneError,
    SceneObject,
    current_scene,
)


def make_image(width=4, height=4):
    return Image(width, height, bytes([0, 0, 255, 255]) * (width * height))


class SceneTestCase(unittest.TestCase):
    """Leaves the shared scene empty, so tests cannot affect each other."""

    def setUp(self):
        current_scene().clear()
        self.addCleanup(current_scene().clear)


class TestScene(SceneTestCase):
    def test_starts_empty(self):
        self.assertEqual(len(Scene()), 0)

    def test_add_and_require(self):
        scene = Scene()
        obj = scene.add(SceneObject("player", make_image(), 1, 2))
        self.assertIs(scene.require("player"), obj)

    def test_contains(self):
        scene = Scene()
        scene.add(SceneObject("player", make_image(), 0, 0))
        self.assertIn("player", scene)
        self.assertNotIn("zombie", scene)

    def test_names_are_in_insertion_order(self):
        scene = Scene()
        for name in ("a", "b", "c"):
            scene.add(SceneObject(name, make_image(), 0, 0))
        self.assertEqual(scene.names, ("a", "b", "c"))

    def test_objects_are_in_draw_order(self):
        """Draw order is insertion order: later objects cover earlier ones."""
        scene = Scene()
        first = scene.add(SceneObject("back", make_image(), 0, 0))
        second = scene.add(SceneObject("front", make_image(), 0, 0))
        self.assertEqual(scene.objects(), (first, second))

    def test_duplicate_names_are_rejected(self):
        """Replacing silently would make one of the two quietly vanish."""
        scene = Scene()
        scene.add(SceneObject("player", make_image(), 0, 0))
        with self.assertRaises(SceneError) as caught:
            scene.add(SceneObject("player", make_image(), 9, 9))
        self.assertIn("player", str(caught.exception))

    def test_a_rejected_duplicate_leaves_the_original_alone(self):
        scene = Scene()
        scene.add(SceneObject("player", make_image(), 1, 2))
        with self.assertRaises(SceneError):
            scene.add(SceneObject("player", make_image(), 9, 9))
        self.assertEqual((scene.require("player").x, scene.require("player").y),
                         (1, 2))

    def test_missing_object_names_what_exists(self):
        scene = Scene()
        scene.add(SceneObject("player", make_image(), 0, 0))
        with self.assertRaises(SceneError) as caught:
            scene.require("zombie")
        message = str(caught.exception)
        self.assertIn("zombie", message)
        self.assertIn("player", message)

    def test_missing_object_in_an_empty_scene_says_so(self):
        with self.assertRaises(SceneError) as caught:
            Scene().require("player")
        self.assertIn("nothing has been created yet", str(caught.exception))

    def test_remove(self):
        scene = Scene()
        scene.add(SceneObject("player", make_image(), 0, 0))
        scene.remove("player")
        self.assertNotIn("player", scene)

    def test_removing_a_missing_object_raises(self):
        with self.assertRaises(SceneError):
            Scene().remove("nobody")

    def test_clear(self):
        scene = Scene()
        scene.add(SceneObject("a", make_image(), 0, 0))
        scene.add(SceneObject("b", make_image(), 0, 0))
        scene.clear()
        self.assertEqual(len(scene), 0)


class TestGameObject(SceneTestCase):
    def create(self, name="player", x=10, y=20):
        current_scene().add(SceneObject(name, make_image(8, 6), x, y))
        return GameObject(name)

    def test_finds_an_existing_object(self):
        self.assertEqual(self.create().name, "player")

    def test_reports_position(self):
        player = self.create(x=30, y=40)
        self.assertEqual(player.position, (30, 40))
        self.assertEqual((player.x, player.y), (30, 40))

    def test_reports_size_from_the_image(self):
        self.assertEqual(self.create().size, (8, 6))

    def test_is_visible_by_default(self):
        self.assertTrue(self.create().visible)

    def test_position_is_writable(self):
        player = self.create()
        player.x = 100
        player.y = 200
        self.assertEqual(player.position, (100, 200))

    def test_writing_through_a_handle_changes_what_is_drawn(self):
        """A handle holds no state of its own; it acts on the scene."""
        player = self.create()
        player.x = 77
        self.assertEqual(current_scene().require("player").x, 77)

    def test_visibility_is_writable(self):
        player = self.create()
        player.visible = False
        self.assertFalse(current_scene().require("player").visible)

    def test_two_handles_refer_to_the_same_object(self):
        self.create()
        self.assertEqual(GameObject("player"), GameObject("player"))

    def test_handles_to_different_objects_differ(self):
        self.create("player")
        self.create("zombie")
        self.assertNotEqual(GameObject("player"), GameObject("zombie"))

    def test_missing_object_raises_with_a_helpful_message(self):
        with self.assertRaises(SceneError) as caught:
            GameObject("nobody")
        self.assertIn("nobody", str(caught.exception))

    def test_a_non_string_name_is_rejected(self):
        with self.assertRaises(TypeError):
            GameObject(42)

    def test_lookup_does_not_create(self):
        """GameObject finds objects; it never makes them."""
        with self.assertRaises(SceneError):
            GameObject("player")
        self.assertEqual(len(current_scene()), 0)

    def test_is_exposed_publicly(self):
        self.assertIs(trjoludus.GameObject, GameObject)


class TestMovement(SceneTestCase):
    """player.move.x(50) -- relative movement, in pixels."""

    def player(self, x=100, y=100):
        current_scene().add(SceneObject("player", make_image(), x, y))
        return GameObject("player")

    def test_positive_x_moves_right(self):
        player = self.player()
        player.move.x(50)
        self.assertEqual(player.x, 150)

    def test_negative_x_moves_left(self):
        player = self.player()
        player.move.x(-50)
        self.assertEqual(player.x, 50)

    def test_positive_y_moves_down(self):
        """+y is downward, matching the coordinate convention."""
        player = self.player()
        player.move.y(50)
        self.assertEqual(player.y, 150)

    def test_negative_y_moves_up(self):
        player = self.player()
        player.move.y(-50)
        self.assertEqual(player.y, 50)

    def test_moving_x_leaves_y_alone(self):
        player = self.player()
        player.move.x(50)
        self.assertEqual(player.position, (150, 100))

    def test_moving_y_leaves_x_alone(self):
        player = self.player()
        player.move.y(50)
        self.assertEqual(player.position, (100, 150))

    def test_repeated_movement_accumulates(self):
        """Movement is an offset, not an assignment."""
        player = self.player()
        player.move.x(50)
        player.move.x(50)
        self.assertEqual(player.x, 200)

    def test_opposite_movements_cancel_out(self):
        player = self.player(y=0)
        player.move.y(25)
        player.move.y(-10)
        self.assertEqual(player.y, 15)

    def test_combined_x_and_y_movement(self):
        player = self.player(0, 0)
        player.move.x(30)
        player.move.y(-40)
        self.assertEqual(player.position, (30, -40))

    def test_movement_after_setting_x_directly(self):
        """The documented distinction: assign absolute, move relative."""
        player = self.player()
        player.x = 250
        player.move.x(50)
        self.assertEqual(player.x, 300)

    def test_movement_after_setting_y_directly(self):
        player = self.player()
        player.y = 100
        player.move.y(-25)
        self.assertEqual(player.y, 75)

    def test_movement_is_reflected_by_position(self):
        player = self.player(10, 20)
        player.move.x(5)
        player.move.y(6)
        self.assertEqual(player.position, (15, 26))

    def test_movement_changes_the_underlying_scene_object(self):
        """What moves must be what the engine draws."""
        player = self.player()
        player.move.x(42)
        self.assertEqual(current_scene().require("player").x, 142)

    def test_movement_through_a_second_handle_is_visible_to_the_first(self):
        first = self.player()
        second = GameObject("player")
        second.move.x(10)
        self.assertEqual(first.x, 110)

    def test_zero_movement_changes_nothing(self):
        player = self.player()
        player.move.x(0)
        player.move.y(0)
        self.assertEqual(player.position, (100, 100))

    def test_movement_off_screen_is_allowed(self):
        """There is no world boundary, so nothing is clamped."""
        player = self.player(10, 10)
        player.move.x(-500)
        player.move.y(-500)
        self.assertEqual(player.position, (-490, -490))

    def test_movement_does_not_change_the_image(self):
        player = self.player()
        before = current_scene().require("player").image
        player.move.x(70)
        self.assertIs(current_scene().require("player").image, before)
        self.assertEqual(player.size, before.size)

    def test_move_is_the_same_object_each_time(self):
        player = self.player()
        self.assertIs(player.move, player.move)

    def test_non_integer_distances_are_rejected(self):
        """A float position would fail much later, inside the renderer."""
        player = self.player()
        for bad in (1.5, "10", None, True):
            with self.subTest(distance=bad):
                with self.assertRaises(TypeError):
                    player.move.x(bad)
        self.assertEqual(player.x, 100)

    def test_setting_a_non_integer_position_is_rejected(self):
        player = self.player()
        with self.assertRaises(TypeError):
            player.x = 1.5
        self.assertEqual(player.x, 100)

    def test_moving_a_removed_object_raises(self):
        """Silently moving something nobody draws looks like a bug in TrjoLudus."""
        player = self.player()
        current_scene().remove("player")
        with self.assertRaises(SceneError) as caught:
            player.move.x(10)
        message = str(caught.exception)
        self.assertIn("player", message)
        self.assertIn("destroyed", message)

    def test_reading_a_removed_object_raises(self):
        player = self.player()
        current_scene().remove("player")
        for read in (lambda: player.x, lambda: player.position,
                     lambda: player.size, lambda: player.visible):
            with self.subTest(), self.assertRaises(SceneError):
                read()

    def test_a_removed_object_is_not_silently_recreated(self):
        player = self.player()
        current_scene().remove("player")
        with self.assertRaises(SceneError):
            player.move.x(10)
        self.assertNotIn("player", current_scene())

    def test_a_new_object_with_the_same_name_is_a_different_object(self):
        old = self.player()
        current_scene().remove("player")
        new = self.player(0, 0)
        new.move.x(5)
        self.assertEqual(new.x, 5)
        with self.assertRaises(SceneError):
            old.move.x(5)


class TestDestroy(SceneTestCase):
    """player.destroy() -- permanent removal from the game."""

    def player(self, name="player", x=10, y=20):
        current_scene().add(SceneObject(name, make_image(), x, y))
        return GameObject(name)

    def test_removes_the_object_from_the_scene(self):
        self.player().destroy()
        self.assertNotIn("player", current_scene())

    def test_the_object_can_no_longer_be_found(self):
        self.player().destroy()
        with self.assertRaises(SceneError):
            GameObject("player")

    def test_the_name_becomes_available_again(self):
        self.player().destroy()
        current_scene().add(SceneObject("player", make_image(), 0, 0))
        self.assertIn("player", current_scene())

    def test_every_handle_becomes_invalid_not_just_the_one_used(self):
        first = self.player()
        second = GameObject("player")
        first.destroy()
        with self.assertRaises(SceneError):
            second.x

    def test_reading_position_after_destruction_raises(self):
        player = self.player()
        player.destroy()
        for read in (lambda: player.x, lambda: player.y,
                     lambda: player.position, lambda: player.size,
                     lambda: player.visible):
            with self.subTest(), self.assertRaises(SceneError):
                read()

    def test_moving_after_destruction_raises(self):
        player = self.player()
        player.destroy()
        with self.assertRaises(SceneError):
            player.move.x(50)
        with self.assertRaises(SceneError):
            player.move.y(50)

    def test_the_error_explains_what_happened_and_what_to_do(self):
        player = self.player()
        player.destroy()
        with self.assertRaises(SceneError) as caught:
            player.move.x(1)
        message = str(caught.exception)
        self.assertIn("player", message)
        self.assertIn("destroyed", message)
        self.assertIn("create.image", message)

    def test_destroying_twice_raises(self):
        """The second call cannot mean anything, so it says so."""
        player = self.player()
        player.destroy()
        with self.assertRaises(SceneError) as caught:
            player.destroy()
        self.assertIn("destroyed", str(caught.exception))

    def test_destroying_twice_does_not_corrupt_the_scene(self):
        other = self.player("zombie")
        player = self.player()
        player.destroy()
        with self.assertRaises(SceneError):
            player.destroy()
        self.assertEqual(current_scene().names, ("zombie",))
        self.assertEqual(other.name, "zombie")

    def test_destroying_one_object_leaves_the_others_alone(self):
        player = self.player("player")
        zombie = self.player("zombie", 5, 5)
        player.destroy()
        self.assertEqual(zombie.position, (5, 5))
        zombie.move.x(1)
        self.assertEqual(zombie.x, 6)

    def test_a_destroyed_object_is_not_silently_recreated(self):
        player = self.player()
        player.destroy()
        with self.assertRaises(SceneError):
            player.move.x(1)
        self.assertEqual(len(current_scene()), 0)

    def test_destroy_is_the_only_way_to_remove_an_object(self):
        self.assertTrue(hasattr(GameObject, "destroy"))


class TestCreateImage(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.sprite = _write_test_png(self, 6, 4)

    def test_creates_and_registers_an_object(self):
        create.image(10, 20, self.sprite, "player")
        self.assertIn("player", current_scene())

    def test_returns_a_usable_handle(self):
        player = create.image(10, 20, self.sprite, "player")
        self.assertIsInstance(player, GameObject)
        self.assertEqual(player.name, "player")
        self.assertEqual(player.position, (10, 20))

    def test_the_handle_matches_a_later_lookup(self):
        created = create.image(1, 2, self.sprite, "player")
        self.assertEqual(created, GameObject("player"))

    def test_size_comes_from_the_image(self):
        self.assertEqual(create.image(0, 0, self.sprite, "p").size, (6, 4))

    def test_duplicate_names_are_rejected(self):
        create.image(0, 0, self.sprite, "player")
        with self.assertRaises(SceneError):
            create.image(50, 50, self.sprite, "player")

    def test_objects_keep_their_own_positions(self):
        a = create.image(1, 2, self.sprite, "a")
        b = create.image(30, 40, self.sprite, "b")
        self.assertEqual(a.position, (1, 2))
        self.assertEqual(b.position, (30, 40))

    def test_negative_positions_are_allowed(self):
        """Partly off-screen is a normal thing for a game object to be."""
        self.assertEqual(create.image(-10, -20, self.sprite, "p").position,
                         (-10, -20))

    def test_a_missing_file_is_reported_clearly(self):
        with self.assertRaises(trjoludus.ImageError) as caught:
            create.image(0, 0, "no-such-file.png", "player")
        self.assertIn("no-such-file.png", str(caught.exception))

    def test_a_failed_load_registers_nothing(self):
        with self.assertRaises(trjoludus.ImageError):
            create.image(0, 0, "no-such-file.png", "player")
        self.assertEqual(len(current_scene()), 0)

    def test_a_non_string_name_is_rejected(self):
        with self.assertRaises(TypeError):
            create.image(0, 0, self.sprite, 42)

    def test_an_empty_name_is_rejected(self):
        with self.assertRaises(ValueError):
            create.image(0, 0, self.sprite, "")

    def test_non_integer_coordinates_are_rejected(self):
        with self.assertRaises(TypeError):
            create.image(1.5, 0, self.sprite, "player")

    def test_destroy(self):
        create.image(0, 0, self.sprite, "player").destroy()
        self.assertNotIn("player", current_scene())

    def test_destroying_frees_the_name(self):
        create.image(0, 0, self.sprite, "player").destroy()
        create.image(5, 5, self.sprite, "player")  # must not raise
        self.assertEqual(GameObject("player").position, (5, 5))

    def test_create_offers_no_competing_removal(self):
        """destroy() is the one way to remove an object."""
        self.assertFalse(hasattr(create, "remove"))

    def test_create_is_exposed_publicly(self):
        self.assertIs(trjoludus.create, create)


def _write_test_png(test, width, height):
    """Write a small opaque PNG to a temporary file and return its path."""
    import struct
    import tempfile
    import zlib
    from pathlib import Path

    rows = b"".join(
        b"\x00" + bytes([200, 100, 50, 255]) * width for _ in range(height)
    )

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
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
