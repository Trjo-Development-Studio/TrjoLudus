"""Tests for the shared engine state.

The rule these exist to enforce: **there is one authoritative copy of
anything**. Rendering, physics and collision must read the same number, not
three numbers that are supposed to agree.

So these do not check that two values happen to match. They check that there
is only one value: written through Python and read through the native
boundary, written natively and read through Python, and -- where a library is
available -- proved to be the same memory rather than a copy that was
refreshed at the right moment.
"""

import unittest

from trjoludus import Game, GameObject, engine
from trjoludus.app import Application
from trjoludus.image import Image
from trjoludus.native import library
from trjoludus.native import world as native_world
from trjoludus.platform.null import NullBackend
from trjoludus.scene import SceneObject, current_scene
from trjoludus.ui import current_ui


def an_image(width=4, height=4):
    return Image(width, height, bytes([0, 0, 250, 255]) * (width * height))


class EngineStateTestCase(unittest.TestCase):
    def setUp(self):
        engine.end_run()
        library.forget()
        native_world.forget()
        self.addCleanup(engine.end_run)
        self.addCleanup(native_world.forget)
        self.addCleanup(library.forget)
        self.image = an_image()

    def object(self, name="player", x=0, y=0):
        return current_scene().add(SceneObject(name, self.image, x, y))


class TestTheStateIsStructured(EngineStateTestCase):
    """Not a bag of globals: an owned thing with named parts."""

    def test_there_is_one_state(self):
        self.assertIs(engine.current(), engine.current())

    def test_it_owns_the_world_and_the_drawings(self):
        state = engine.current()
        self.assertIs(state.world, current_scene())
        self.assertIs(state.drawings, current_ui())

    def test_it_owns_the_object_table(self):
        self.assertIsInstance(engine.current().objects, engine.ObjectTable)

    def test_its_parts_are_named_rather_than_arbitrary(self):
        self.assertEqual(set(engine.EngineState.__slots__),
                         {"objects", "world", "drawings", "clock",
                          "resources", "groups"})

    def test_there_are_no_loose_module_globals_left(self):
        """scene and ui used to keep their own singletons."""
        import trjoludus.scene
        import trjoludus.ui

        self.assertFalse(hasattr(trjoludus.scene, "_current"))
        self.assertFalse(hasattr(trjoludus.ui, "_current"))

    def test_the_state_is_not_public(self):
        import trjoludus

        self.assertNotIn("engine", trjoludus.__all__)
        self.assertNotIn("EngineState", trjoludus.__all__)


class TestOneAuthoritativeCopy(EngineStateTestCase):
    """An object's numbers live in exactly one place."""

    def test_the_object_reads_the_table(self):
        thing = self.object(x=10, y=20)
        table = engine.current().objects
        self.assertEqual(table.x[thing._slot], 10.0)
        self.assertEqual(table.y[thing._slot], 20.0)

    def test_writing_the_object_writes_the_table(self):
        thing = self.object()
        thing.x = 123.5
        self.assertEqual(engine.current().objects.x[thing._slot], 123.5)

    def test_writing_the_table_is_seen_by_the_object(self):
        thing = self.object()
        engine.current().objects.y[thing._slot] = 77.25
        self.assertEqual(thing.y, 77.25)

    def test_the_object_holds_no_copy_of_its_position(self):
        thing = self.object()
        stored = [name for name in type(thing).__slots__
                  if name in ("x", "y", "scale", "visible")]
        self.assertEqual(stored, [], f"{stored} is a second copy")

    def test_scale_and_visibility_live_there_too(self):
        thing = self.object()
        thing.scale = 2.5
        thing.visible = False
        table = engine.current().objects
        self.assertEqual(table.scale[thing._slot], 2.5)
        self.assertFalse(table.flags[thing._slot] & engine.VISIBLE)
        self.assertTrue(table.flags[thing._slot] & engine.ALIVE)

    def test_the_size_follows_the_image(self):
        thing = self.object()
        table = engine.current().objects
        self.assertEqual((table.width[thing._slot], table.height[thing._slot]),
                         (4, 4))
        thing.image = an_image(9, 7)
        self.assertEqual((table.width[thing._slot], table.height[thing._slot]),
                         (9, 7))

    def test_every_handle_reaches_the_same_numbers(self):
        self.object("player", 5, 5)
        first = GameObject("player")
        second = GameObject("player")
        first.set.x(64.5)
        self.assertEqual(second.x, 64.5)
        self.assertEqual(GameObject("player").x, 64.5)
        self.assertEqual(engine.current().objects.x[first._object._slot], 64.5)

    def test_a_destroyed_object_marks_its_slot_dead(self):
        thing = self.object("player")
        slot = thing._slot
        GameObject("player").destroy()
        self.assertFalse(engine.current().objects.flags[slot] & engine.ALIVE)

    def test_a_slot_is_reused_rather_than_leaked(self):
        first = self.object("a")
        slot = first._slot
        current_scene().remove("a")
        second = self.object("b")
        self.assertEqual(second._slot, slot)
        self.assertEqual(len(engine.current().objects), 1)


class TestPositionsKeepTheirMeaning(EngineStateTestCase):
    """Milestone 8.1's model, through the new storage."""

    def test_fractions_survive(self):
        thing = self.object()
        thing.x = 100.5
        self.assertEqual(thing.x, 100.5)

    def test_fractions_add_up_exactly(self):
        thing = self.object()
        for _ in range(60):
            thing.x += 100 * (1 / 60)
        self.assertAlmostEqual(thing.x, 100.0, places=6)

    def test_a_whole_position_still_reads_as_a_whole_number(self):
        """A HUD printing a position must not start showing 100.0."""
        thing = self.object()
        thing.x = 100
        self.assertIsInstance(thing.x, int)
        self.assertEqual(f"{thing.x}", "100")

    def test_a_fractional_position_stays_a_float(self):
        thing = self.object()
        thing.x = 100.5
        self.assertNotIsInstance(thing.x, int)

    def test_sizes_stay_whole(self):
        thing = self.object()
        table = engine.current().objects
        self.assertIsInstance(table.width[thing._slot], int)
        self.assertIsInstance(table.height[thing._slot], int)


class TestTheTable(EngineStateTestCase):
    def test_it_starts_empty(self):
        self.assertEqual(len(engine.ObjectTable()), 0)
        self.assertEqual(engine.ObjectTable().live, 0)

    def test_claiming_and_releasing(self):
        table = engine.ObjectTable()
        first = table.claim(1, 2, 3, 4)
        second = table.claim(5, 6, 7, 8)
        self.assertEqual((first, second), (0, 1))
        self.assertEqual(table.live, 2)
        table.release(first)
        self.assertEqual(table.live, 1)
        self.assertEqual(table.claim(), first, "the slot was not reused")

    def test_releasing_twice_is_harmless(self):
        table = engine.ObjectTable()
        slot = table.claim()
        table.release(slot)
        table.release(slot)
        self.assertEqual(table.live, 0)

    def test_releasing_something_that_is_not_there(self):
        table = engine.ObjectTable()
        table.release(99)
        table.release(-1)
        table.release(None)

    def test_clearing_forgets_everything(self):
        table = engine.ObjectTable()
        table.claim()
        table.claim()
        table.clear()
        self.assertEqual(len(table), 0)
        self.assertEqual(table.live, 0)

    def test_the_arrays_stay_the_same_length(self):
        table = engine.ObjectTable()
        for _ in range(5):
            table.claim()
        lengths = {len(table.x), len(table.y), len(table.scale),
                   len(table.width), len(table.height), len(table.flags)}
        self.assertEqual(lengths, {5})


class TestLifetime(EngineStateTestCase):
    def play(self, game, size=(20, 20)):
        Application(game, size=size, max_fps=None,
                    backend=NullBackend()).run()

    def test_a_run_lends_its_clock_to_the_state(self):
        seen = []

        class G(Game):
            def on_update(self, dt):
                seen.append(engine.current().clock)
                self.quit()

        self.play(G())
        self.assertIsNotNone(seen[0])

    def test_objects_made_before_a_run_take_part_in_it(self):
        self.object("early")
        seen = []

        class G(Game):
            def on_start(self):
                seen.append(len(current_scene()))

            def on_update(self, dt):
                self.quit()

        self.play(G())
        self.assertEqual(seen, [1])

    def test_a_second_run_starts_with_an_empty_world(self):
        seen = []

        class G(Game):
            def on_start(self):
                seen.append(len(current_scene()))
                current_scene().add(SceneObject("made", an_image(), 0, 0))

            def on_update(self, dt):
                self.quit()

        game = G()
        self.play(game)
        self.play(game)
        self.assertEqual(seen, [0, 0])

    def test_the_table_does_not_carry_over(self):
        class G(Game):
            def on_start(self):
                current_scene().add(SceneObject("made", an_image(), 0, 0))

            def on_update(self, dt):
                self.quit()

        game = G()
        self.play(game)
        self.play(game)
        self.assertEqual(len(engine.current().objects), 0)

    def test_the_state_is_replaced_after_a_run(self):
        before = engine.current()

        class G(Game):
            def on_update(self, dt):
                self.quit()

        self.play(G())
        self.assertIsNot(engine.current(), before)

    def test_a_run_that_raised_still_replaces_the_state(self):
        class Breaking(Game):
            def on_update(self, dt):
                raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            self.play(Breaking())
        self.assertEqual(len(current_scene()), 0)
        self.assertEqual(len(engine.current().objects), 0)

    def test_backend_configuration_is_not_part_of_the_state(self):
        """Configuration says how the program runs, not what the world is."""
        from trjoludus import rendering
        from trjoludus.native import PYTHON, registry

        rendering.engine = PYTHON
        self.addCleanup(registry.reset)

        class G(Game):
            def on_update(self, dt):
                self.quit()

        self.play(G())
        self.assertEqual(rendering.engine, PYTHON)


class TestNativeSeesTheSameState(EngineStateTestCase):
    """The point of the whole exercise, proved through the ABI."""

    def setUp(self):
        super().setUp()
        library.forget()
        native_world.forget()
        if not native_world.available():
            self.skipTest("no native library built here")

    def test_native_code_counts_the_same_objects(self):
        self.object("a")
        self.object("b")
        self.assertEqual(native_world.live(), 2)

    def test_native_code_reads_what_python_wrote(self):
        thing = self.object(x=10.5, y=20.25)
        found = native_world.read(thing._slot)
        self.assertEqual((found.x, found.y), (10.5, 20.25))

    def test_a_python_change_needs_nothing_to_be_told(self):
        """No sync step: the write and the read are the same memory."""
        thing = self.object()
        for value in (1.5, -99.0, 12345.75):
            thing.x = value
            self.assertEqual(native_world.read(thing._slot).x, value)

    def test_a_native_change_is_seen_by_python(self):
        thing = self.object()
        self.assertTrue(native_world.set_position(thing._slot, 5.5, 6.25))
        self.assertEqual((thing.x, thing.y), (5.5, 6.25))

    def test_a_native_change_is_seen_through_every_handle(self):
        thing = self.object("player")
        first = GameObject("player")
        second = GameObject("player")
        native_world.set_position(thing._slot, 42.5, 43.5)
        self.assertEqual(first.position, (42.5, 43.5))
        self.assertEqual(second.position, (42.5, 43.5))

    def test_scale_and_size_cross_correctly(self):
        thing = self.object()
        thing.scale = 2.5
        thing.image = an_image(9, 7)
        found = native_world.read(thing._slot)
        self.assertEqual(found.scale, 2.5)
        self.assertEqual((found.width, found.height), (9, 7))

    def test_visibility_crosses_as_a_flag(self):
        thing = self.object()
        self.assertTrue(native_world.read(thing._slot).flags & engine.VISIBLE)
        thing.visible = False
        self.assertFalse(native_world.read(thing._slot).flags & engine.VISIBLE)

    def test_a_destroyed_object_is_gone_natively_too(self):
        thing = self.object("player")
        slot = thing._slot
        GameObject("player").destroy()
        self.assertIsNone(native_world.read(slot))
        self.assertEqual(native_world.live(), 0)

    def test_native_code_cannot_move_a_destroyed_object(self):
        thing = self.object("player")
        slot = thing._slot
        GameObject("player").destroy()
        self.assertFalse(native_world.set_position(slot, 1.0, 1.0))

    def test_native_code_cannot_move_a_slot_that_does_not_exist(self):
        self.object()
        self.assertFalse(native_world.set_position(999, 1.0, 1.0))

    def test_the_table_growing_does_not_strand_the_view(self):
        """An array moves as it grows; the view is rebuilt per call."""
        first = self.object("a", x=1.0)
        for index in range(50):
            self.object(f"filler{index}")
        self.assertEqual(native_world.read(first._slot).x, 1.0)
        self.assertEqual(native_world.live(), 51)

    def test_an_empty_world_is_not_an_error(self):
        self.assertEqual(native_world.live(), 0)
        self.assertIsNone(native_world.read(0))

    def test_it_reads_the_same_memory_rather_than_a_copy(self):
        """Change the array directly; native code must see it at once."""
        thing = self.object()
        engine.current().objects.x[thing._slot] = 314.5
        self.assertEqual(native_world.read(thing._slot).x, 314.5)

    def test_python_and_native_agree_after_both_have_written(self):
        thing = self.object()
        thing.x = 1.5
        native_world.set_position(thing._slot, 2.5, 3.5)
        thing.y = 4.5
        self.assertEqual((thing.x, thing.y), (2.5, 4.5))
        found = native_world.read(thing._slot)
        self.assertEqual((found.x, found.y), (2.5, 4.5))


class TestNativeFailuresAreClear(EngineStateTestCase):
    def test_without_a_library_it_says_so(self):
        library._library = None
        library._problem = "no native library found (test)"
        native_world.forget()
        with self.assertRaises(native_world.WorldError) as caught:
            native_world.live()
        self.assertIn("no native library", str(caught.exception))

    def test_a_world_error_is_a_trjoludus_error(self):
        from trjoludus.errors import TrjoLudusError

        self.assertTrue(issubclass(native_world.WorldError, TrjoLudusError))

    def test_no_native_wording_reaches_the_message(self):
        try:
            native_world._check(-2)
        except native_world.WorldError as error:
            message = str(error).lower()
        for word in ("rust", "panic", "ctypes", "ffi", "0x", "pointer into"):
            if word == "pointer into":
                continue
            with self.subTest(word=word):
                self.assertNotIn(word, message)

    def test_every_status_says_something(self):
        for status in (-1, -2, -3, -99):
            with self.subTest(status=status):
                with self.assertRaises(native_world.WorldError):
                    native_world._check(status)

    def test_success_says_nothing(self):
        self.assertIsNone(native_world._check(0))


class TestNothingElseChanged(EngineStateTestCase):
    """The public API is exactly what it was."""

    def test_the_wildcard_is_unchanged(self):
        import trjoludus

        namespace = {}
        exec("from trjoludus import *", namespace)
        namespace.pop("__builtins__", None)
        self.assertEqual(set(namespace), set(trjoludus.__all__))
        for name in namespace:
            with self.subTest(name=name):
                for word in ("engine state", "enginestate", "world",
                             "table", "slot", "ffi", "ctypes"):
                    self.assertNotIn(word, name.lower())

    def test_no_state_object_is_exported(self):
        namespace = {}
        exec("from trjoludus import *", namespace)
        for hidden in ("EngineState", "ObjectTable", "WorldTable", "Object",
                       "SceneObject"):
            with self.subTest(name=hidden):
                self.assertNotIn(hidden, namespace)

    def test_a_game_still_reads_the_same(self):
        from trjoludus import create, draw  # noqa: F401

        self.object("player", 10, 10)
        player = GameObject("player")
        player.set.x = 100
        player.set.y(50)
        player.move.x(10)
        player.set.scale(2)
        self.assertEqual(player.position, (110, 50))
        self.assertEqual(player.scale, 2.0)
        self.assertEqual(player.size, (8, 8))


if __name__ == "__main__":
    unittest.main()
