"""The API rules this library holds itself to, checked rather than intended.

Four rules came out of the pre-1.0 consistency pass:

1. Values are properties; actions are methods.
2. Anything that names an object takes a name *or* a handle.
3. Anything that produces a value returns it.
4. A game object and a drawing behave the same where they mean the same.

These test the rules directly, across the classes they apply to, so a new API
that breaks one of them fails here rather than being noticed by somebody
writing a game.
"""

import unittest
import warnings

import trjoludus
from trjoludus import (GameObject, color, draw, engine, keyboard, mouse,
                       objects)
from trjoludus.errors import TrjoLudusWarning
from trjoludus.image import Image
from trjoludus.scene import SceneError, SceneObject, current_scene
from trjoludus.ui import Drawable, UiError


def picture(width=10, height=10):
    return Image(width, height, bytes([0, 0, 250, 255]) * (width * height))


class PolishTestCase(unittest.TestCase):
    def setUp(self):
        engine.end_run()
        self.addCleanup(engine.end_run)

    def place(self, name, x=0, y=0, width=10, height=10):
        current_scene().add(SceneObject(name, picture(width, height), x, y))
        return GameObject(name)

    def drawing(self):
        return draw.rect(0, 0, 10, 10, color.white)


# --- rule 1: values are properties -------------------------------------


class TestValuesAreProperties(PolishTestCase):
    SETTABLE = ("x", "y", "scale", "visible")

    def test_a_game_object_takes_all_of_them(self):
        thing = self.place("thing")
        for name in self.SETTABLE:
            with self.subTest(value=name):
                self.assertIsNotNone(
                    getattr(GameObject, name).fset,
                    f"GameObject.{name} should be assignable")

    def test_a_drawing_takes_all_of_them(self):
        for name in self.SETTABLE:
            with self.subTest(value=name):
                self.assertIsNotNone(
                    getattr(Drawable, name).fset,
                    f"Drawable.{name} should be assignable")

    def test_scale_can_be_assigned(self):
        thing = self.place("thing")
        thing.scale = 2.0
        self.assertEqual(thing.scale, 2.0)
        self.assertEqual(thing.size, (20, 20))

    def test_assigning_scale_and_calling_set_scale_agree(self):
        one, two = self.place("one"), self.place("two")
        one.scale = 3.0
        two.set.scale(3.0)
        self.assertEqual(one.scale, two.scale)
        self.assertEqual(one.size, two.size)

    def test_scale_is_still_validated(self):
        thing = self.place("thing")
        for bad in (0, -1, -0.5):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    thing.scale = bad
        for bad in ("2", None, True):
            with self.subTest(value=bad):
                with self.assertRaises(TypeError):
                    thing.scale = bad

    def test_a_refused_scale_changes_nothing(self):
        thing = self.place("thing")
        thing.scale = 2.0
        with self.assertRaises(ValueError):
            thing.scale = 0
        self.assertEqual(thing.scale, 2.0)

    def test_the_relative_forms_still_work(self):
        """Absolute and relative are different intents; both stay."""
        thing = self.place("thing")
        thing.scale = 2.0
        thing.add.scale(1.0)
        self.assertEqual(thing.scale, 3.0)
        thing.remove.scale(1.0)
        self.assertEqual(thing.scale, 2.0)

    def test_move_still_works_beside_assignment(self):
        thing = self.place("thing")
        thing.x = 250
        thing.move.x(50)
        self.assertEqual(thing.x, 300)

    def test_actions_are_still_methods(self):
        for name in ("destroy", "group", "ungroup"):
            with self.subTest(action=name):
                self.assertFalse(isinstance(getattr(GameObject, name),
                                            property))


# --- rule 4: a game object and a drawing agree -------------------------


class TestObjectsAndDrawingsAgree(PolishTestCase):
    def both(self):
        return self.place("thing"), self.drawing()

    def test_the_same_four_assignments_work_on_both(self):
        for thing in self.both():
            with self.subTest(kind=type(thing).__name__):
                thing.x = 40
                thing.y = 25
                thing.scale = 2.0
                thing.visible = False
                self.assertEqual((thing.x, thing.y), (40, 25))
                self.assertEqual(thing.scale, 2.0)
                self.assertFalse(thing.visible)

    def test_visible_reads_back_the_same_way(self):
        for thing in self.both():
            with self.subTest(kind=type(thing).__name__):
                thing.visible = False
                self.assertIs(thing.visible, False)
                thing.visible = True
                self.assertIs(thing.visible, True)

    def test_position_reads_the_same_way(self):
        for thing in self.both():
            with self.subTest(kind=type(thing).__name__):
                thing.x = 7
                thing.y = 9
                self.assertEqual(thing.position, (7, 9))

    def test_both_offer_set_and_move(self):
        for thing in self.both():
            with self.subTest(kind=type(thing).__name__):
                thing.set.x(10)
                thing.move.x(5)
                self.assertEqual(thing.x, 15)

    def test_a_drawing_keeps_hide_and_show(self):
        """An action spelling of the same thing, and worth keeping."""
        label = self.drawing()
        label.hide()
        self.assertFalse(label.visible)
        label.show()
        self.assertTrue(label.visible)

    def test_hide_and_assignment_are_the_same_operation(self):
        one, two = self.drawing(), self.drawing()
        one.hide()
        two.visible = False
        self.assertEqual(one.visible, two.visible)
        self.assertEqual(one.showing, two.showing)

    def test_showing_still_means_something_different(self):
        """It accounts for the list; `visible` does not."""
        label = self.drawing()
        label.visible = True
        label.list.hide()
        self.assertTrue(label.visible)
        self.assertFalse(label.showing)

    def test_a_drawing_does_not_grow_object_only_ideas(self):
        for absent in ("group", "ungroup", "groups", "layer", "mask",
                       "animation", "image", "destroy_object"):
            with self.subTest(name=absent):
                self.assertFalse(hasattr(Drawable, absent),
                                 f"a drawing should not have {absent}")

    def test_assignment_on_a_drawing_is_checked(self):
        label = self.drawing()
        for bad in ("five", None, True):
            with self.subTest(value=bad):
                with self.assertRaises(TypeError):
                    label.x = bad

    def test_a_gone_drawing_refuses_assignment(self):
        label = self.drawing()
        current_scene()  # keep the run alive
        engine.current().drawings.clear()
        with self.assertRaises(UiError):
            label.x = 5


# --- object lifetime ----------------------------------------------------


class TestObjectLifetime(PolishTestCase):
    def test_a_live_object_is_alive(self):
        thing = self.place("thing")
        self.assertTrue(thing.alive)
        self.assertTrue(thing)

    def test_a_destroyed_object_is_not(self):
        thing = self.place("thing")
        thing.destroy()
        self.assertFalse(thing.alive)
        self.assertFalse(thing)

    def test_every_handle_agrees(self):
        self.place("thing")
        one, two = GameObject("thing"), GameObject("thing")
        one.destroy()
        self.assertFalse(two.alive)
        self.assertFalse(two)

    def test_asking_is_safe_after_destruction(self):
        """The one thing a handle still answers, which is why it is worth
        asking."""
        thing = self.place("thing")
        thing.destroy()
        self.assertFalse(thing.alive)      # must not raise
        self.assertFalse(bool(thing))
        with self.assertRaises(SceneError):
            thing.x

    def test_a_recreated_name_does_not_revive_the_old_handle(self):
        thing = self.place("thing")
        thing.destroy()
        fresh = self.place("thing")
        self.assertFalse(thing.alive, "the old handle came back to life")
        self.assertTrue(fresh.alive)

    def test_a_reused_slot_does_not_revive_the_old_handle(self):
        thing = self.place("thing")
        slot = current_scene().require("thing")._slot
        thing.destroy()
        other = self.place("other")
        self.assertEqual(current_scene().require("other")._slot, slot,
                         "the test needs the slot to be reused")
        self.assertFalse(thing.alive)
        self.assertTrue(other.alive)

    def test_destroying_twice_still_raises(self):
        thing = self.place("thing")
        thing.destroy()
        with self.assertRaises(SceneError):
            thing.destroy()

    def test_equality_and_hashing_are_unchanged(self):
        self.place("thing")
        one, two = GameObject("thing"), GameObject("thing")
        self.assertEqual(one, two)
        self.assertEqual(hash(one), hash(two))
        one.destroy()
        self.assertEqual(one, two, "destruction is not an identity change")
        self.assertEqual(hash(one), hash(two))

    def test_repr_still_names_it_after_destruction(self):
        thing = self.place("thing")
        thing.destroy()
        self.assertEqual(repr(thing), "GameObject('thing')")

    def test_the_guard_a_game_would_actually_write(self):
        thing = self.place("thing")
        thing.destroy()
        moved = False
        if thing:
            thing.move.x(5)
            moved = True
        self.assertFalse(moved, "`if thing:` promised something false")


# --- rule 2: names or handles, everywhere ------------------------------


class TestNamesOrHandles(PolishTestCase):
    def setUp(self):
        super().setUp()
        self.player = self.place("player", 0, 0)
        self.zombie = self.place("zombie", 5, 5)

    def test_collide_takes_two_names(self):
        self.assertTrue(objects.collide("player", "zombie"))

    def test_collide_takes_two_handles(self):
        self.assertTrue(objects.collide(self.player, self.zombie))

    def test_collide_takes_one_of_each(self):
        self.assertTrue(objects.collide(self.player, "zombie"))
        self.assertTrue(objects.collide("player", self.zombie))

    def test_colliding_takes_a_handle(self):
        found = objects.colliding(self.player)
        self.assertEqual([f.name for f in found], ["zombie"])

    def test_a_result_goes_straight_back_in(self):
        """The round trip that used to need `.name`."""
        found = objects.colliding(self.player)[0]
        back = objects.colliding(found)
        self.assertEqual([f.name for f in back], ["player"])

    def test_a_result_goes_back_into_collide(self):
        found = objects.colliding(self.player)[0]
        self.assertTrue(objects.collide(self.player, found))

    def test_a_group_query_takes_a_handle(self):
        self.zombie.group("enemy")
        self.assertEqual(
            [f.name for f in objects.colliding(self.player, group="enemy")],
            ["zombie"])
        self.assertTrue(objects.collide(self.player, group="enemy"))

    def test_find_and_exists_take_a_handle(self):
        self.assertEqual(objects.find(self.player), self.player)
        self.assertTrue(objects.exists(self.player))

    def test_self_collision_still_raises_with_handles(self):
        from trjoludus import CollisionError

        with self.assertRaises(CollisionError):
            objects.collide(self.player, self.player)

    def test_a_missing_name_still_warns_with_a_handle_beside_it(self):
        with self.assertWarns(TrjoLudusWarning):
            self.assertFalse(objects.collide(self.player, "ghost"))

    def test_a_destroyed_handle_reads_as_a_missing_name(self):
        self.zombie.destroy()
        with self.assertWarns(TrjoLudusWarning):
            self.assertFalse(objects.collide(self.player, self.zombie))

    def test_something_that_is_neither_is_refused(self):
        for wrong in (7, None, 2.5, [self.player]):
            with self.subTest(value=wrong):
                with self.assertRaises(TypeError):
                    objects.colliding(wrong)
                with self.assertRaises(TypeError):
                    objects.collide(self.player, wrong)

    def test_the_type_error_names_both_forms(self):
        with self.assertRaises(TypeError) as caught:
            objects.colliding(7)
        message = str(caught.exception)
        self.assertIn("name", message)
        self.assertIn("game object", message)

    def test_layers_and_groups_still_filter_with_handles(self):
        self.zombie.group("enemy")
        self.player.mask = 5
        self.assertEqual(objects.colliding(self.player, group="enemy"), ())


# --- the objects namespace ---------------------------------------------


class TestTheObjectsNamespace(PolishTestCase):
    def test_all_returns_handles_in_creation_order(self):
        for name in ("first", "second", "third"):
            self.place(name)
        self.assertEqual([o.name for o in objects.all()],
                         ["first", "second", "third"])
        for found in objects.all():
            self.assertIsInstance(found, GameObject)

    def test_all_is_empty_when_nothing_exists(self):
        self.assertEqual(objects.all(), ())

    def test_all_leaves_out_the_destroyed(self):
        self.place("a")
        self.place("b")
        GameObject("a").destroy()
        self.assertEqual([o.name for o in objects.all()], ["b"])

    def test_all_is_a_snapshot(self):
        self.place("a")
        held = objects.all()
        GameObject("a").destroy()
        self.assertEqual(len(held), 1, "the tuple changed underneath")
        self.assertFalse(held[0].alive)

    def test_find_returns_a_usable_handle(self):
        self.place("player", 3, 4)
        found = objects.find("player")
        self.assertEqual(found.position, (3, 4))
        found.x = 40
        self.assertEqual(GameObject("player").x, 40)

    def test_find_answers_none_rather_than_raising(self):
        self.assertIsNone(objects.find("nobody"))

    def test_find_after_destruction(self):
        self.place("thing").destroy()
        self.assertIsNone(objects.find("thing"))

    def test_find_after_a_name_is_recreated(self):
        self.place("thing").destroy()
        self.place("thing", 9, 9)
        self.assertEqual(objects.find("thing").position, (9, 9))

    def test_exists(self):
        self.place("player")
        self.assertTrue(objects.exists("player"))
        self.assertFalse(objects.exists("ghost"))

    def test_exists_after_destruction(self):
        self.place("thing").destroy()
        self.assertFalse(objects.exists("thing"))

    def test_the_guard_a_game_would_write(self):
        self.place("player")
        player = objects.find("player")
        self.assertTrue(player and player.alive)

    def test_none_of_them_change_anything(self):
        for name in ("a", "b"):
            self.place(name, 1, 2)
        GameObject("a").group("enemy")
        GameObject("a").layer = 3

        def snapshot():
            return [(o.name, o.x, o.y, o.scale, o.visible, tuple(o._groups),
                     o._layer, o._mask)
                    for o in current_scene().objects()]

        before = snapshot()
        slots = len(engine.current().objects)
        objects.all()
        objects.find("a")
        objects.exists("b")
        objects.find("nobody")
        self.assertEqual(snapshot(), before)
        self.assertEqual(len(engine.current().objects), slots)

    def test_they_start_no_animation(self):
        self.place("a")
        objects.all()
        objects.find("a")
        self.assertIsNone(GameObject("a").animation.current)

    def test_the_namespace_offers_what_it_should_and_no_more(self):
        self.assertEqual(objects.__all__,
                         ["all", "collide", "colliding", "exists", "find"])
        for hidden in ("current_scene", "SceneObject", "ObjectTable",
                       "engine", "registry", "name_of"):
            with self.subTest(name=hidden):
                self.assertFalse(hasattr(objects, hidden))


# --- animation ----------------------------------------------------------


class TestAnimationStop(PolishTestCase):
    def frames(self):
        import struct
        import tempfile
        import zlib
        from pathlib import Path

        folder = Path(tempfile.mkdtemp())
        made = []
        for index in range(3):
            path = folder / f"f{index}.png"

            def chunk(tag, body):
                crc = zlib.crc32(tag + body) & 0xFFFFFFFF
                return (struct.pack(">I", len(body)) + tag + body
                        + struct.pack(">I", crc))

            rows = b"".join(b"\x00" + bytes([10, 20, 30, 255]) * 4
                            for _ in range(4))
            path.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
            made.append(str(path))
        return made

    def walker(self):
        thing = self.place("walker")
        thing.animation.add("walk", self.frames())
        return thing

    def test_stop_with_no_name_stops_what_is_playing(self):
        walker = self.walker()
        walker.animation.play("walk")
        walker.animation.stop()
        self.assertFalse(walker.animation.is_playing)

    def test_stop_with_a_name_still_works(self):
        walker = self.walker()
        walker.animation.play("walk")
        walker.animation.stop("walk")
        self.assertFalse(walker.animation.is_playing)

    def test_both_leave_the_same_state(self):
        one, two = self.walker(), self.place("other")
        two.animation.add("walk", self.frames())
        one.animation.play("walk")
        two.animation.play("walk")
        one.animation.stop()
        two.animation.stop("walk")
        self.assertEqual(one.animation.is_playing, two.animation.is_playing)
        self.assertEqual(one.animation.current, two.animation.current)
        self.assertEqual(one.animation.frame, two.animation.frame)

    def test_stopping_when_nothing_plays_is_quiet(self):
        walker = self.walker()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            walker.animation.stop()
        self.assertEqual(caught, [], "asking for the state it is in warned")

    def test_stopping_twice_is_quiet(self):
        walker = self.walker()
        walker.animation.play("walk")
        walker.animation.stop()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            walker.animation.stop()
        self.assertEqual(caught, [])

    def test_naming_the_wrong_one_still_says_so(self):
        """Naming it is how a game asks to be told."""
        walker = self.walker()
        walker.animation.add("jump", self.frames())
        walker.animation.play("walk")
        with self.assertWarns(TrjoLudusWarning):
            walker.animation.stop("jump")
        self.assertTrue(walker.animation.is_playing)

    def test_the_frame_is_kept(self):
        walker = self.walker()
        walker.animation.play("walk")
        frame = walker.animation.frame
        walker.animation.stop()
        self.assertEqual(walker.animation.frame, frame)


# --- the public surface -------------------------------------------------


class TestThePublicSurface(PolishTestCase):
    def test_the_wildcard_still_matches_all(self):
        namespace = {}
        exec("from trjoludus import *", namespace)
        namespace.pop("__builtins__", None)
        self.assertEqual(set(namespace), set(trjoludus.__all__))

    def test_no_internals_leaked_into_the_top_level(self):
        for hidden in ("name_of", "SceneObject", "ObjectTable", "EngineState",
                       "current_scene", "current_ui", "registry", "ctypes"):
            with self.subTest(name=hidden):
                self.assertNotIn(hidden, trjoludus.__all__)

    def test_keyboard_and_mouse_have_the_same_shape(self):
        for name in ("pressed", "wait"):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(keyboard, name)))
                self.assertTrue(callable(getattr(mouse, name)))

    def test_the_things_that_should_not_have_changed_did_not(self):
        for name in ("Game", "run", "Application", "create", "GameObject",
                     "draw", "color", "keyboard", "mouse", "time",
                     "rendering", "objects"):
            with self.subTest(name=name):
                self.assertIn(name, trjoludus.__all__)


if __name__ == "__main__":
    unittest.main()
