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
    def test_objects_offers_only_the_collision_questions(self):
        self.assertEqual(objects.__all__, ["collide", "colliding"])
        self.assertEqual(
            sorted(n for n in dir(objects) if not n.startswith("_")),
            ["collide", "colliding"])

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


class CollidingTestCase(CollisionTestCase):
    """Helpers for the second question: what is this one touching?"""

    def names(self, name="player"):
        """The result as names, which is what most assertions want to read."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TrjoLudusWarning)
            return [found.name for found in objects.colliding(name)]

    def ask(self, name="player"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TrjoLudusWarning)
            return objects.colliding(name)


class TestWhatIsTouchingThis(CollidingTestCase):
    def test_nothing_is_touching_it(self):
        self.place("player", 0, 0)
        self.place("far", 500, 500)
        self.assertEqual(self.ask(), ())

    def test_an_empty_scene_apart_from_the_object_itself(self):
        self.place("player", 0, 0)
        self.assertEqual(self.ask(), ())

    def test_one_thing_is_touching_it(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.assertEqual(self.names(), ["zombie"])

    def test_several_things_are_touching_it(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.place("wall", 8, 0)
        self.place("spike", 0, 9)
        self.assertEqual(sorted(self.names()), ["spike", "wall", "zombie"])

    def test_the_ones_that_are_not_touching_stay_out(self):
        self.place("player", 0, 0)
        self.place("near", 5, 5)
        self.place("far", 500, 500)
        self.place("beyond", -500, -500)
        self.assertEqual(self.names(), ["near"])

    def test_something_completely_inside_it(self):
        self.place("player", 0, 0, 100, 100)
        self.place("crumb", 40, 40, 2, 2)
        self.assertEqual(self.names(), ["crumb"])

    def test_something_it_is_completely_inside(self):
        self.place("player", 40, 40, 2, 2)
        self.place("room", 0, 0, 100, 100)
        self.assertEqual(self.names(), ["room"])

    def test_something_it_only_shares_an_edge_with(self):
        self.place("player", 0, 0)
        self.place("neighbour", 10, 0)
        self.assertEqual(self.ask(), (),
                         "touching is not overlapping, here too")

    def test_a_corner_neighbour_is_out_and_a_real_overlap_is_in(self):
        self.place("player", 0, 0)
        self.place("corner", 10, 10)
        self.place("overlapping", 9, 9)
        self.assertEqual(self.names(), ["overlapping"])

    def test_a_crowd(self):
        self.place("player", 0, 0, 100, 100)
        for index in range(20):
            self.place(f"thing{index}", index * 4, 0, 4, 4)
        # Everything from x=0 to x=96 overlaps a 100-wide player.
        self.assertEqual(len(self.names()), 20)

    def test_only_the_ones_that_reach(self):
        self.place("player", 0, 0, 20, 20)
        for index in range(10):
            self.place(f"thing{index}", index * 10, 0, 5, 5)
        # thing0 at 0..5 and thing1 at 10..15 reach; thing2 starts at 20.
        self.assertEqual(self.names(), ["thing0", "thing1"])


class TestItAgreesWithCollide(CollidingTestCase):
    """One set of rules, asked two ways."""

    def test_every_pair_agrees(self):
        self.place("player", 0, 0)
        placements = ((0, 0), (5, 5), (9, 9), (10, 0), (10, 10), (11, 11),
                      (-5, -5), (-10, 0), (9.5, 0), (10.5, 0), (500, 500))
        for index, (x, y) in enumerate(placements):
            self.place(f"other{index}", x, y)

        touching = set(self.names())
        for index in range(len(placements)):
            name = f"other{index}"
            with self.subTest(other=name, at=placements[index]):
                self.assertEqual(name in touching,
                                 self.collide("player", name))

    def test_they_agree_about_scale(self):
        self.place("player", 0, 0)
        self.place("wall", 20, 0)
        GameObject("player").set.scale(4.0)
        self.assertEqual(self.names(), ["wall"])
        self.assertTrue(self.collide("player", "wall"))

    def test_they_agree_about_fractional_positions(self):
        self.place("player", 0, 0)
        self.place("close", 9.5, 0)
        self.place("exact", 10.0, 0)
        self.assertEqual(self.names(), ["close"])
        self.assertTrue(self.collide("player", "close"))
        self.assertFalse(self.collide("player", "exact"))

    def test_they_use_the_same_bounds(self):
        self.place("player", 7.25, 3.5, 12, 8)
        self.place("other", 12.0, 4.0, 3, 3)
        subject = current_scene().require("player")
        self.assertEqual(collision.bounds(subject),
                         (7.25, 3.5, 7.25 + 12, 3.5 + 8))
        self.assertEqual(self.names(), ["other"])

    def test_neither_rounds(self):
        self.place("player", 0, 0)
        self.place("just_past", 10.5, 0)
        self.assertEqual(self.ask(), ())
        self.assertFalse(self.collide("player", "just_past"))


class TestOrdering(CollidingTestCase):
    """Creation order -- the scene's own, which is also draw order."""

    def test_results_come_back_in_creation_order(self):
        self.place("player", 0, 0, 100, 100)
        for name in ("first", "second", "third", "fourth"):
            self.place(name, 0, 0, 5, 5)
        self.assertEqual(self.names(), ["first", "second", "third", "fourth"])

    def test_creation_order_not_alphabetical(self):
        self.place("player", 0, 0, 100, 100)
        for name in ("zebra", "apple", "mango"):
            self.place(name, 0, 0, 5, 5)
        self.assertEqual(self.names(), ["zebra", "apple", "mango"])

    def test_the_same_scene_answers_the_same_way_every_time(self):
        self.place("player", 0, 0, 100, 100)
        for index in range(12):
            self.place(f"thing{index}", index, index, 5, 5)
        first = self.names()
        for _ in range(10):
            self.assertEqual(self.names(), first)

    def test_it_matches_the_scene_s_own_order(self):
        self.place("player", 0, 0, 100, 100)
        for name in ("c", "a", "b"):
            self.place(name, 0, 0, 5, 5)
        scene_order = [name for name in current_scene().names
                       if name != "player"]
        self.assertEqual(self.names(), scene_order)

    def test_a_destroyed_object_does_not_disturb_the_order(self):
        self.place("player", 0, 0, 100, 100)
        for name in ("a", "b", "c", "d"):
            self.place(name, 0, 0, 5, 5)
        GameObject("b").destroy()
        self.assertEqual(self.names(), ["a", "c", "d"])

    def test_a_new_object_joins_at_the_end(self):
        self.place("player", 0, 0, 100, 100)
        self.place("a", 0, 0, 5, 5)
        self.place("b", 0, 0, 5, 5)
        self.assertEqual(self.names(), ["a", "b"])
        self.place("c", 0, 0, 5, 5)
        self.assertEqual(self.names(), ["a", "b", "c"])


class TestItNeverReturnsItself(CollidingTestCase):
    def test_the_object_asked_about_is_not_in_its_own_result(self):
        self.place("player", 0, 0)
        self.assertNotIn("player", self.names())

    def test_not_even_when_others_are_touching_it(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.assertEqual(self.names(), ["zombie"])

    def test_not_even_among_a_crowd_at_the_same_place(self):
        self.place("player", 0, 0)
        for index in range(5):
            self.place(f"other{index}", 0, 0)
        self.assertNotIn("player", self.names())
        self.assertEqual(len(self.names()), 5)

    def test_another_object_at_exactly_the_same_place_is_returned(self):
        """Excluded for being itself, not for being where it is."""
        self.place("player", 0, 0)
        self.place("twin", 0, 0)
        self.assertEqual(self.names(), ["twin"])

    def test_collide_still_refuses_the_same_question(self):
        """The two say the same thing in the way each can."""
        self.place("player", 0, 0)
        self.assertNotIn("player", self.names())
        with self.assertRaises(CollisionError):
            objects.collide("player", "player")


class TestNoDuplicates(CollidingTestCase):
    def test_each_object_appears_once(self):
        self.place("player", 0, 0, 100, 100)
        for index in range(10):
            self.place(f"thing{index}", 0, 0, 5, 5)
        names = self.names()
        self.assertEqual(len(names), len(set(names)))

    def test_asking_repeatedly_does_not_accumulate(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        for _ in range(5):
            self.assertEqual(self.names(), ["zombie"])

    def test_one_handle_per_object_even_when_stacked(self):
        self.place("player", 0, 0)
        self.place("a", 0, 0)
        self.place("b", 1, 1)
        found = self.ask()
        self.assertEqual(len(found), 2)
        self.assertEqual(len({handle.name for handle in found}), 2)


class TestScaleChangesTheResult(CollidingTestCase):
    def test_scaling_another_object_up_brings_it_in(self):
        self.place("player", 0, 0)
        self.place("wall", 20, 0)
        self.assertEqual(self.ask(), ())
        GameObject("wall").set.scale(3.0)
        GameObject("wall").set.x(5.0)
        self.assertEqual(self.names(), ["wall"])

    def test_scaling_another_object_down_takes_it_out(self):
        # The blob reaches the player from the left: -15..5 against 0..10.
        self.place("player", 0, 0)
        self.place("blob", -15, 0, 20, 20)
        self.assertEqual(self.names(), ["blob"])
        # Shrinking pulls its right edge back to -13, short of the player.
        GameObject("blob").set.scale(0.1)
        self.assertEqual(self.ask(), ())

    def test_scaling_the_queried_object_reaches_further(self):
        self.place("player", 0, 0)
        self.place("wall", 25, 0)
        self.assertEqual(self.ask(), ())
        GameObject("player").set.scale(4.0)
        self.assertEqual(self.names(), ["wall"])

    def test_a_fractional_scale(self):
        self.place("player", 0, 0)
        self.place("wall", 12, 0)
        self.assertEqual(self.ask(), ())
        GameObject("player").set.scale(1.25)
        self.assertEqual(self.names(), ["wall"])


class TestMovementUpdatesTheResult(CollidingTestCase):
    def test_moving_into_something(self):
        self.place("player", 0, 0)
        self.place("zombie", 30, 0)
        self.assertEqual(self.ask(), ())
        GameObject("player").set.x(25.0)
        self.assertEqual(self.names(), ["zombie"])

    def test_moving_out_of_something(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 0)
        self.assertEqual(self.names(), ["zombie"])
        GameObject("player").set.x(100.0)
        self.assertEqual(self.ask(), ())

    def test_the_answer_moves_with_the_object_immediately(self):
        """No stale list: ask, move, ask again."""
        self.place("player", 0, 0)
        self.place("zombie", 50, 0)
        self.assertEqual(self.ask(), ())
        GameObject("player").move.x(45)
        self.assertEqual(self.names(), ["zombie"])
        GameObject("player").move.x(45)
        self.assertEqual(self.ask(), ())

    def test_walking_through_a_line_of_things(self):
        self.place("player", 0, 0, 5, 5)
        for index in range(4):
            self.place(f"post{index}", index * 20, 0, 5, 5)
        player = GameObject("player")
        seen = []
        for step in range(0, 61, 20):
            player.set.x(float(step))
            seen.append(self.names())
        self.assertEqual(seen, [["post0"], ["post1"], ["post2"], ["post3"]])

    def test_moving_the_other_objects_instead(self):
        self.place("player", 0, 0)
        self.place("a", 100, 0)
        self.place("b", 200, 0)
        self.assertEqual(self.ask(), ())
        GameObject("b").set.x(5.0)
        self.assertEqual(self.names(), ["b"])
        GameObject("a").set.x(2.0)
        self.assertEqual(self.names(), ["a", "b"],
                         "creation order, not the order they arrived")

    def test_a_sub_pixel_step_across_the_edge(self):
        self.place("player", 0, 0)
        self.place("wall", 10.0, 0)
        self.assertEqual(self.ask(), ())
        GameObject("wall").set.x(9.99)
        self.assertEqual(self.names(), ["wall"])


class TestDestroyedObjectsAreNotReturned(CollidingTestCase):
    def test_a_destroyed_object_disappears_from_the_result(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.assertEqual(self.names(), ["zombie"])
        GameObject("zombie").destroy()
        self.assertEqual(self.ask(), ())

    def test_the_others_are_still_there(self):
        self.place("player", 0, 0)
        self.place("a", 1, 1)
        self.place("b", 2, 2)
        GameObject("a").destroy()
        self.assertEqual(self.names(), ["b"])

    def test_destroying_the_queried_object_answers_empty_and_warns(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        GameObject("player").destroy()
        with self.assertWarns(TrjoLudusWarning):
            self.assertEqual(objects.colliding("player"), ())

    def test_destroying_everything(self):
        self.place("player", 0, 0)
        for name in ("a", "b", "c"):
            self.place(name, 1, 1)
        for name in ("a", "b", "c"):
            GameObject(name).destroy()
        self.assertEqual(self.ask(), ())

    def test_a_reused_table_slot_is_the_new_object_only(self):
        """Destroying frees a slot; the next object gets it. The destroyed one
        must not come back wearing it, and the new one must be itself."""
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        slot = current_scene().require("zombie")._slot
        GameObject("zombie").destroy()
        self.assertEqual(self.ask(), ())

        self.place("ghost", 6, 6)
        self.assertEqual(current_scene().require("ghost")._slot, slot,
                         "the test needs the slot to be reused")
        self.assertEqual(self.names(), ["ghost"])

    def test_a_reused_slot_belonging_to_something_far_away(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        GameObject("zombie").destroy()
        self.place("elsewhere", 900, 900)
        self.assertEqual(self.ask(), ())

    def test_there_is_no_registry_to_go_stale(self):
        """Destroy, recreate under the same name, and the answer is about the
        new object rather than a remembered one."""
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.assertEqual(self.names(), ["zombie"])
        GameObject("zombie").destroy()
        self.place("zombie", 900, 900)
        self.assertEqual(self.ask(), ())


class TestInvisibleObjectsAreReturned(CollidingTestCase):
    def test_an_invisible_object_is_in_the_result(self):
        self.place("player", 0, 0)
        self.place("boundary", 5, 5)
        GameObject("boundary").visible = False
        self.assertEqual(self.names(), ["boundary"])

    def test_hiding_something_does_not_change_the_result(self):
        self.place("player", 0, 0)
        self.place("a", 1, 1)
        self.place("b", 2, 2)
        before = self.names()
        GameObject("a").visible = False
        self.assertEqual(self.names(), before)

    def test_the_queried_object_may_be_invisible_too(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        GameObject("player").visible = False
        self.assertEqual(self.names(), ["zombie"])

    def test_everything_invisible_still_collides(self):
        self.place("player", 0, 0)
        for name in ("a", "b"):
            self.place(name, 1, 1)
            GameObject(name).visible = False
        GameObject("player").visible = False
        self.assertEqual(self.names(), ["a", "b"])

    def test_invisible_is_returned_and_destroyed_is_not(self):
        self.place("player", 0, 0)
        self.place("hidden", 1, 1)
        self.place("gone", 2, 2)
        GameObject("hidden").visible = False
        GameObject("gone").destroy()
        self.assertEqual(self.names(), ["hidden"])


class TestMissingNames(CollidingTestCase):
    def test_it_answers_empty(self):
        self.place("real", 0, 0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TrjoLudusWarning)
            self.assertEqual(objects.colliding("ghost"), ())

    def test_it_warns(self):
        self.place("real", 0, 0)
        with self.assertWarns(TrjoLudusWarning):
            objects.colliding("ghost")

    def test_it_does_not_raise(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TrjoLudusWarning)
            objects.colliding("ghost")      # must not raise

    def test_the_warning_names_the_missing_object(self):
        self.place("real", 0, 0)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            objects.colliding("zomby")
        message = str(caught[0].message)
        self.assertIn("zomby", message)
        self.assertIn("real", message, "and says what does exist")

    def test_the_warning_blames_the_game_s_own_line(self):
        self.place("real", 0, 0)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            objects.colliding("ghost")
        self.assertTrue(caught[0].filename.endswith("test_collision.py"),
                        f"blamed {caught[0].filename}")

    def test_it_warns_the_same_way_collide_does(self):
        self.place("real", 0, 0)
        with warnings.catch_warnings(record=True) as one:
            warnings.simplefilter("always")
            objects.colliding("ghost")
        with warnings.catch_warnings(record=True) as two:
            warnings.simplefilter("always")
            objects.collide("real", "ghost")
        self.assertEqual(str(one[0].message), str(two[0].message))

    def test_an_empty_scene(self):
        with self.assertWarns(TrjoLudusWarning):
            self.assertEqual(objects.colliding("anything"), ())


class TestBadArguments(CollidingTestCase):
    def test_a_name_that_is_not_a_string(self):
        self.place("player", 0, 0)
        for wrong in (1, None, 2.5, ["player"], b"player"):
            with self.subTest(name=wrong):
                with self.assertRaises(TypeError):
                    objects.colliding(wrong)

    def test_the_type_error_says_what_it_got(self):
        with self.assertRaises(TypeError) as caught:
            objects.colliding(7)
        self.assertIn("int", str(caught.exception))

    def test_it_refuses_the_same_things_collide_refuses(self):
        self.place("player", 0, 0)
        for wrong in (1, None, 2.5):
            with self.subTest(name=wrong):
                with self.assertRaises(TypeError):
                    objects.colliding(wrong)
                with self.assertRaises(TypeError):
                    objects.collide("player", wrong)


class TestWhatComesBack(CollidingTestCase):
    """GameObject handles: the same thing create.image() gives you."""

    def test_the_result_is_a_tuple(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.assertIsInstance(self.ask(), tuple)

    def test_the_elements_are_game_objects(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        for found in self.ask():
            self.assertIsInstance(found, GameObject)

    def test_a_returned_handle_can_be_used_straight_away(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 7)
        zombie = self.ask()[0]
        self.assertEqual(zombie.name, "zombie")
        self.assertEqual((zombie.x, zombie.y), (5, 7))
        self.assertEqual(zombie.size, (10, 10))

    def test_a_returned_handle_can_move_its_object(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.ask()[0].set.x(500.0)
        self.assertEqual(current_scene().require("zombie").x, 500)

    def test_a_returned_handle_equals_one_made_by_name(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.assertEqual(self.ask()[0], GameObject("zombie"))

    def test_it_is_the_same_kind_of_thing_create_returns(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.assertIs(type(self.ask()[0]), GameObject)

    def test_names_are_one_attribute_away(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.place("wall", 1, 1)
        self.assertIn("zombie", [found.name for found in self.ask()])

    def test_the_result_can_be_looped_over_more_than_once(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        found = self.ask()
        self.assertEqual(len(list(found)), 1)
        self.assertEqual(len(list(found)), 1, "a generator leaked out")

    def test_an_empty_result_is_falsey(self):
        self.place("player", 0, 0)
        self.assertFalse(self.ask())

    def test_a_result_with_something_in_it_is_truthy(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.assertTrue(self.ask())


class TestItOnlyAnswers(CollidingTestCase):
    """Asking changes nothing."""

    def snapshot(self):
        return [(o.name, o.x, o.y, o.scale, o.visible)
                for o in current_scene().objects()]

    def crowd(self):
        self.place("player", 0, 0)
        for index in range(5):
            self.place(f"thing{index}", index, index)

    def test_asking_moves_nothing(self):
        self.crowd()
        before = self.snapshot()
        self.ask()
        self.assertEqual(self.snapshot(), before)

    def test_asking_destroys_nothing(self):
        self.crowd()
        before = set(current_scene().names)
        self.ask()
        self.assertEqual(set(current_scene().names), before)

    def test_asking_starts_no_animation(self):
        self.crowd()
        self.ask()
        for name in current_scene().names:
            self.assertIsNone(GameObject(name).animation.current)

    def test_asking_claims_no_table_slots(self):
        self.crowd()
        before = len(engine.current().objects)
        self.ask()
        self.ask()
        self.assertEqual(len(engine.current().objects), before)

    def test_asking_changes_no_visibility(self):
        self.crowd()
        self.ask()
        for name in current_scene().names:
            self.assertTrue(GameObject(name).visible)

    def test_asking_about_a_missing_object_changes_nothing(self):
        self.crowd()
        before = self.snapshot()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TrjoLudusWarning)
            objects.colliding("ghost")
        self.assertEqual(self.snapshot(), before)

    def test_using_a_returned_handle_is_the_game_s_decision(self):
        """The intended shape: TrjoLudus finds them, the game acts."""
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.place("spike", 2, 2)
        health = 100
        for enemy in self.ask():
            health -= 25            # the game's decision, not the engine's
        self.assertEqual(health, 50)
        self.assertEqual(self.snapshot(), self.snapshot())


class TestNothingIsRemembered(CollidingTestCase):
    def test_the_answer_is_worked_out_each_time(self):
        self.place("player", 0, 0)
        self.place("zombie", 100, 0)
        self.assertEqual(self.ask(), ())
        slot = current_scene().require("zombie")._slot
        engine.current().objects.x[slot] = 5.0
        self.assertEqual(self.names(), ["zombie"],
                         "the answer was remembered from before")

    def test_the_module_holds_no_result(self):
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.ask()
        stateful = [name for name in vars(collision)
                    if not name.startswith("__")
                    and isinstance(getattr(collision, name),
                                   (dict, list, set, tuple))]
        self.assertEqual(stateful, [], f"{stateful} looks like a cache")

    def test_there_is_no_collision_specific_storage(self):
        """No second copy of a position, size, scale or lifetime."""
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        self.ask()
        for obj in current_scene().objects():
            self.assertEqual(
                set(type(obj).__slots__),
                {"name", "_image", "removed", "animator", "_table", "_slot"},
                "an object grew a collision-only field")

    def test_the_scan_is_the_only_thing_that_knows_how_things_are_found(self):
        """A future grid or tree replaces one function and nothing else."""
        self.assertTrue(callable(collision._overlapping))
        self.place("player", 0, 0)
        self.place("zombie", 5, 5)
        subject = current_scene().require("player")
        self.assertEqual([o.name for o in collision._overlapping(subject)],
                         ["zombie"])


class TestTheApiSurfaceAfterPhaseTwo(CollidingTestCase):
    def test_objects_offers_exactly_the_two_questions(self):
        self.assertEqual(objects.__all__, ["collide", "colliding"])
        self.assertEqual(
            sorted(n for n in dir(objects) if not n.startswith("_")),
            ["collide", "colliding"])

    def test_no_internals_leaked_into_the_namespace(self):
        for hidden in ("bounds", "overlap", "engine", "registry",
                       "_participates", "_overlapping", "_find",
                       "ObjectTable", "SceneObject", "current_scene"):
            with self.subTest(name=hidden):
                self.assertFalse(hasattr(objects, hidden))

    def test_it_is_reachable_the_way_a_game_writes_it(self):
        import trjoludus

        self.assertIs(trjoludus.objects.colliding, objects.colliding)

    def test_the_wildcard_is_unchanged_apart_from_nothing(self):
        import trjoludus

        namespace = {}
        exec("from trjoludus import *", namespace)
        namespace.pop("__builtins__", None)
        self.assertEqual(set(namespace), set(trjoludus.__all__))

    def test_the_collision_module_exports_both(self):
        self.assertEqual(collision.__all__,
                         ["CollisionError", "collide", "colliding"])


class TestInsideARunningGame(CollidingTestCase):
    def play(self, game):
        from trjoludus.app import Application
        from trjoludus.platform.null import NullBackend

        Application(game, size=(200, 200), max_fps=None,
                    backend=NullBackend()).run()

    def test_a_game_can_ask_during_a_frame(self):
        from trjoludus import Game

        seen = []
        picture_ = picture()

        class Sweep(Game):
            def on_start(self):
                current_scene().add(SceneObject("player", picture_, 0, 0))
                for index in range(3):
                    current_scene().add(
                        SceneObject(f"post{index}", picture_, index * 20, 0))

            def on_update(self, dt):
                player = GameObject("player")
                seen.append([f.name for f in objects.colliding("player")])
                player.set.x(player.x + 20)
                if len(seen) >= 3:
                    self.quit()

        self.play(Sweep())
        self.assertEqual(seen, [["post0"], ["post1"], ["post2"]])

    def test_the_developer_decides_what_it_means(self):
        from trjoludus import Game

        picture_ = picture()
        damage = []

        class Fight(Game):
            def on_start(self):
                current_scene().add(SceneObject("player", picture_, 0, 0))
                current_scene().add(SceneObject("sword", picture_, 2, 0))
                current_scene().add(SceneObject("claw", picture_, 4, 0))
                current_scene().add(SceneObject("cloud", picture_, 900, 0))

            def on_update(self, dt):
                for enemy in objects.colliding("player"):
                    damage.append(enemy.name)      # the game's decision
                self.quit()

        self.play(Fight())
        self.assertEqual(damage, ["sword", "claw"])


if __name__ == "__main__":
    unittest.main()
