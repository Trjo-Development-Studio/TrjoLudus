//! Reading and changing the engine's objects, without owning any of them.
//!
//! # Nothing here holds state
//!
//! Python owns the object table. A [`World`] is a borrowed view of it, made
//! at the start of one call and gone at the end. There is no Rust-side copy
//! of the game world to keep in step, because keeping two copies in step is
//! the bug this design exists to make impossible.
//!
//! That means a native subsystem -- rendering today, collision or physics
//! later -- reads *the same doubles* Python wrote. Not a snapshot taken this
//! frame, not a mirror updated on change. The same memory.
//!
//! # Struct of arrays
//!
//! One array per field rather than one record per object. A pass that only
//! wants positions touches a contiguous run of doubles instead of striding
//! over sizes and flags it does not care about.
//!
//! # Borrowing
//!
//! [`World`] borrows immutably and [`WorldMut`] mutably, so Rust's own rules
//! stop a subsystem from reading a field while another writes it. The only
//! `unsafe` is where the pointers arrive from C, and it is confined to
//! [`crate`].

/// Bit set while an object is in the scene.
pub const ALIVE: i32 = 1;

/// Bit set while an object should be drawn.
pub const VISIBLE: i32 = 2;

/// What one object is, to a native subsystem.
///
/// A copy of one object's numbers, made to hand back across the ABI. Cheap,
/// and explicitly a copy: the caller owns it and changing it changes nothing.
#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Object {
    /// Distance from the left edge. Fractional.
    pub x: f64,
    /// Distance from the top edge. Fractional.
    pub y: f64,
    /// How much bigger than its image the object is drawn.
    pub scale: f64,
    /// The image's width in whole pixels.
    pub width: i32,
    /// The image's height in whole pixels.
    pub height: i32,
    /// [`ALIVE`] and [`VISIBLE`].
    pub flags: i32,
    /// Which slot this came from.
    ///
    /// A gathered object has to keep its identity or nothing can be said
    /// about it afterwards: a collision pass reports *which* objects touched,
    /// and a caller writing a result back needs the slot to write it to. It
    /// also pads the struct to a size every compiler agrees on, which is what
    /// this field was before it carried anything.
    pub slot: i32,
}

/// A read-only view of the engine's objects.
pub struct World<'a> {
    pub x: &'a [f64],
    pub y: &'a [f64],
    pub scale: &'a [f64],
    pub width: &'a [i32],
    pub height: &'a [i32],
    pub flags: &'a [i32],
}

/// A view that may change positions.
///
/// Separate from [`World`] so that a subsystem which only reads cannot write
/// by accident, and so the borrow checker enforces it rather than a comment.
pub struct WorldMut<'a> {
    pub x: &'a mut [f64],
    pub y: &'a mut [f64],
    pub flags: &'a [i32],
}

impl<'a> World<'a> {
    /// How many slots there are, alive or not.
    pub fn len(&self) -> usize {
        self.x.len()
    }

    /// Whether there are no slots at all.
    pub fn is_empty(&self) -> bool {
        self.x.is_empty()
    }

    /// How many slots hold an object that has not been destroyed.
    pub fn live(&self) -> usize {
        self.flags.iter().filter(|flags| *flags & ALIVE != 0).count()
    }

    /// Whether a slot holds an object that has not been destroyed.
    pub fn alive(&self, slot: usize) -> bool {
        self.flags.get(slot).is_some_and(|flags| flags & ALIVE != 0)
    }

    /// One object's numbers, or `None` if the slot is empty or out of range.
    pub fn get(&self, slot: usize) -> Option<Object> {
        if !self.alive(slot) {
            return None;
        }
        Some(Object {
            x: self.x[slot],
            y: self.y[slot],
            scale: self.scale[slot],
            width: self.width[slot],
            height: self.height[slot],
            flags: self.flags[slot],
            slot: slot as i32,
        })
    }

    /// Copy every live object into the caller's buffer, in one pass.
    ///
    /// **This is the shape a native subsystem is meant to use.** One call
    /// walks the whole table, rather than a call per object: the crossing is
    /// paid once for the pass instead of once for each thing in it.
    ///
    /// Returns how many live objects there **are**, which is not always how
    /// many were written. A buffer too small to hold them is filled to its
    /// capacity and the true count comes back anyway, so a caller can size a
    /// buffer and ask again without having to guess. Nothing is written past
    /// `out.len()`, and a zero-length buffer is a count and nothing else.
    pub fn gather(&self, out: &mut [Object]) -> usize {
        let mut found = 0;
        for slot in 0..self.len() {
            if self.flags[slot] & ALIVE == 0 {
                continue;
            }
            if let Some(place) = out.get_mut(found) {
                *place = Object {
                    x: self.x[slot],
                    y: self.y[slot],
                    scale: self.scale[slot],
                    width: self.width[slot],
                    height: self.height[slot],
                    flags: self.flags[slot],
                    slot: slot as i32,
                };
            }
            found += 1;
        }
        found
    }

    /// Whether every array is the same length.
    ///
    /// Checked once when the view is made, because everything else indexes
    /// all six with the same number.
    pub fn consistent(&self) -> bool {
        let count = self.x.len();
        self.y.len() == count
            && self.scale.len() == count
            && self.width.len() == count
            && self.height.len() == count
            && self.flags.len() == count
    }
}

impl<'a> WorldMut<'a> {
    /// Put one object somewhere, if the slot holds a live object.
    ///
    /// Returns whether anything was changed. Refusing a dead or missing slot
    /// rather than growing the table is deliberate: creating objects belongs
    /// to Python, and a native subsystem that could conjure them would be a
    /// second place where the world is decided.
    pub fn set_position(&mut self, slot: usize, x: f64, y: f64) -> bool {
        if !self.flags.get(slot).is_some_and(|f| f & ALIVE != 0) {
            return false;
        }
        self.x[slot] = x;
        self.y[slot] = y;
        true
    }

    /// Move many objects in one pass.
    ///
    /// **The counterpart of [`World::gather`], and the shape a native
    /// subsystem is meant to write with.** A physics step works out where
    /// everything goes and says so once, rather than crossing the boundary
    /// per body.
    ///
    /// `slots`, `xs` and `ys` line up: entry `n` of each describes one move.
    /// Returns how many actually moved. A slot that is out of range or holds
    /// no live object is skipped rather than refused -- an object destroyed
    /// part-way through a pass is an ordinary thing to happen, not a failure
    /// of the pass -- and creating one is still not possible from here.
    ///
    /// Nothing is written unless all three arrays are at least as long as
    /// `slots`, because a short one would mean pairing a slot with somebody
    /// else's number.
    pub fn set_positions(&mut self, slots: &[i64], xs: &[f64], ys: &[f64]) -> usize {
        if xs.len() < slots.len() || ys.len() < slots.len() {
            return 0;
        }
        let mut moved = 0;
        for (index, &slot) in slots.iter().enumerate() {
            if slot < 0 {
                continue;
            }
            let slot = slot as usize;
            if !self.flags.get(slot).is_some_and(|f| f & ALIVE != 0) {
                continue;
            }
            self.x[slot] = xs[index];
            self.y[slot] = ys[index];
            moved += 1;
        }
        moved
    }

    /// Whether every array is the same length.
    pub fn consistent(&self) -> bool {
        self.x.len() == self.y.len() && self.x.len() == self.flags.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Table {
        x: Vec<f64>,
        y: Vec<f64>,
        scale: Vec<f64>,
        width: Vec<i32>,
        height: Vec<i32>,
        flags: Vec<i32>,
    }

    fn table() -> Table {
        Table {
            x: vec![1.5, 20.0, 300.25],
            y: vec![2.5, 30.0, 400.75],
            scale: vec![1.0, 2.0, 0.5],
            width: vec![8, 16, 32],
            height: vec![8, 16, 32],
            flags: vec![ALIVE | VISIBLE, ALIVE, 0],
        }
    }

    fn view(table: &Table) -> World<'_> {
        World {
            x: &table.x,
            y: &table.y,
            scale: &table.scale,
            width: &table.width,
            height: &table.height,
            flags: &table.flags,
        }
    }

    #[test]
    fn it_counts_slots_and_live_objects() {
        let table = table();
        let world = view(&table);
        assert_eq!(world.len(), 3);
        assert_eq!(world.live(), 2);
        assert!(!world.is_empty());
    }

    #[test]
    fn it_reads_an_object() {
        let table = table();
        let found = view(&table).get(0).unwrap();
        assert_eq!(found.x, 1.5);
        assert_eq!(found.y, 2.5);
        assert_eq!(found.width, 8);
        assert_eq!(found.flags, ALIVE | VISIBLE);
    }

    #[test]
    fn a_dead_slot_reads_as_nothing() {
        let table = table();
        assert!(view(&table).get(2).is_none());
        assert!(!view(&table).alive(2));
    }

    #[test]
    fn a_slot_that_is_not_there_reads_as_nothing() {
        let table = table();
        assert!(view(&table).get(99).is_none());
        assert!(!view(&table).alive(99));
    }

    #[test]
    fn fractional_positions_survive_the_crossing() {
        let table = table();
        assert_eq!(view(&table).get(2 - 1).unwrap().x, 20.0);
        assert_eq!(table.x[2], 300.25);
    }

    fn empty() -> [Object; 4] {
        [Object { x: 0.0, y: 0.0, scale: 0.0, width: 0, height: 0, flags: 0, slot: -1 }; 4]
    }

    #[test]
    fn gather_takes_every_live_object_in_one_pass() {
        let table = table();
        let mut out = empty();
        // Three slots, one of them dead.
        assert_eq!(view(&table).gather(&mut out), 2);
        assert_eq!(out[0].x, 1.5);
        assert_eq!(out[1].x, 20.0);
        assert_eq!(out[2].slot, -1, "wrote past the live objects");
    }

    #[test]
    fn gather_keeps_each_object_s_slot() {
        let mut table = table();
        table.flags[2] = ALIVE;
        let mut out = empty();
        assert_eq!(view(&table).gather(&mut out), 3);
        assert_eq!([out[0].slot, out[1].slot, out[2].slot], [0, 1, 2]);
    }

    #[test]
    fn gather_skips_the_dead_and_keeps_the_slots_of_the_rest() {
        let mut table = table();
        table.flags[0] = 0;
        let mut out = empty();
        assert_eq!(view(&table).gather(&mut out), 1);
        assert_eq!(out[0].slot, 1, "the surviving object lost its identity");
    }

    #[test]
    fn gather_into_nothing_still_counts() {
        let table = table();
        assert_eq!(view(&table).gather(&mut []), 2);
    }

    #[test]
    fn gather_into_too_little_room_fills_it_and_counts_the_rest() {
        let table = table();
        let mut out = [empty()[0]; 1];
        assert_eq!(view(&table).gather(&mut out), 2, "the true count was lost");
        assert_eq!(out[0].x, 1.5);
    }

    #[test]
    fn gather_from_an_empty_world_finds_nothing() {
        let table = Table { x: vec![], y: vec![], scale: vec![], width: vec![],
                            height: vec![], flags: vec![] };
        let mut out = empty();
        assert_eq!(view(&table).gather(&mut out), 0);
    }

    #[test]
    fn set_positions_moves_many_at_once() {
        let mut table = table();
        let moved = {
            let mut world = WorldMut { x: &mut table.x, y: &mut table.y,
                                       flags: &table.flags };
            world.set_positions(&[0, 1], &[10.5, 11.5], &[20.5, 21.5])
        };
        assert_eq!(moved, 2);
        assert_eq!((table.x[0], table.y[0]), (10.5, 20.5));
        assert_eq!((table.x[1], table.y[1]), (11.5, 21.5));
    }

    #[test]
    fn set_positions_skips_the_dead_and_the_missing() {
        let mut table = table();
        let moved = {
            let mut world = WorldMut { x: &mut table.x, y: &mut table.y,
                                       flags: &table.flags };
            // Slot 2 is dead, 99 is not there, -1 is not a slot at all.
            world.set_positions(&[0, 2, 99, -1], &[9.0; 4], &[9.0; 4])
        };
        assert_eq!(moved, 1);
        assert_eq!(table.x[0], 9.0);
        assert_eq!(table.x[2], 300.25, "a dead slot was written");
    }

    #[test]
    fn set_positions_moving_nothing_is_not_a_failure() {
        let mut table = table();
        let mut world = WorldMut { x: &mut table.x, y: &mut table.y,
                                   flags: &table.flags };
        assert_eq!(world.set_positions(&[], &[], &[]), 0);
    }

    #[test]
    fn set_positions_refuses_arrays_that_do_not_line_up() {
        let mut table = table();
        let moved = {
            let mut world = WorldMut { x: &mut table.x, y: &mut table.y,
                                       flags: &table.flags };
            world.set_positions(&[0, 1], &[5.0], &[5.0, 6.0])
        };
        assert_eq!(moved, 0, "a slot was paired with somebody else's number");
        assert_eq!(table.x[0], 1.5, "nothing should have been written");
    }

    #[test]
    fn a_bulk_write_changes_the_caller_s_own_memory() {
        let mut table = table();
        {
            let mut world = WorldMut { x: &mut table.x, y: &mut table.y,
                                       flags: &table.flags };
            world.set_positions(&[1], &[77.25], &[88.75]);
        }
        // Read back through a fresh view: one authoritative copy, not two.
        assert_eq!(view(&table).get(1).unwrap().x, 77.25);
        assert_eq!(table.y[1], 88.75);
    }

    #[test]
    fn a_bulk_pass_over_a_large_table_stays_exact() {
        let count = 5000;
        let mut table = Table {
            x: (0..count).map(|n| n as f64 + 0.25).collect(),
            y: (0..count).map(|n| n as f64 + 0.75).collect(),
            scale: vec![1.0; count],
            width: vec![8; count],
            height: vec![8; count],
            flags: vec![ALIVE; count],
        };
        let slots: Vec<i64> = (0..count as i64).collect();
        let xs: Vec<f64> = slots.iter().map(|n| *n as f64 * 2.5).collect();
        let moved = {
            let mut world = WorldMut { x: &mut table.x, y: &mut table.y,
                                       flags: &table.flags };
            world.set_positions(&slots, &xs, &xs)
        };
        assert_eq!(moved, count);
        assert_eq!(table.x[count - 1], (count as f64 - 1.0) * 2.5);
        let mut out = vec![empty()[0]; count];
        assert_eq!(view(&table).gather(&mut out), count);
        assert_eq!(out[count - 1].slot, count as i32 - 1);
    }

    #[test]
    fn a_ragged_view_is_not_consistent() {
        let mut table = table();
        table.y.pop();
        assert!(!view(&table).consistent());
    }

    #[test]
    fn writing_a_position_changes_the_caller_s_memory() {
        let mut table = table();
        {
            let mut world = WorldMut {
                x: &mut table.x,
                y: &mut table.y,
                flags: &table.flags,
            };
            assert!(world.set_position(1, 44.5, 55.5));
        }
        assert_eq!(table.x[1], 44.5);
        assert_eq!(table.y[1], 55.5);
    }

    #[test]
    fn a_dead_slot_cannot_be_moved() {
        let mut table = table();
        let mut world = WorldMut {
            x: &mut table.x,
            y: &mut table.y,
            flags: &table.flags,
        };
        assert!(!world.set_position(2, 1.0, 1.0));
    }

    #[test]
    fn a_missing_slot_cannot_be_moved() {
        let mut table = table();
        let mut world = WorldMut {
            x: &mut table.x,
            y: &mut table.y,
            flags: &table.flags,
        };
        assert!(!world.set_position(99, 1.0, 1.0));
    }
}
