"""Tests for `objects.collide`.

The rule these enforce, beyond the arithmetic: **collision answers a question
and changes nothing**. A test that only checked True and False would not
notice an implementation that moved something on the way, so the ones at the
bottom check that nothing moved, nothing was destroyed and no animation
started.

The bounds come from the object table, which is where an object's numbers
already live. That is checked too -- a second copy of a position kept for
collision is the bug this design exists to make impossible.
"""

import unittest
import warnings

from trjoludus import collision, engine, objects
from trjoludus.collision import CollisionError
from trjoludus.errors import TrjoLudusWarning
from trjoludus.image import Image
from trjoludus.scene import GameObject, SceneObject, current_scene


def picture(width=10, height=10):
    return Image(width, height, bytes([0, 0, 250, 255]) * (width * height))


class CollisionTestCase(unittest.TestCase):
    def setUp(self):
        engine.end_run()
        self.addCleanup(engine.end_run)

    def place(self, name, x=0, y=0, width=10, height=10):
        """One object of a known size, at a known place."""
        return current_scene().add(
            SceneObject(name, picture(width, height), x, y))

    def collide(self, a="a", b="b"):
        """Ask, with warnings silenced -- the warning tests check those."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TrjoLudusWarning)
            return objects.collide(a, b)


class TestOverlapping(CollisionTestCase):
    def test_two_objects_on_top_of_each_other(self):
        self.place("a", 0, 0)
        self.place("b", 0, 0)
        self.assertTrue(self.collide())

    def test_two_objects_partly_over_each_other(self):
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        self.assertTrue(self.collide())

    def test_objects_far_apart(self):
        self.place("a", 0, 0)
        self.place("b", 500, 500)
        self.assertFalse(self.collide())

    def test_apart_horizontally_but_level(self):
        self.place("a", 0, 0)
        self.place("b", 50, 0)
        self.assertFalse(self.collide())

    def test_apart_vertically_but_aligned(self):
        self.place("a", 0, 0)
        self.place("b", 0, 50)
        self.assertFalse(self.collide())

    def test_overlapping_across_but_not_down(self):
        """Both axes have to overlap, not just one."""
        self.place("a", 0, 0)
        self.place("b", 5, 100)
        self.assertFalse(self.collide())

    def test_overlapping_down_but_not_across(self):
        self.place("a", 0, 0)
        self.place("b", 100, 5)
        self.assertFalse(self.collide())

    def test_one_completely_inside_another(self):
        self.place("a", 0, 0, 100, 100)
        self.place("b", 40, 40, 5, 5)
        self.assertTrue(self.collide())

    def test_the_small_one_asked_about_first(self):
        """The answer cannot depend on which order they were named."""
        self.place("a", 40, 40, 5, 5)
        self.place("b", 0, 0, 100, 100)
        self.assertTrue(self.collide())

    def test_the_answer_is_the_same_both_ways_round(self):
        for x, y in ((0, 0), (5, 5), (9, 9), (10, 10), (11, 0), (-5, -5)):
            with self.subTest(at=(x, y)):
                engine.end_run()
                self.place("a", 0, 0)
                self.place("b", x, y)
                self.assertEqual(self.collide("a", "b"),
                                 self.collide("b", "a"))

    def test_objects_of_different_sizes(self):
        self.place("a", 0, 0, 4, 4)
        self.place("b", 3, 3, 60, 60)
        self.assertTrue(self.collide())

    def test_a_tall_thin_object_and_a_wide_flat_one_crossing(self):
        self.place("a", 10, 0, 2, 100)
        self.place("b", 0, 10, 100, 2)
        self.assertTrue(self.collide())

    def test_negative_positions(self):
        self.place("a", -20, -20)
        self.place("b", -15, -15)
        self.assertTrue(self.collide())

    def test_across_the_origin(self):
        self.place("a", -5, -5)
        self.place("b", 0, 0)
        self.assertTrue(self.collide())

    def test_a_one_pixel_overlap_counts(self):
        self.place("a", 0, 0)
        self.place("b", 9, 9)
        self.assertTrue(self.collide())

    def test_fractional_positions_are_not_rounded_away(self):
        """Rounding is a rendering concern. Half a pixel of overlap is
        overlap, and half a pixel of gap is a gap."""
        self.place("a", 0, 0)
        self.place("b", 9.5, 0)
        self.assertTrue(self.collide())

    def test_a_fractional_gap_is_still_a_gap(self):
        self.place("a", 0, 0)
        self.place("b", 10.5, 0)
        self.assertFalse(self.collide())


class TestTouchingIsNotOverlapping(CollisionTestCase):
    """Walls laid side by side must not report every seam as a collision."""

    def test_sharing_a_vertical_edge(self):
        self.place("a", 0, 0)
        self.place("b", 10, 0)
        self.assertFalse(self.collide())

    def test_sharing_a_horizontal_edge(self):
        self.place("a", 0, 0)
        self.place("b", 0, 10)
        self.assertFalse(self.collide())

    def test_meeting_at_one_corner(self):
        self.place("a", 0, 0)
        self.place("b", 10, 10)
        self.assertFalse(self.collide())

    def test_the_other_side_of_the_edge(self):
        self.place("a", 10, 0)
        self.place("b", 0, 0)
        self.assertFalse(self.collide())

    def test_a_hair_past_the_edge_does_collide(self):
        self.place("a", 0, 0)
        self.place("b", 9.999, 0)
        self.assertTrue(self.collide())

    def test_a_row_of_walls_has_no_collisions_in_it(self):
        """The case the rule exists for."""
        for index in range(6):
            self.place(f"wall{index}", index * 10, 0)
        for index in range(5):
            with self.subTest(seam=index):
                self.assertFalse(
                    self.collide(f"wall{index}", f"wall{index + 1}"))

    def test_an_object_with_no_width_touches_nothing(self):
        self.place("a", 0, 0, 0, 10)
        self.place("b", 0, 0, 10, 10)
        self.assertFalse(self.collide())

    def test_the_public_api_will_not_scale_an_object_to_nothing(self):
        """So the zero-area case cannot be reached by a game by accident."""
        self.place("a", 0, 0)
        with self.assertRaises(ValueError):
            GameObject("a").set.scale(0.0)

    def test_an_object_scaled_to_nothing_touches_nothing(self):
        """Reached through the table, since the public API refuses it: the
        arithmetic still has to answer sensibly."""
        self.place("a", 0, 0)
        self.place("b", 0, 0)
        table = engine.current().objects
        table.scale[current_scene().require("a")._slot] = 0.0
        self.assertFalse(self.collide())


class TestScaleChangesTheBounds(CollisionTestCase):
    def test_scaling_up_reaches_something_it_did_not(self):
        self.place("player", 0, 0)
        self.place("wall", 20, 0)
        self.assertFalse(self.collide("player", "wall"))
        GameObject("player").set.scale(4.0)      # 10 wide -> 40 wide
        self.assertTrue(self.collide("player", "wall"))

    def test_scaling_down_lets_go_of_something(self):
        self.place("player", 0, 0, 40, 40)
        self.place("wall", 30, 30)
        self.assertTrue(self.collide("player", "wall"))
        GameObject("player").set.scale(0.5)      # 40 wide -> 20 wide
        self.assertFalse(self.collide("player", "wall"))

    def test_scaling_the_other_object_works_the_same(self):
        self.place("player", 0, 0)
        self.place("wall", 20, 0)
        self.assertFalse(self.collide("player", "wall"))
        GameObject("wall").set.scale(3.0)
        # The wall grows from its own top-left, so it grows away, not towards.
        self.assertFalse(self.collide("player", "wall"))
        GameObject("wall").set.x(11.0)
        self.assertFalse(self.collide("player", "wall"))
        GameObject("wall").set.x(9.0)
        self.assertTrue(self.collide("player", "wall"))

    def test_a_fractional_scale(self):
        self.place("a", 0, 0)
        self.place("b", 12, 0)
        GameObject("a").set.scale(1.25)          # 10 -> 12.5
        self.assertTrue(self.collide())

    def test_scale_grows_from_the_top_left_corner(self):
        """The same corner scaling has always grown from."""
        self.place("a", 0, 0)
        self.place("behind", -5, 0)
        self.assertTrue(self.collide("a", "behind"))
        GameObject("a").set.scale(10.0)
        # Growing right and down cannot reach further left.
        self.assertTrue(self.collide("a", "behind"))
        GameObject("behind").set.x(-10.0)
        self.assertFalse(self.collide("a", "behind"))

    def test_the_bounds_match_what_size_reports(self):
        """What a game is told an object's size is, and what it collides
        with, must be the same rectangle."""
        self.place("a", 7, 3, 12, 8)
        GameObject("a").set.scale(2.0)
        handle = GameObject("a")
        left, top, right, bottom = collision.bounds(handle._object)
        self.assertEqual((right - left, bottom - top), handle.size)
        self.assertEqual((left, top), (handle.x, handle.y))


class TestInvisibleObjectsStillCollide(CollisionTestCase):
    """Invisible walls, boundaries and hitboxes are made of these."""

    def test_an_invisible_object_collides(self):
        self.place("player", 0, 0)
        self.place("wall", 5, 5)
        GameObject("wall").visible = False
        self.assertTrue(self.collide("player", "wall"))

    def test_both_invisible(self):
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        GameObject("a").visible = False
        GameObject("b").visible = False
        self.assertTrue(self.collide())

    def test_hiding_an_object_does_not_change_the_answer(self):
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        before = self.collide()
        GameObject("b").visible = False
        self.assertEqual(self.collide(), before)

    def test_showing_it_again_does_not_either(self):
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        GameObject("b").visible = False
        GameObject("b").visible = True
        self.assertTrue(self.collide())

    def test_invisible_is_not_destroyed(self):
        """The distinction the rule turns on."""
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        GameObject("b").visible = False
        self.assertTrue(self.collide(), "invisible should still collide")
        GameObject("b").destroy()
        self.assertFalse(self.collide(), "destroyed should not")


class TestDestroyedObjects(CollisionTestCase):
    def test_a_destroyed_object_does_not_collide(self):
        self.place("player", 0, 0)
        self.place("wall", 5, 5)
        self.assertTrue(self.collide("player", "wall"))
        GameObject("wall").destroy()
        self.assertFalse(self.collide("player", "wall"))

    def test_destroying_the_first_one_named(self):
        self.place("player", 0, 0)
        self.place("wall", 5, 5)
        GameObject("player").destroy()
        self.assertFalse(self.collide("player", "wall"))

    def test_destroying_both(self):
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        GameObject("a").destroy()
        GameObject("b").destroy()
        self.assertFalse(self.collide())

    def test_destroying_warns_that_the_name_is_gone(self):
        """A destroyed object is out of the scene, so asking about it is
        asking about a name that is not there -- and that is said, not
        silently answered False."""
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        GameObject("b").destroy()
        with self.assertWarns(TrjoLudusWarning):
            self.assertFalse(objects.collide("a", "b"))

    def test_a_slot_reused_by_a_new_object_is_not_the_old_one(self):
        """Destroying frees the table slot; the next object gets it. The
        destroyed object must not come back to life wearing it."""
        self.place("player", 0, 0)
        self.place("wall", 5, 5)
        slot = current_scene().require("wall")._slot
        GameObject("wall").destroy()
        self.place("elsewhere", 900, 900)
        self.assertEqual(current_scene().require("elsewhere")._slot, slot)
        self.assertFalse(self.collide("player", "wall"))
        self.assertFalse(self.collide("player", "elsewhere"))


class TestMissingNames(CollisionTestCase):
    def test_the_first_name_is_missing(self):
        self.place("real", 0, 0)
        with self.assertWarns(TrjoLudusWarning):
            self.assertFalse(objects.collide("ghost", "real"))

    def test_the_second_name_is_missing(self):
        self.place("real", 0, 0)
        with self.assertWarns(TrjoLudusWarning):
            self.assertFalse(objects.collide("real", "ghost"))

    def test_both_names_are_missing(self):
        with self.assertWarns(TrjoLudusWarning):
            self.assertFalse(objects.collide("ghost", "spectre"))

    def test_both_missing_names_are_reported(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            objects.collide("ghost", "spectre")
        said = " ".join(str(warning.message) for warning in caught)
        self.assertIn("ghost", said)
        self.assertIn("spectre", said)

    def test_the_warning_names_the_object_that_is_missing(self):
        self.place("real", 0, 0)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            objects.collide("real", "zomby")
        message = str(caught[0].message)
        self.assertIn("zomby", message, "the warning must name the mistake")
        self.assertIn("real", message, "and say what does exist")

    def test_it_is_a_warning_and_not_an_error(self):
        self.place("real", 0, 0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TrjoLudusWarning)
            objects.collide("real", "ghost")     # must not raise

    def test_a_missing_name_never_answers_true(self):
        self.place("real", 0, 0, 1000, 1000)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TrjoLudusWarning)
            self.assertFalse(objects.collide("real", "ghost"))

    def test_the_warning_points_at_the_game_not_at_trjoludus(self):
        """A warning blaming a file inside the engine helps nobody."""
        self.place("real", 0, 0)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            objects.collide("real", "ghost")
        self.assertTrue(caught[0].filename.endswith("test_collision.py"),
                        f"blamed {caught[0].filename}")


class TestAnObjectCannotCollideWithItself(CollisionTestCase):
    def test_it_raises(self):
        self.place("player", 0, 0)
        with self.assertRaises(CollisionError):
            objects.collide("player", "player")

    def test_it_does_not_answer_true(self):
        self.place("player", 0, 0)
        try:
            answer = objects.collide("player", "player")
        except CollisionError:
            return
        self.fail(f"answered {answer!r} instead of raising")

    def test_the_error_names_the_object(self):
        self.place("player", 0, 0)
        with self.assertRaises(CollisionError) as caught:
            objects.collide("player", "player")
        self.assertIn("player", str(caught.exception))

    def test_the_error_explains_what_is_wrong(self):
        self.place("player", 0, 0)
        with self.assertRaises(CollisionError) as caught:
            objects.collide("player", "player")
        self.assertIn("itself", str(caught.exception))

    def test_it_raises_even_when_the_object_does_not_exist(self):
        """Wrong whether or not there is such an object."""
        with self.assertRaises(CollisionError):
            objects.collide("nobody", "nobody")

    def test_it_is_a_trjoludus_error(self):
        from trjoludus import TrjoLudusError

        self.place("player", 0, 0)
        with self.assertRaises(TrjoLudusError):
            objects.collide("player", "player")

    def test_two_different_objects_are_still_fine(self):
        self.place("player", 0, 0)
        self.place("player2", 0, 0)
        self.assertTrue(self.collide("player", "player2"))


class TestMovingInAndOut(CollisionTestCase):
    def test_moving_into_something_and_out_again(self):
        self.place("player", 0, 0)
        self.place("zombie", 30, 0)
        player = GameObject("player")

        self.assertFalse(self.collide("player", "zombie"))
        player.set.x(25.0)
        self.assertTrue(self.collide("player", "zombie"), "moved in")
        player.set.x(45.0)
        self.assertFalse(self.collide("player", "zombie"), "moved past")
        player.set.x(0.0)
        self.assertFalse(self.collide("player", "zombie"), "moved back")

    def test_walking_past_step_by_step(self):
        """The answer changes exactly where the rectangles say it does."""
        self.place("player", 0, 0)
        self.place("wall", 20, 0)
        player = GameObject("player")
        answers = []
        for step in range(0, 41, 5):
            player.set.x(float(step))
            answers.append(self.collide("player", "wall"))
        # x = 0,5 apart; 15,20,25 overlapping; 10 and 30 share an edge.
        self.assertEqual(
            answers,
            [False, False, False, True, True, True, False, False, False])

    def test_moving_with_the_movement_api(self):
        self.place("player", 0, 0)
        self.place("zombie", 15, 0)
        player = GameObject("player")
        self.assertFalse(self.collide("player", "zombie"))
        player.move.x(10)
        self.assertTrue(self.collide("player", "zombie"))

    def test_moving_diagonally(self):
        self.place("player", 0, 0)
        self.place("zombie", 30, 30)
        player = GameObject("player")
        player.set.x(25.0)
        self.assertFalse(self.collide("player", "zombie"), "across only")
        player.set.y(25.0)
        self.assertTrue(self.collide("player", "zombie"), "both now")

    def test_moving_the_other_object(self):
        self.place("player", 0, 0)
        self.place("zombie", 100, 0)
        self.assertFalse(self.collide("player", "zombie"))
        GameObject("zombie").set.x(5.0)
        self.assertTrue(self.collide("player", "zombie"))

    def test_sub_pixel_steps_change_the_answer_where_they_should(self):
        self.place("a", 0, 0)
        self.place("b", 10.5, 0)
        b = GameObject("b")
        self.assertFalse(self.collide())
        b.set.x(10.0)
        self.assertFalse(self.collide(), "an edge is not an overlap")
        b.set.x(9.5)
        self.assertTrue(self.collide())


class TestItOnlyAnswers(CollisionTestCase):
    """TrjoLudus detects what happened; the game decides what it means."""

    def positions(self):
        return [(o.name, o.x, o.y, o.scale, o.visible)
                for o in current_scene().objects()]

    def test_asking_moves_nothing(self):
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        before = self.positions()
        self.collide()
        self.assertEqual(self.positions(), before)

    def test_asking_about_something_that_does_not_touch_moves_nothing(self):
        self.place("a", 0, 0)
        self.place("b", 500, 500)
        before = self.positions()
        self.collide()
        self.assertEqual(self.positions(), before)

    def test_asking_destroys_nothing(self):
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        self.collide()
        self.assertEqual(set(current_scene().names), {"a", "b"})

    def test_asking_starts_no_animation(self):
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        self.collide()
        for name in ("a", "b"):
            self.assertIsNone(GameObject(name).animation.current)

    def test_asking_changes_no_visibility(self):
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        self.collide()
        self.assertTrue(GameObject("a").visible)

    def test_asking_twice_gives_the_same_answer(self):
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        self.assertEqual([self.collide() for _ in range(5)], [True] * 5)

    def test_asking_claims_no_table_slots(self):
        """No hidden object is created to answer with."""
        self.place("a", 0, 0)
        self.place("b", 5, 5)
        before = len(engine.current().objects)
        self.collide()
        self.assertEqual(len(engine.current().objects), before)


class TestThereIsNoSecondCopyOfAnything(CollisionTestCase):
    """Collision reads the object table, like everything else."""

    def test_it_reads_the_table_a_python_write_changed(self):
        self.place("a", 0, 0)
        self.place("b", 100, 0)
        self.assertFalse(self.collide())
        table = engine.current().objects
        table.x[current_scene().require("b")._slot] = 5.0
        self.assertTrue(self.collide(), "collision read a stale position")

    def test_it_reads_the_size_the_table_holds(self):
        self.place("a", 0, 0)
        self.place("b", 20, 0)
        self.assertFalse(self.collide())
        # A bigger picture makes a bigger object, and a bigger hitbox.
        current_scene().require("a").image = picture(40, 40)
        self.assertTrue(self.collide())

    def test_it_reads_the_scale_the_table_holds(self):
        self.place("a", 0, 0)
        self.place("b", 20, 0)
        table = engine.current().objects
        table.scale[current_scene().require("a")._slot] = 5.0
        self.assertTrue(self.collide())

    def test_collision_keeps_no_state_of_its_own(self):
        """No cache, no last answer, nothing to go stale."""
        stateful = [name for name in vars(collision)
                    if not name.startswith("__")
                    and isinstance(getattr(collision, name),
                                   (dict, list, set))]
        self.assertEqual(stateful, [], f"{stateful} looks like a cache")


class TestBadArguments(CollisionTestCase):
    def test_a_name_that_is_not_a_string(self):
        self.place("player", 0, 0)
        for wrong in (1, None, 3.5, ["player"]):
            with self.subTest(name=wrong):
                with self.assertRaises(TypeError):
                    objects.collide("player", wrong)

    def test_the_first_name_not_a_string(self):
        self.place("player", 0, 0)
        with self.assertRaises(TypeError):
            objects.collide(7, "player")

    def test_the_type_error_says_what_it_got(self):
        self.place("player", 0, 0)
        with self.assertRaises(TypeError) as caught:
            objects.collide("player", 7)
        self.assertIn("int", str(caught.exception))


class TestTheApiSurface(CollisionTestCase):
    def test_objects_offers_only_collide(self):
        self.assertEqual(objects.__all__, ["collide"])
        self.assertEqual([n for n in dir(objects) if not n.startswith("_")],
                         ["collide"])

    def test_it_is_reachable_the_way_a_game_writes_it(self):
        import trjoludus

        self.assertIn("objects", trjoludus.__all__)
        self.assertIs(trjoludus.objects.collide, objects.collide)

    def test_the_wildcard_brings_it_in(self):
        namespace = {}
        exec("from trjoludus import *", namespace)
        self.assertIn("objects", namespace)
        self.assertIn("CollisionError", namespace)

    def test_no_backend_detail_leaks_into_the_namespace(self):
        for hidden in ("engine", "bounds", "overlap", "registry", "ctypes",
                       "ObjectTable", "SceneObject"):
            with self.subTest(name=hidden):
                self.assertFalse(hasattr(objects, hidden))

    def test_collision_reports_a_python_implementation(self):
        """It has one now, so it recommends one."""
        from trjoludus.native import PYTHON, registry

        system = registry.system("collision")
        self.assertEqual(system.recommends, PYTHON)
        self.assertTrue(system.python_available())
        self.assertEqual(system.resolve(), PYTHON)

    def test_there_is_still_no_native_collision(self):
        from trjoludus.native import registry

        self.assertFalse(registry.system("collision").native_available())

    def test_asking_for_rust_collision_says_there_is_none(self):
        from trjoludus.native import RUST, EngineError, registry

        system = registry.system("collision")
        self.addCleanup(registry.reset)
        system.engine = RUST
        with self.assertRaises(EngineError):
            system.resolve()


class TestItWorksInsideARunningGame(CollisionTestCase):
    """The way a game actually uses it: from on_update."""

    def play(self, game):
        from trjoludus.app import Application
        from trjoludus.platform.null import NullBackend

        Application(game, size=(200, 200), max_fps=None,
                    backend=NullBackend()).run()

    def test_a_game_can_ask_during_a_frame(self):
        from trjoludus import Game, create

        answers = []
        image = picture()

        class Chase(Game):
            def on_start(self):
                current_scene().add(SceneObject("player", image, 0, 0))
                current_scene().add(SceneObject("zombie", image, 30, 0))

            def on_update(self, dt):
                player = GameObject("player")
                answers.append(objects.collide("player", "zombie"))
                player.set.x(player.x + 15)
                if len(answers) >= 3:
                    self.quit()

        del create
        self.play(Chase())
        self.assertEqual(answers, [False, False, True])

    def test_the_developer_decides_what_it_means(self):
        """The intended shape, end to end: detect, then act."""
        from trjoludus import Game

        image = picture()
        health = [100]

        class Fight(Game):
            def on_start(self):
                current_scene().add(SceneObject("player", image, 0, 0))
                current_scene().add(SceneObject("sword", image, 5, 0))

            def on_update(self, dt):
                if objects.collide("player", "sword"):
                    health[0] -= 25          # the game's decision, not ours
                self.quit()

        self.play(Fight())
        self.assertEqual(health[0], 75)


if __name__ == "__main__":
    unittest.main()
