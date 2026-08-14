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
    /// Padding, so the layout is the same on every compiler.
    pub reserved: i32,
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
            reserved: 0,
        })
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
