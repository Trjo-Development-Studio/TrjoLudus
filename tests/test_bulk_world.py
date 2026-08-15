"""A native subsystem reads and writes the world a whole pass at a time.

These are about the *shape* of the boundary, not about any subsystem: nothing
here is collision or physics. What they establish is that one crossing can
carry a whole pass, that it works on the same memory Python is holding rather
than a copy of it, and that a result whose size is not known in advance has one
convention instead of one per subsystem.

They skip when there is no native library. That is the one thing that cannot
be arranged: a boundary needs both sides.
"""

import unittest
from array import array

from trjoludus import engine
from trjoludus.native import library
from trjoludus.native import world as native_world


class BulkTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        library.forget()
        native_world.forget()
        if not native_world.available():
            raise unittest.SkipTest(
                "no native library built here; run cargo build")

    def setUp(self):
        engine.end_run()
        library.forget()
        native_world.forget()
        self.addCleanup(native_world.forget)
        self.addCleanup(library.forget)
        self.addCleanup(engine.end_run)

    def world(self, count, dead=()):
        """A table with ``count`` objects, some of them destroyed."""
        table = engine.current().objects
        for index in range(count):
            table.claim(index + 0.5, index + 0.25, 8, 8)
        for slot in dead:
            table.release(slot)
        return table


class TestGatheringTheWholeWorld(BulkTestCase):
    def test_it_finds_every_live_object_in_one_call(self):
        table = self.world(5)
        objects, count = native_world.gather(table=table)
        self.assertEqual(count, 5)
        self.assertEqual([o.x for o in objects[:count]],
                         [0.5, 1.5, 2.5, 3.5, 4.5])

    def test_it_skips_the_destroyed(self):
        table = self.world(5, dead=(1, 3))
        objects, count = native_world.gather(table=table)
        self.assertEqual(count, 3)
        self.assertEqual([o.slot for o in objects[:count]], [0, 2, 4])

    def test_each_object_keeps_its_slot(self):
        table = self.world(4, dead=(0,))
        objects, count = native_world.gather(table=table)
        for found in objects[:count]:
            self.assertEqual(found.x, table.x[found.slot])
            self.assertEqual(found.y, table.y[found.slot])

    def test_an_empty_world_gathers_nothing(self):
        objects, count = native_world.gather(table=self.world(0))
        self.assertEqual(count, 0)
        self.assertEqual(len(objects), 0)

    def test_a_world_of_one(self):
        objects, count = native_world.gather(table=self.world(1))
        self.assertEqual(count, 1)
        self.assertEqual(objects[0].x, 0.5)

    def test_a_large_world(self):
        table = self.world(2000)
        objects, count = native_world.gather(table=table)
        self.assertEqual(count, 2000)
        self.assertEqual(objects[1999].x, 1999.5)
        self.assertEqual(objects[1999].slot, 1999)

    def test_fractions_survive_the_crossing(self):
        table = self.world(1)
        table.x[0] = 100.0625
        objects, _ = native_world.gather(table=table)
        self.assertEqual(objects[0].x, 100.0625)

    def test_sizes_and_flags_come_across_too(self):
        table = self.world(1)
        objects, _ = native_world.gather(table=table)
        self.assertEqual((objects[0].width, objects[0].height), (8, 8))
        self.assertTrue(objects[0].flags & engine.ALIVE)


class TestTheVariableLengthConvention(BulkTestCase):
    """Python allocates, native fills what fits, native says how many."""

    def buffer(self, capacity):
        return (native_world.Object * capacity)()

    def test_no_buffer_at_all_is_a_counting_pass(self):
        table = self.world(7, dead=(2,))
        _, count = native_world.gather(self.buffer(0), table=table)
        self.assertEqual(count, 6)

    def test_a_counting_pass_is_not_an_error(self):
        table = self.world(3)
        # It must not raise, and must not report the buffer as too small: a
        # caller who offered no room was not trying to fill any.
        _, count = native_world.gather(self.buffer(0), table=table)
        self.assertEqual(count, 3)

    def test_zero_results(self):
        room = self.buffer(4)
        _, count = native_world.gather(room, table=self.world(0))
        self.assertEqual(count, 0)

    def test_one_result(self):
        room = self.buffer(4)
        _, count = native_world.gather(room, table=self.world(1))
        self.assertEqual(count, 1)
        self.assertEqual(room[0].slot, 0)

    def test_many_results(self):
        room = self.buffer(100)
        _, count = native_world.gather(room, table=self.world(100))
        self.assertEqual(count, 100)
        self.assertEqual(room[99].slot, 99)

    def test_a_buffer_filled_exactly(self):
        room = self.buffer(3)
        _, count = native_world.gather(room, table=self.world(3))
        self.assertEqual(count, 3, "an exact fit must not read as too small")
        self.assertEqual(room[2].x, 2.5)

    def test_a_buffer_too_small_still_says_how_many_there_were(self):
        room = self.buffer(2)
        _, count = native_world.gather(room, table=self.world(10))
        self.assertEqual(count, 10, "the true count is what makes retry work")

    def test_a_buffer_too_small_is_filled_and_not_overrun(self):
        room = self.buffer(2)
        native_world.gather(room, table=self.world(10))
        self.assertEqual([room[0].slot, room[1].slot], [0, 1])
        self.assertEqual(len(room), 2)

    def test_asking_again_with_the_count_works(self):
        """The convention's whole point: ask, allocate, ask again."""
        table = self.world(9, dead=(4,))
        _, needed = native_world.gather(self.buffer(0), table=table)
        room = self.buffer(needed)
        _, count = native_world.gather(room, table=table)
        self.assertEqual((needed, count), (8, 8))
        self.assertEqual(room[7].slot, 8)

    def test_allocating_for_the_caller_does_the_same_thing(self):
        table = self.world(6, dead=(0, 5))
        objects, count = native_world.gather(table=table)
        self.assertEqual(count, 4)
        self.assertEqual(len(objects), 4)


class TestMovingTheWholeWorld(BulkTestCase):
    def test_one_call_moves_many(self):
        table = self.world(4)
        moved = native_world.set_positions(
            array("q", [0, 1, 2, 3]),
            array("d", [10.5, 11.5, 12.5, 13.5]),
            array("d", [20.5, 21.5, 22.5, 23.5]), table=table)
        self.assertEqual(moved, 4)
        self.assertEqual(list(table.x), [10.5, 11.5, 12.5, 13.5])
        self.assertEqual(list(table.y), [20.5, 21.5, 22.5, 23.5])

    def test_it_writes_the_memory_python_is_holding(self):
        """Not a copy handed back: the very arrays."""
        table = self.world(2)
        before = table.x.buffer_info()[0]
        native_world.set_positions([0], [99.25], [88.75], table=table)
        self.assertEqual(table.x.buffer_info()[0], before,
                         "the array was replaced rather than written")
        self.assertEqual(table.x[0], 99.25)

    def test_a_scene_object_sees_the_move(self):
        """Through the whole stack, not just the table."""
        from trjoludus.image import Image
        from trjoludus.scene import SceneObject, current_scene

        picture = Image(4, 4, bytes([0, 0, 250, 255]) * 16)
        thing = current_scene().add(SceneObject("player", picture, 0, 0))
        native_world.set_positions([thing._slot], [42.5], [43.25])
        self.assertEqual((thing.x, thing.y), (42.5, 43.25))

    def test_plain_sequences_work_as_well_as_arrays(self):
        table = self.world(2)
        moved = native_world.set_positions([0, 1], [1.0, 2.0], [3.0, 4.0],
                                           table=table)
        self.assertEqual(moved, 2)
        self.assertEqual(list(table.x), [1.0, 2.0])

    def test_moving_nothing_is_not_a_failure(self):
        table = self.world(3)
        self.assertEqual(
            native_world.set_positions([], [], [], table=table), 0)
        self.assertEqual(table.x[0], 0.5, "nothing should have moved")

    def test_a_destroyed_object_is_skipped_rather_than_refused(self):
        table = self.world(3, dead=(1,))
        moved = native_world.set_positions([0, 1, 2], [7.0] * 3, [7.0] * 3,
                                           table=table)
        self.assertEqual(moved, 2, "the whole pass failed over one dead slot")
        self.assertEqual(table.x[1], 1.5, "a destroyed object was moved")

    def test_a_slot_that_is_not_there_is_skipped(self):
        table = self.world(2)
        moved = native_world.set_positions([0, 999, -1], [5.0] * 3, [5.0] * 3,
                                           table=table)
        self.assertEqual(moved, 1)

    def test_arrays_that_do_not_line_up_are_refused(self):
        table = self.world(3)
        with self.assertRaises(native_world.WorldError) as caught:
            native_world.set_positions([0, 1, 2], [1.0], [1.0], table=table)
        self.assertIn("one of each", str(caught.exception))

    def test_a_large_pass(self):
        count = 2000
        table = self.world(count)
        moved = native_world.set_positions(
            array("q", range(count)),
            array("d", [n * 1.5 for n in range(count)]),
            array("d", [n * 2.5 for n in range(count)]), table=table)
        self.assertEqual(moved, count)
        self.assertEqual(table.x[count - 1], (count - 1) * 1.5)
        self.assertEqual(table.y[count - 1], (count - 1) * 2.5)

    def test_moving_into_an_empty_world_moves_nothing(self):
        table = self.world(0)
        self.assertEqual(
            native_world.set_positions([0], [1.0], [1.0], table=table), 0)


class TestOneAuthoritativeCopyStillHolds(BulkTestCase):
    """The reason the bulk shape exists is not to break the shared identity."""

    def test_a_bulk_write_is_seen_by_a_bulk_read(self):
        table = self.world(3)
        native_world.set_positions([0, 1, 2], [9.5] * 3, [8.5] * 3,
                                   table=table)
        objects, count = native_world.gather(table=table)
        self.assertEqual(count, 3)
        self.assertEqual([o.x for o in objects], [9.5] * 3)

    def test_a_python_write_is_seen_by_a_bulk_read(self):
        table = self.world(2)
        table.x[1] = 77.125
        objects, _ = native_world.gather(table=table)
        self.assertEqual(objects[1].x, 77.125)

    def test_a_bulk_write_is_seen_by_python(self):
        table = self.world(2)
        native_world.set_positions([1], [66.375], [55.125], table=table)
        self.assertEqual((table.x[1], table.y[1]), (66.375, 55.125))

    def test_growing_the_table_between_passes_is_safe(self):
        """An array reallocates as it grows; a stale pointer would be found
        here rather than as a corrupted position."""
        table = self.world(2)
        _, first = native_world.gather(table=table)
        for index in range(500):
            table.claim(index, index, 4, 4)
        _, second = native_world.gather(table=table)
        self.assertEqual((first, second), (2, 502))
        self.assertEqual(native_world.live(table), 502)

    def test_native_creates_no_objects(self):
        table = self.world(2)
        native_world.set_positions([0, 99], [1.0, 1.0], [1.0, 1.0],
                                   table=table)
        self.assertEqual(len(table), 2, "the table grew from the native side")

    def test_native_destroys_no_objects(self):
        table = self.world(3)
        native_world.set_positions([0, 1, 2], [1.0] * 3, [1.0] * 3,
                                   table=table)
        self.assertEqual(native_world.live(table), 3)


class TestTheBoundaryIsCrossedOncePerPass(BulkTestCase):
    """Not a timing test: a count of crossings."""

    def crossings(self, work):
        """How many times the native side was called."""
        functions = native_world._functions()
        counted = {"calls": 0}
        original = dict(functions)

        def wrap(name):
            def counting(*arguments):
                counted["calls"] += 1
                return original[name](*arguments)
            return counting

        for name in original:
            functions[name] = wrap(name)
        try:
            work()
        finally:
            functions.update(original)
        return counted["calls"]

    def test_gathering_a_thousand_objects_crosses_once(self):
        table = self.world(1000)
        room = (native_world.Object * 1000)()
        self.assertEqual(
            self.crossings(lambda: native_world.gather(room, table=table)), 1)

    def test_moving_a_thousand_objects_crosses_once(self):
        table = self.world(1000)
        slots = array("q", range(1000))
        values = array("d", [1.0] * 1000)
        self.assertEqual(
            self.crossings(
                lambda: native_world.set_positions(slots, values, values,
                                                   table=table)), 1)

    def test_gathering_without_a_buffer_costs_two(self):
        """A count, then a fill. Still not one per object."""
        table = self.world(1000)
        self.assertEqual(
            self.crossings(lambda: native_world.gather(table=table)), 2)

    def test_the_per_object_calls_are_still_one_each(self):
        """What the bulk shape exists to replace, stated as a fact."""
        table = self.world(50)

        def one_at_a_time():
            for slot in range(50):
                native_world.read(slot, table)

        self.assertEqual(self.crossings(one_at_a_time), 50)


if __name__ == "__main__":
    unittest.main()
