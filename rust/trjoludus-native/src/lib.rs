//! Native implementations of TrjoLudus subsystems.
//!
//! # What this is
//!
//! TrjoLudus is a Python game-development library that can use a native
//! library, not a Python wrapper around a Rust engine. Everything a game
//! writes is Python, and stays Python whatever is underneath it:
//!
//! ```python
//! player.move.x(100 * time.delta)
//! ```
//!
//! With this library absent, every subsystem runs its Python implementation.
//! With it present, the subsystems listed in [`IMPLEMENTED`] run here instead.
//!
//! # The boundary
//!
//! A plain C ABI, loaded with `ctypes` on the Python side -- the same way
//! TrjoLudus already loads `libX11` and `user32`. No `PyO3`, no Python C API,
//! and no dependency on a particular Python version: the library is built
//! once and any Python that can call C can use it.
//!
//! Four rules hold at this boundary:
//!
//! 1. **Work crosses in bulk.** A native subsystem does a whole frame or a
//!    whole broad-phase pass before returning. Nothing here is called once per
//!    pixel or per entity, because the crossing would cost more than the work.
//! 2. **Nothing calls back into Python.** Data comes in, results go out. A
//!    callback into the interpreter from inside a loop would undo the reason
//!    for the loop being here.
//! 3. **Ownership is explicit.** Every buffer crossing this boundary is owned
//!    by the caller and borrowed for exactly the length of one call. This
//!    library allocates nothing that Python must free, and keeps no pointer
//!    after returning, so there is nothing to leak and nothing to dangle.
//! 4. **No panic escapes.** Every exported function runs its work inside
//!    [`std::panic::catch_unwind`] and returns a status code. A panic
//!    unwinding into C is undefined behaviour; a panic that becomes
//!    [`STATUS_PANIC`] is a Python exception.
//!
//! # Results that vary in length
//!
//! Some work does not know how much it will produce until it has done it: how
//! many pairs collided, how many steps a path took. One convention covers all
//! of it, and it is the ownership rule again rather than an exception to it:
//!
//! ```text
//! Python allocates a buffer  ->  Rust fills what fits  ->  Rust reports how
//!                                                          many there were
//! ```
//!
//! Every such function takes a buffer and its capacity, and a `*mut usize`
//! the true count is written to. Four rules hold:
//!
//! 1. **The count is always written**, whether or not everything fit. It is
//!    what there *was*, not what was stored, so a caller can size a buffer
//!    from it and ask again.
//! 2. **A capacity of zero is a counting pass.** The buffer may be null then,
//!    nothing is written to it, and the status is success rather than
//!    [`STATUS_TOO_SMALL`] -- a caller who offered no room was not trying to
//!    fill any. That is the cheap first half of ask-then-fill, and it costs
//!    one crossing.
//! 3. **Too small is [`STATUS_TOO_SMALL`], not a failure.** The buffer is
//!    filled to its capacity and the count still comes back. Nothing is ever
//!    written past it.
//! 4. **Nothing is allocated here.** There is no result object to free, no
//!    handle to close and no global holding the last answer, so the rules
//!    above are the whole of it.
//!
//! # Rounding lives in Python
//!
//! Every coordinate arriving here is already a whole number, and scaled sizes
//! are already worked out. Python rounds half-to-even; Rust's `f64::round`
//! rounds half-away-from-zero. Rounding on this side would put roughly one
//! position in two hundred on a different pixel from the Python renderer, so
//! the boundary takes integers and the question never arises.

#![deny(unsafe_op_in_unsafe_fn)]

pub mod image;
pub mod render;
pub mod world;

use std::ffi::CStr;
use std::os::raw::{c_char, c_int};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

use world::{Object, World, WorldMut};

/// The ABI this library speaks.
///
/// Python refuses a library whose number is not the one it expects, rather
/// than calling a function whose arguments have since moved. Bump it whenever
/// the meaning of any exported function changes.
pub const ABI_VERSION: u32 = 5;

/// The subsystems implemented here.
///
/// A name appears in this list in the step that implements it. One that
/// claimed to be implemented while doing nothing would make
/// `<system>.engine = "rust"` succeed and change nothing, which is worse than
/// an honest refusal.
///
/// The names are the ones Python uses.
pub const IMPLEMENTED: &[&str] = &["rendering", "image"];

/// The call did what it was asked.
pub const STATUS_OK: c_int = 0;
/// A pointer was null where one was needed.
pub const STATUS_NULL: c_int = -1;
/// A size was not a size, or a buffer was not the length its size implies.
pub const STATUS_BAD_BUFFER: c_int = -2;
/// Something panicked. Contained here; never unwound into C.
pub const STATUS_PANIC: c_int = -3;
/// The slot asked about holds no live object. An answer, not a failure.
pub const STATUS_NO_OBJECT: c_int = -4;
/// The filtered data was shorter than the image's size implies.
pub const STATUS_SHORT_DATA: c_int = -5;
/// A filter byte that is not one of the five PNG defines. Which one is
/// written to the caller's out-parameter, so Python can name it in the
/// message it already raises.
pub const STATUS_BAD_FILTER: c_int = -6;
/// The caller's buffer was too small to hold every result.
///
/// Not a failure so much as a measurement: what would have been written is
/// still counted, and the true count is in the caller's out-parameter, so a
/// caller can size a buffer from the answer and ask again. See the
/// variable-length results convention below.
pub const STATUS_TOO_SMALL: c_int = -7;

/// Returns the ABI version this library was built against.
///
/// The first thing Python calls after loading the library.
#[no_mangle]
pub extern "C" fn trjoludus_abi_version() -> u32 {
    ABI_VERSION
}

/// Returns 1 if this library implements the named subsystem, 0 otherwise.
///
/// # Safety
///
/// `name` must be a valid pointer to a NUL-terminated string, or null. The
/// string belongs to the caller and is only read for the length of this call.
#[no_mangle]
pub unsafe extern "C" fn trjoludus_implements(name: *const c_char) -> c_int {
    if name.is_null() {
        return 0;
    }
    // Safety: the caller promises a NUL-terminated string, per the contract
    // above. Python passes bytes from a str it owns.
    let requested = unsafe { CStr::from_ptr(name) };
    match requested.to_str() {
        Ok(text) => IMPLEMENTED.contains(&text) as c_int,
        // Not valid UTF-8, so it cannot be one of our names.
        Err(_) => 0,
    }
}

/// Run some drawing, turning any panic into a status code.
///
/// `AssertUnwindSafe` is honest here rather than a shrug: the only state the
/// closure touches is the caller's buffer, and a panic part-way through
/// drawing leaves it with some pixels drawn and some not -- which is a frame,
/// not a broken invariant. Nothing here has a data structure that could be
/// left half-updated.
fn guarded(work: impl FnOnce() -> c_int) -> c_int {
    match catch_unwind(AssertUnwindSafe(work)) {
        Ok(status) => status,
        Err(_) => STATUS_PANIC,
    }
}

/// As [`guarded`], for the functions that answer with a count.
fn guarded_i64(work: impl FnOnce() -> i64) -> i64 {
    match catch_unwind(AssertUnwindSafe(work)) {
        Ok(value) => value,
        Err(_) => STATUS_PANIC as i64,
    }
}

/// Borrow the caller's frame buffer, or say why it cannot be borrowed.
///
/// # Safety
///
/// `pixels` must point to `length` writable bytes that stay valid and
/// unaliased for this call.
unsafe fn frame<'a>(
    pixels: *mut u8,
    length: usize,
    width: i64,
    height: i64,
) -> Result<render::Frame<'a>, c_int> {
    if pixels.is_null() {
        return Err(STATUS_NULL);
    }
    // Safety: the caller promises `length` writable bytes for this call.
    let bytes = unsafe { slice::from_raw_parts_mut(pixels, length) };
    render::Frame::new(bytes, width, height).map_err(|_| STATUS_BAD_BUFFER)
}

/// Borrow a read-only buffer the caller owns.
///
/// # Safety
///
/// `data` must point to `length` readable bytes valid for this call.
unsafe fn borrow<'a>(data: *const u8, length: usize) -> Result<&'a [u8], c_int> {
    if data.is_null() {
        return Err(STATUS_NULL);
    }
    // Safety: the caller promises `length` readable bytes for this call.
    Ok(unsafe { slice::from_raw_parts(data, length) })
}

/// Fill a whole frame with one opaque colour.
///
/// # Safety
///
/// `pixels` must point to `length` writable bytes, being `width * height * 4`,
/// valid for this call. Nothing is kept.
#[no_mangle]
pub unsafe extern "C" fn trjoludus_render_clear(
    pixels: *mut u8,
    length: usize,
    width: i64,
    height: i64,
    red: u8,
    green: u8,
    blue: u8,
) -> c_int {
    guarded(|| {
        // Safety: forwarded from this function's own contract.
        match unsafe { frame(pixels, length, width, height) } {
            Ok(mut target) => {
                target.clear(red, green, blue);
                STATUS_OK
            }
            Err(status) => status,
        }
    })
}

/// Set one pixel, ignoring anything outside the frame.
///
/// # Safety
///
/// As [`trjoludus_render_clear`].
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn trjoludus_render_set_pixel(
    pixels: *mut u8,
    length: usize,
    width: i64,
    height: i64,
    x: i64,
    y: i64,
    red: u8,
    green: u8,
    blue: u8,
) -> c_int {
    guarded(|| {
        // Safety: forwarded from this function's own contract.
        match unsafe { frame(pixels, length, width, height) } {
            Ok(mut target) => {
                target.set_pixel(x, y, red, green, blue);
                STATUS_OK
            }
            Err(status) => status,
        }
    })
}

/// Fill a rectangle, clipped to the frame.
///
/// # Safety
///
/// As [`trjoludus_render_clear`].
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn trjoludus_render_fill_rect(
    pixels: *mut u8,
    length: usize,
    width: i64,
    height: i64,
    x: i64,
    y: i64,
    rectangle_width: i64,
    rectangle_height: i64,
    red: u8,
    green: u8,
    blue: u8,
) -> c_int {
    guarded(|| {
        // Safety: forwarded from this function's own contract.
        match unsafe { frame(pixels, length, width, height) } {
            Ok(mut target) => {
                target.fill_rect(
                    x,
                    y,
                    rectangle_width,
                    rectangle_height,
                    red,
                    green,
                    blue,
                );
                STATUS_OK
            }
            Err(status) => status,
        }
    })
}

/// Draw a one-pixel line, ends included.
///
/// # Safety
///
/// As [`trjoludus_render_clear`].
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn trjoludus_render_draw_line(
    pixels: *mut u8,
    length: usize,
    width: i64,
    height: i64,
    x: i64,
    y: i64,
    end_x: i64,
    end_y: i64,
    red: u8,
    green: u8,
    blue: u8,
) -> c_int {
    guarded(|| {
        // Safety: forwarded from this function's own contract.
        match unsafe { frame(pixels, length, width, height) } {
            Ok(mut target) => {
                target.draw_line(x, y, end_x, end_y, red, green, blue);
                STATUS_OK
            }
            Err(status) => status,
        }
    })
}

/// Draw text from glyph columns the caller supplies.
///
/// The font belongs to Python. `columns` is `character_width` bytes per
/// character, each bit one pixel down that column.
///
/// # Safety
///
/// `pixels` as [`trjoludus_render_clear`]. `columns` must point to
/// `column_count` readable bytes valid for this call. Neither is kept.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn trjoludus_render_draw_glyphs(
    pixels: *mut u8,
    length: usize,
    width: i64,
    height: i64,
    columns: *const u8,
    column_count: usize,
    character_width: i64,
    character_height: i64,
    advance: i64,
    x: i64,
    y: i64,
    red: u8,
    green: u8,
    blue: u8,
) -> c_int {
    guarded(|| {
        // Safety: forwarded from this function's own contract.
        let glyphs = match unsafe { borrow(columns, column_count) } {
            Ok(slice) => slice,
            Err(status) => return status,
        };
        // Safety: forwarded from this function's own contract.
        match unsafe { frame(pixels, length, width, height) } {
            Ok(mut target) => {
                target.draw_glyphs(
                    glyphs,
                    character_width,
                    character_height,
                    advance,
                    x,
                    y,
                    red,
                    green,
                    blue,
                );
                STATUS_OK
            }
            Err(status) => status,
        }
    })
}

/// Draw text larger, one call for the whole string.
///
/// Where [`trjoludus_render_draw_glyphs`] lights single pixels, this fills a
/// block per lit pixel, and the caller says how big every block is by handing
/// over the rounded edges rather than a scale. Doing it this way is what
/// makes one call possible: the alternative -- and what Python did before
/// this existed -- is a `fill_rect` per lit pixel, which for a sixteen
/// character label at scale two is 226 crossings of this boundary per frame,
/// and measured slower than not crossing it at all.
///
/// Rounding stays in Python for the reason given at the top of this file.
///
/// # Safety
///
/// As [`trjoludus_render_clear`] for the frame. `columns`, `horizontal` and
/// `vertical` must each address their stated number of readable values for
/// this call. Nothing is kept.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn trjoludus_render_draw_glyphs_scaled(
    pixels: *mut u8,
    length: usize,
    width: i64,
    height: i64,
    columns: *const u8,
    column_count: usize,
    character_width: i64,
    character_height: i64,
    advance: i64,
    horizontal: *const i64,
    horizontal_count: usize,
    vertical: *const i64,
    vertical_count: usize,
    x: i64,
    y: i64,
    red: u8,
    green: u8,
    blue: u8,
) -> c_int {
    guarded(|| {
        // Safety: forwarded from this function's own contract.
        let glyphs = match unsafe { borrow(columns, column_count) } {
            Ok(slice) => slice,
            Err(status) => return status,
        };
        if horizontal.is_null() || vertical.is_null() {
            return STATUS_NULL;
        }
        // Safety: forwarded from this function's own contract.
        let (across, down) = unsafe {
            (
                slice::from_raw_parts(horizontal, horizontal_count),
                slice::from_raw_parts(vertical, vertical_count),
            )
        };
        // Safety: forwarded from this function's own contract.
        match unsafe { frame(pixels, length, width, height) } {
            Ok(mut target) => {
                target.draw_glyphs_scaled(
                    glyphs,
                    character_width,
                    character_height,
                    advance,
                    across,
                    down,
                    x,
                    y,
                    red,
                    green,
                    blue,
                );
                STATUS_OK
            }
            Err(status) => status,
        }
    })
}

/// Composite an image at its own size.
///
/// # Safety
///
/// `pixels` as [`trjoludus_render_clear`]. `source` must point to
/// `source_length` readable bytes, being `source_width * source_height * 4`,
/// valid for this call. Neither is kept.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn trjoludus_render_draw_image(
    pixels: *mut u8,
    length: usize,
    width: i64,
    height: i64,
    source: *const u8,
    source_length: usize,
    source_width: i64,
    source_height: i64,
    opaque: c_int,
    x: i64,
    y: i64,
) -> c_int {
    guarded(|| {
        // Safety: forwarded from this function's own contract.
        let image = match unsafe { borrow(source, source_length) } {
            Ok(slice) => slice,
            Err(status) => return status,
        };
        // Safety: forwarded from this function's own contract.
        match unsafe { frame(pixels, length, width, height) } {
            Ok(mut target) => {
                target.draw_image(
                    image,
                    source_width,
                    source_height,
                    opaque != 0,
                    x,
                    y,
                );
                STATUS_OK
            }
            Err(status) => status,
        }
    })
}

/// Reverse the per-scanline filters of a decompressed PNG.
///
/// The expensive half of decoding. Python has already checked the file's
/// structure and run zlib; this turns the filtered scanlines into pixels.
///
/// `out` must be exactly `width * samples * height` bytes and is written only
/// on success -- an image is not worth half-decoding.
///
/// On [`STATUS_BAD_FILTER`], `bad_filter` receives the offending byte so that
/// Python can raise the message it has always raised. It is untouched
/// otherwise.
///
/// # Safety
///
/// `raw` must address `raw_length` readable bytes and `out` `out_length`
/// writable ones, both valid and unaliased for this call. `bad_filter` must
/// be a valid pointer or null. Nothing is kept.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn trjoludus_image_unfilter(
    raw: *const u8,
    raw_length: usize,
    out: *mut u8,
    out_length: usize,
    width: usize,
    height: usize,
    samples: usize,
    bad_filter: *mut i32,
) -> c_int {
    guarded(|| {
        if raw.is_null() || out.is_null() {
            return STATUS_NULL;
        }
        // Safety: forwarded from this function's own contract.
        let source = unsafe { slice::from_raw_parts(raw, raw_length) };
        // Safety: as above; `out` is writable and does not overlap `raw`.
        let target = unsafe { slice::from_raw_parts_mut(out, out_length) };

        match image::unfilter(source, target, width, height, samples) {
            Ok(()) => STATUS_OK,
            Err(image::ImageError::BadSize) => STATUS_BAD_BUFFER,
            Err(image::ImageError::WrongOutputSize) => STATUS_BAD_BUFFER,
            Err(image::ImageError::NotEnoughData) => STATUS_SHORT_DATA,
            Err(image::ImageError::UnknownFilter(found)) => {
                if !bad_filter.is_null() {
                    // Safety: the caller promises a valid pointer or null.
                    unsafe { *bad_filter = found as i32 };
                }
                STATUS_BAD_FILTER
            }
        }
    })
}

/// Whether every pixel of a BGRA image is fully opaque.
///
/// Writes 1 or 0 to `out`, and only on success.
///
/// # Safety
///
/// `pixels` must address `length` readable bytes valid for this call, and
/// `out` must be a valid pointer. Nothing is kept.
#[no_mangle]
pub unsafe extern "C" fn trjoludus_image_opaque(
    pixels: *const u8,
    length: usize,
    out: *mut c_int,
) -> c_int {
    guarded(|| {
        if out.is_null() || (pixels.is_null() && length != 0) {
            return STATUS_NULL;
        }
        // An empty image has no transparent pixel in it, which is what Python
        // answers too -- `all()` of nothing is true.
        let data: &[u8] = if length == 0 {
            &[]
        } else {
            // Safety: forwarded from this function's own contract.
            unsafe { slice::from_raw_parts(pixels, length) }
        };
        match image::opaque(data) {
            Ok(answer) => {
                // Safety: the caller promises a valid pointer.
                unsafe { *out = answer as c_int };
                STATUS_OK
            }
            Err(_) => STATUS_BAD_BUFFER,
        }
    })
}

/// The engine's object table, as it arrives from Python.
///
/// Six pointers and a count: one array per field, all the same length. Python
/// owns every one of them and they stay valid for the length of one call --
/// the same borrowing rule the renderer's frame buffer follows.
///
/// This is a C struct on purpose. Python builds one with `ctypes` and never
/// learns anything about how Rust arranges the world.
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct WorldTable {
    /// Positions, fractional.
    pub x: *mut f64,
    pub y: *mut f64,
    /// How much bigger than its image each object is drawn.
    pub scale: *const f64,
    /// Image sizes, whole pixels.
    pub width: *const i32,
    pub height: *const i32,
    /// ALIVE and VISIBLE per object.
    pub flags: *const i32,
    /// How many slots each array holds.
    pub count: usize,
}

impl WorldTable {
    /// Whether every pointer is there.
    fn complete(&self) -> bool {
        !self.x.is_null()
            && !self.y.is_null()
            && !self.scale.is_null()
            && !self.width.is_null()
            && !self.height.is_null()
            && !self.flags.is_null()
    }
}

/// Borrow a table for reading.
///
/// # Safety
///
/// Every pointer must address `count` readable values that stay valid and
/// unaliased for this call.
unsafe fn borrow_world<'a>(table: &WorldTable) -> Result<World<'a>, c_int> {
    // An empty world is a world. Python's arrays have no allocation until
    // something is put in them, so their pointers are null while a game has
    // created nothing -- and `from_raw_parts` on null is undefined behaviour
    // even for a length of zero.
    if table.count == 0 {
        return Ok(World {
            x: &[],
            y: &[],
            scale: &[],
            width: &[],
            height: &[],
            flags: &[],
        });
    }
    if !table.complete() {
        return Err(STATUS_NULL);
    }
    // Safety: forwarded from this function's contract.
    let world = unsafe {
        World {
            x: slice::from_raw_parts(table.x, table.count),
            y: slice::from_raw_parts(table.y, table.count),
            scale: slice::from_raw_parts(table.scale, table.count),
            width: slice::from_raw_parts(table.width, table.count),
            height: slice::from_raw_parts(table.height, table.count),
            flags: slice::from_raw_parts(table.flags, table.count),
        }
    };
    if !world.consistent() {
        return Err(STATUS_BAD_BUFFER);
    }
    Ok(world)
}

/// Borrow a table for changing positions.
///
/// # Safety
///
/// As [`borrow_world`], and `x` and `y` must be writable.
unsafe fn borrow_world_mut<'a>(table: &WorldTable) -> Result<WorldMut<'a>, c_int> {
    // As above: an empty table is empty, not broken.
    if table.count == 0 {
        return Ok(WorldMut { x: &mut [], y: &mut [], flags: &[] });
    }
    if !table.complete() {
        return Err(STATUS_NULL);
    }
    // Safety: forwarded from this function's contract.
    let world = unsafe {
        WorldMut {
            x: slice::from_raw_parts_mut(table.x, table.count),
            y: slice::from_raw_parts_mut(table.y, table.count),
            flags: slice::from_raw_parts(table.flags, table.count),
        }
    };
    if !world.consistent() {
        return Err(STATUS_BAD_BUFFER);
    }
    Ok(world)
}

/// How many objects in the table have not been destroyed.
///
/// Returns a negative status on failure, so a caller can tell "no objects"
/// from "that was not a table".
///
/// # Safety
///
/// `table` must point to a valid [`WorldTable`] whose arrays stay valid for
/// this call.
#[no_mangle]
pub unsafe extern "C" fn trjoludus_world_live(table: *const WorldTable) -> i64 {
    guarded_i64(|| {
        if table.is_null() {
            return STATUS_NULL as i64;
        }
        // Safety: forwarded from this function's contract.
        let table = unsafe { &*table };
        // Safety: as above.
        match unsafe { borrow_world(table) } {
            Ok(world) => world.live() as i64,
            Err(status) => status as i64,
        }
    })
}

/// Copy one object's numbers into `out`.
///
/// `out` is the caller's, and is only written when this returns
/// [`STATUS_OK`]. A slot that is empty or out of range is
/// [`STATUS_NO_OBJECT`], which is not an error so much as an answer.
///
/// # Safety
///
/// `table` and `out` must be valid pointers for this call.
#[no_mangle]
pub unsafe extern "C" fn trjoludus_world_read(
    table: *const WorldTable,
    slot: usize,
    out: *mut Object,
) -> c_int {
    guarded(|| {
        if table.is_null() || out.is_null() {
            return STATUS_NULL;
        }
        // Safety: forwarded from this function's contract.
        let table = unsafe { &*table };
        // Safety: as above.
        let world = match unsafe { borrow_world(table) } {
            Ok(world) => world,
            Err(status) => return status,
        };
        match world.get(slot) {
            Some(object) => {
                // Safety: `out` is a valid, writable Object per the contract.
                unsafe { *out = object };
                STATUS_OK
            }
            None => STATUS_NO_OBJECT,
        }
    })
}

/// Copy every live object into the caller's buffer, in one call.
///
/// **The read half of a bulk pass, and the shape a native subsystem should
/// use.** One crossing walks the whole table; the per-object accessors above
/// exist to prove that Python and this library share memory, not to be called
/// in a loop.
///
/// Follows the variable-length results convention at the top of this file:
/// `count` always receives how many live objects there are, a `capacity` of
/// zero is a counting pass and may pass a null `out`, and a buffer too small
/// is [`STATUS_TOO_SMALL`] with as much written as fits.
///
/// # Safety
///
/// `table` must be valid for this call. `out` must address `capacity`
/// writable [`Object`]s, or be null when `capacity` is zero. `count` must be
/// a valid pointer. Nothing is kept.
#[no_mangle]
pub unsafe extern "C" fn trjoludus_world_gather(
    table: *const WorldTable,
    out: *mut Object,
    capacity: usize,
    count: *mut usize,
) -> c_int {
    guarded(|| {
        if table.is_null() || count.is_null() {
            return STATUS_NULL;
        }
        if out.is_null() && capacity != 0 {
            return STATUS_NULL;
        }
        // Safety: forwarded from this function's contract.
        let table = unsafe { &*table };
        // Safety: as above.
        let world = match unsafe { borrow_world(table) } {
            Ok(world) => world,
            Err(status) => return status,
        };
        // Safety: `capacity` writable Objects, or none at all. An empty slice
        // is made without touching `out`, which may be null here.
        let room: &mut [Object] = if capacity == 0 {
            &mut []
        } else {
            unsafe { slice::from_raw_parts_mut(out, capacity) }
        };
        let found = world.gather(room);
        // Safety: `count` is a valid pointer per the contract.
        unsafe { *count = found };
        // Asking for no room is asking for the count, and a count is never
        // too small to hold. Only a caller that offered a buffer can be told
        // it was not big enough -- otherwise the counting half of ask-then-
        // fill would answer with a status its caller has to ignore, and a
        // status you must ignore is worse than no status.
        if capacity != 0 && found > capacity {
            STATUS_TOO_SMALL
        } else {
            STATUS_OK
        }
    })
}

/// Move many objects in one call.
///
/// **The write half of a bulk pass.** `slots`, `xs` and `ys` line up: entry
/// `n` of each is one move. The number that actually moved is written to
/// `moved` -- slots that are out of range or hold nothing are skipped, which
/// is what an object destroyed part-way through a pass looks like.
///
/// Objects are still never created here, and never destroyed. Positions are
/// the only thing this changes, in the caller's own memory, with no copy to
/// write back.
///
/// # Safety
///
/// `table` must be valid for this call. `slots`, `xs` and `ys` must each
/// address `count` readable values, or be null when `count` is zero. `moved`
/// must be a valid pointer. Nothing is kept.
#[no_mangle]
pub unsafe extern "C" fn trjoludus_world_set_positions(
    table: *const WorldTable,
    slots: *const i64,
    xs: *const f64,
    ys: *const f64,
    count: usize,
    moved: *mut usize,
) -> c_int {
    guarded(|| {
        if table.is_null() || moved.is_null() {
            return STATUS_NULL;
        }
        if count != 0 && (slots.is_null() || xs.is_null() || ys.is_null()) {
            return STATUS_NULL;
        }
        // Safety: forwarded from this function's contract.
        let table = unsafe { &*table };
        // Safety: as above.
        let mut world = match unsafe { borrow_world_mut(table) } {
            Ok(world) => world,
            Err(status) => return status,
        };
        if count == 0 {
            // Safety: `moved` is a valid pointer per the contract.
            unsafe { *moved = 0 };
            return STATUS_OK;
        }
        // Safety: `count` readable values in each, per the contract.
        let (which, new_x, new_y) = unsafe {
            (
                slice::from_raw_parts(slots, count),
                slice::from_raw_parts(xs, count),
                slice::from_raw_parts(ys, count),
            )
        };
        let changed = world.set_positions(which, new_x, new_y);
        // Safety: `moved` is a valid pointer per the contract.
        unsafe { *moved = changed };
        STATUS_OK
    })
}

/// Put one object somewhere.
///
/// The one thing native code may change about the world today, and it changes
/// Python's memory directly -- there is no copy to write back. A slot that is
/// empty or out of range is [`STATUS_NO_OBJECT`] and nothing is written.
///
/// # Safety
///
/// `table` must be valid for this call, with writable `x` and `y`.
#[no_mangle]
pub unsafe extern "C" fn trjoludus_world_set_position(
    table: *const WorldTable,
    slot: usize,
    x: f64,
    y: f64,
) -> c_int {
    guarded(|| {
        if table.is_null() {
            return STATUS_NULL;
        }
        // Safety: forwarded from this function's contract.
        let table = unsafe { &*table };
        // Safety: as above.
        let mut world = match unsafe { borrow_world_mut(table) } {
            Ok(world) => world,
            Err(status) => return status,
        };
        if world.set_position(slot, x, y) {
            STATUS_OK
        } else {
            STATUS_NO_OBJECT
        }
    })
}

/// Composite an image at a different size, nearest-neighbour.
///
/// `target_width` and `target_height` are worked out by the caller, because
/// rounding belongs on the Python side.
///
/// # Safety
///
/// As [`trjoludus_render_draw_image`].
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn trjoludus_render_draw_image_scaled(
    pixels: *mut u8,
    length: usize,
    width: i64,
    height: i64,
    source: *const u8,
    source_length: usize,
    source_width: i64,
    source_height: i64,
    x: i64,
    y: i64,
    target_width: i64,
    target_height: i64,
) -> c_int {
    guarded(|| {
        // Safety: forwarded from this function's own contract.
        let image = match unsafe { borrow(source, source_length) } {
            Ok(slice) => slice,
            Err(status) => return status,
        };
        // Safety: forwarded from this function's own contract.
        match unsafe { frame(pixels, length, width, height) } {
            Ok(mut target) => {
                target.draw_image_scaled(
                    image,
                    source_width,
                    source_height,
                    x,
                    y,
                    target_width,
                    target_height,
                );
                STATUS_OK
            }
            Err(status) => status,
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CString;

    #[test]
    fn abi_version_is_reported() {
        assert_eq!(trjoludus_abi_version(), ABI_VERSION);
    }

    #[test]
    fn rendering_is_implemented() {
        let name = CString::new("rendering").unwrap();
        assert_eq!(unsafe { trjoludus_implements(name.as_ptr()) }, 1);
    }

    #[test]
    fn nothing_else_is_implemented_yet() {
        for name in [
            "collision",
            "physics",
            "ai",
            "pathfinding",
            "animation",
            "audio",
        ] {
            let requested = CString::new(name).unwrap();
            assert_eq!(
                unsafe { trjoludus_implements(requested.as_ptr()) },
                0,
                "{name} was claimed but has not been migrated"
            );
        }
    }

    #[test]
    fn a_null_name_is_not_implemented() {
        assert_eq!(unsafe { trjoludus_implements(std::ptr::null()) }, 0);
    }

    #[test]
    fn a_name_we_do_not_know_is_not_implemented() {
        let name = CString::new("teleportation").unwrap();
        assert_eq!(unsafe { trjoludus_implements(name.as_ptr()) }, 0);
    }

    #[test]
    fn a_panic_becomes_a_status_code() {
        assert_eq!(guarded(|| panic!("deliberate")), STATUS_PANIC);
    }

    #[test]
    fn a_null_buffer_is_refused() {
        let status = unsafe {
            trjoludus_render_clear(std::ptr::null_mut(), 16, 2, 2, 0, 0, 0)
        };
        assert_eq!(status, STATUS_NULL);
    }

    #[test]
    fn a_buffer_of_the_wrong_length_is_refused() {
        let mut buffer = vec![0u8; 8];
        let status = unsafe {
            trjoludus_render_clear(buffer.as_mut_ptr(), 8, 4, 4, 0, 0, 0)
        };
        assert_eq!(status, STATUS_BAD_BUFFER);
        assert!(buffer.iter().all(|byte| *byte == 0), "it drew anyway");
    }

    #[test]
    fn a_bad_size_is_refused() {
        let mut buffer = vec![0u8; 16];
        let status = unsafe {
            trjoludus_render_clear(buffer.as_mut_ptr(), 16, 0, 4, 0, 0, 0)
        };
        assert_eq!(status, STATUS_BAD_BUFFER);
    }

    #[test]
    fn a_null_image_is_refused() {
        let mut buffer = vec![0u8; 16];
        let status = unsafe {
            trjoludus_render_draw_image(
                buffer.as_mut_ptr(),
                16,
                2,
                2,
                std::ptr::null(),
                4,
                1,
                1,
                1,
                0,
                0,
            )
        };
        assert_eq!(status, STATUS_NULL);
    }

    #[test]
    fn unfiltering_through_the_abi_works_and_refuses_rubbish() {
        let raw = [0u8, 1, 2, 3, 4, 0, 5, 6, 7, 8];
        let mut out = [0u8; 8];
        let mut bad = -1i32;
        let status = unsafe {
            trjoludus_image_unfilter(
                raw.as_ptr(), raw.len(), out.as_mut_ptr(), out.len(),
                4, 2, 1, &mut bad,
            )
        };
        assert_eq!(status, STATUS_OK);
        assert_eq!(out, [1, 2, 3, 4, 5, 6, 7, 8]);

        // Null pointers.
        assert_eq!(
            unsafe {
                trjoludus_image_unfilter(
                    std::ptr::null(), 10, out.as_mut_ptr(), out.len(),
                    4, 2, 1, std::ptr::null_mut(),
                )
            },
            STATUS_NULL
        );
        // Too little data.
        assert_eq!(
            unsafe {
                trjoludus_image_unfilter(
                    raw.as_ptr(), 3, out.as_mut_ptr(), out.len(),
                    4, 2, 1, std::ptr::null_mut(),
                )
            },
            STATUS_SHORT_DATA
        );
    }

    #[test]
    fn a_bad_filter_reports_which_one() {
        let raw = [9u8, 1, 2, 3, 4, 0, 5, 6, 7, 8];
        let mut out = [0u8; 8];
        let mut bad = -1i32;
        let status = unsafe {
            trjoludus_image_unfilter(
                raw.as_ptr(), raw.len(), out.as_mut_ptr(), out.len(),
                4, 2, 1, &mut bad,
            )
        };
        assert_eq!(status, STATUS_BAD_FILTER);
        assert_eq!(bad, 9);
        assert_eq!(out, [0; 8], "it wrote despite refusing");
    }

    #[test]
    fn a_null_bad_filter_pointer_is_allowed() {
        let raw = [9u8, 1, 2, 3, 4, 0, 5, 6, 7, 8];
        let mut out = [0u8; 8];
        assert_eq!(
            unsafe {
                trjoludus_image_unfilter(
                    raw.as_ptr(), raw.len(), out.as_mut_ptr(), out.len(),
                    4, 2, 1, std::ptr::null_mut(),
                )
            },
            STATUS_BAD_FILTER
        );
    }

    #[test]
    fn opacity_through_the_abi() {
        let mut answer = -1;
        let opaque = [1u8, 2, 3, 255];
        assert_eq!(
            unsafe { trjoludus_image_opaque(opaque.as_ptr(), 4, &mut answer) },
            STATUS_OK
        );
        assert_eq!(answer, 1);

        let clear = [1u8, 2, 3, 0];
        assert_eq!(
            unsafe { trjoludus_image_opaque(clear.as_ptr(), 4, &mut answer) },
            STATUS_OK
        );
        assert_eq!(answer, 0);

        // Empty is opaque, as `all()` of nothing is true.
        assert_eq!(
            unsafe { trjoludus_image_opaque(std::ptr::null(), 0, &mut answer) },
            STATUS_OK
        );
        assert_eq!(answer, 1);

        // Not a whole number of pixels.
        assert_eq!(
            unsafe { trjoludus_image_opaque(opaque.as_ptr(), 3, &mut answer) },
            STATUS_BAD_BUFFER
        );
        // Nowhere to put the answer.
        assert_eq!(
            unsafe {
                trjoludus_image_opaque(opaque.as_ptr(), 4, std::ptr::null_mut())
            },
            STATUS_NULL
        );
    }

    #[test]
    fn image_is_implemented() {
        let name = CString::new("image").unwrap();
        assert_eq!(unsafe { trjoludus_implements(name.as_ptr()) }, 1);
    }

    #[test]
    fn an_empty_world_is_not_an_error() {
        // Every pointer null, count zero: what Python hands over before a
        // game has created anything.
        let table = WorldTable {
            x: std::ptr::null_mut(),
            y: std::ptr::null_mut(),
            scale: std::ptr::null(),
            width: std::ptr::null(),
            height: std::ptr::null(),
            flags: std::ptr::null(),
            count: 0,
        };
        assert_eq!(unsafe { trjoludus_world_live(&table) }, 0);
        let mut found = Object {
            x: 0.0,
            y: 0.0,
            scale: 0.0,
            width: 0,
            height: 0,
            flags: 0,
            slot: 0,
        };
        assert_eq!(
            unsafe { trjoludus_world_read(&table, 0, &mut found) },
            STATUS_NO_OBJECT
        );
        assert_eq!(
            unsafe { trjoludus_world_set_position(&table, 0, 1.0, 1.0) },
            STATUS_NO_OBJECT
        );
    }

    #[test]
    fn a_null_world_table_is_refused() {
        assert_eq!(
            unsafe { trjoludus_world_live(std::ptr::null()) },
            STATUS_NULL as i64
        );
        assert_eq!(
            unsafe {
                trjoludus_world_read(std::ptr::null(), 0, std::ptr::null_mut())
            },
            STATUS_NULL
        );
    }

    #[test]
    fn a_partly_null_table_with_objects_is_refused() {
        let values = [1.0f64, 2.0];
        let table = WorldTable {
            x: values.as_ptr() as *mut f64,
            y: std::ptr::null_mut(),
            scale: std::ptr::null(),
            width: std::ptr::null(),
            height: std::ptr::null(),
            flags: std::ptr::null(),
            count: 2,
        };
        assert_eq!(
            unsafe { trjoludus_world_live(&table) },
            STATUS_NULL as i64
        );
    }

    /// The arrays behind a world, kept alive while a `WorldTable` points at
    /// them. A struct rather than a tuple so the fields have their names.
    struct Arrays {
        x: Vec<f64>,
        y: Vec<f64>,
        scale: Vec<f64>,
        width: Vec<i32>,
        height: Vec<i32>,
        flags: Vec<i32>,
    }

    impl Arrays {
        /// Three objects, the last of them destroyed.
        fn three() -> Self {
            Arrays {
                x: vec![1.5, 2.5, 3.5],
                y: vec![10.5, 20.5, 30.5],
                scale: vec![1.0, 1.0, 1.0],
                width: vec![8, 8, 8],
                height: vec![8, 8, 8],
                flags: vec![world::ALIVE, world::ALIVE, 0],
            }
        }

        /// As many live objects as asked for, all at the origin.
        fn many(count: usize) -> Self {
            Arrays {
                x: vec![0.0; count],
                y: vec![0.0; count],
                scale: vec![1.0; count],
                width: vec![8; count],
                height: vec![8; count],
                flags: vec![world::ALIVE; count],
            }
        }

        fn table(&mut self) -> WorldTable {
            WorldTable {
                x: self.x.as_mut_ptr(),
                y: self.y.as_mut_ptr(),
                scale: self.scale.as_ptr(),
                width: self.width.as_ptr(),
                height: self.height.as_ptr(),
                flags: self.flags.as_ptr(),
                count: self.x.len(),
            }
        }
    }

    fn nowhere() -> Object {
        Object { x: 0.0, y: 0.0, scale: 0.0, width: 0, height: 0, flags: 0, slot: -1 }
    }

    // --- the variable-length results convention -------------------------

    #[test]
    fn gathering_with_no_room_is_a_counting_pass() {
        let mut parts = Arrays::three();
        let table = parts.table();
        let mut count = 0usize;
        let status = unsafe {
            trjoludus_world_gather(&table, std::ptr::null_mut(), 0, &mut count)
        };
        assert_eq!(status, STATUS_OK, "counting is not a failure");
        assert_eq!(count, 2);
    }

    #[test]
    fn gathering_one_result() {
        let mut parts = Arrays::three();
        parts.flags[1] = 0;
        let table = parts.table();
        let mut out = [nowhere(); 4];
        let mut count = 0usize;
        let status =
            unsafe { trjoludus_world_gather(&table, out.as_mut_ptr(), 4, &mut count) };
        assert_eq!((status, count), (STATUS_OK, 1));
        assert_eq!(out[0].x, 1.5);
        assert_eq!(out[1].slot, -1, "wrote past the one result");
    }

    #[test]
    fn gathering_many_results() {
        let mut parts = Arrays::three();
        parts.flags[2] = world::ALIVE;
        let table = parts.table();
        let mut out = [nowhere(); 4];
        let mut count = 0usize;
        let status =
            unsafe { trjoludus_world_gather(&table, out.as_mut_ptr(), 4, &mut count) };
        assert_eq!((status, count), (STATUS_OK, 3));
        assert_eq!([out[0].slot, out[1].slot, out[2].slot], [0, 1, 2]);
    }

    #[test]
    fn gathering_into_exactly_enough_room_fits() {
        let mut parts = Arrays::three();
        let table = parts.table();
        let mut out = [nowhere(); 2];
        let mut count = 0usize;
        let status =
            unsafe { trjoludus_world_gather(&table, out.as_mut_ptr(), 2, &mut count) };
        assert_eq!(status, STATUS_OK, "an exact fit is not too small");
        assert_eq!(count, 2);
        assert_eq!(out[1].x, 2.5);
    }

    #[test]
    fn gathering_into_too_little_room_says_so_and_still_counts() {
        let mut parts = Arrays::three();
        let table = parts.table();
        let mut out = [nowhere(); 1];
        let mut count = 0usize;
        let status =
            unsafe { trjoludus_world_gather(&table, out.as_mut_ptr(), 1, &mut count) };
        assert_eq!(status, STATUS_TOO_SMALL);
        assert_eq!(count, 2, "the true count must survive a short buffer");
        assert_eq!(out[0].x, 1.5, "what fitted should still be there");
    }

    #[test]
    fn gathering_from_an_empty_world_finds_nothing() {
        let table = WorldTable {
            x: std::ptr::null_mut(),
            y: std::ptr::null_mut(),
            scale: std::ptr::null(),
            width: std::ptr::null(),
            height: std::ptr::null(),
            flags: std::ptr::null(),
            count: 0,
        };
        let mut out = [nowhere(); 2];
        let mut count = 9usize;
        let status =
            unsafe { trjoludus_world_gather(&table, out.as_mut_ptr(), 2, &mut count) };
        assert_eq!((status, count), (STATUS_OK, 0));
    }

    #[test]
    fn gathering_refuses_null_arguments() {
        let mut parts = Arrays::three();
        let table = parts.table();
        let mut count = 0usize;
        assert_eq!(
            unsafe {
                trjoludus_world_gather(std::ptr::null(), std::ptr::null_mut(), 0, &mut count)
            },
            STATUS_NULL
        );
        assert_eq!(
            unsafe {
                trjoludus_world_gather(&table, std::ptr::null_mut(), 0, std::ptr::null_mut())
            },
            STATUS_NULL,
            "there was nowhere to report the count"
        );
        assert_eq!(
            unsafe { trjoludus_world_gather(&table, std::ptr::null_mut(), 5, &mut count) },
            STATUS_NULL,
            "claimed room in a buffer that is not there"
        );
    }

    // --- bulk writing ----------------------------------------------------

    #[test]
    fn a_bulk_write_moves_many_and_reports_how_many() {
        let mut parts = Arrays::three();
        let table = parts.table();
        let slots = [0i64, 1];
        let xs = [100.25f64, 200.25];
        let ys = [300.5f64, 400.5];
        let mut moved = 0usize;
        let status = unsafe {
            trjoludus_world_set_positions(
                &table, slots.as_ptr(), xs.as_ptr(), ys.as_ptr(), 2, &mut moved)
        };
        assert_eq!((status, moved), (STATUS_OK, 2));
        assert_eq!(parts.x[0], 100.25, "the caller's own memory should have changed");
        assert_eq!(parts.y[1], 400.5);
    }

    #[test]
    fn a_bulk_write_skips_slots_holding_nothing() {
        let mut parts = Arrays::three();
        let table = parts.table();
        let slots = [0i64, 2, 99, -1];
        let values = [7.0f64; 4];
        let mut moved = 0usize;
        let status = unsafe {
            trjoludus_world_set_positions(
                &table, slots.as_ptr(), values.as_ptr(), values.as_ptr(), 4, &mut moved)
        };
        assert_eq!((status, moved), (STATUS_OK, 1));
        assert_eq!(parts.x[2], 3.5, "a destroyed object was moved");
    }

    #[test]
    fn a_bulk_write_of_nothing_is_not_a_failure() {
        let mut parts = Arrays::three();
        let table = parts.table();
        let mut moved = 9usize;
        let status = unsafe {
            trjoludus_world_set_positions(
                &table, std::ptr::null(), std::ptr::null(), std::ptr::null(), 0, &mut moved)
        };
        assert_eq!((status, moved), (STATUS_OK, 0));
    }

    #[test]
    fn a_bulk_write_refuses_null_arguments() {
        let mut parts = Arrays::three();
        let table = parts.table();
        let slots = [0i64];
        let values = [1.0f64];
        let mut moved = 0usize;
        assert_eq!(
            unsafe {
                trjoludus_world_set_positions(
                    &table, std::ptr::null(), values.as_ptr(), values.as_ptr(), 1, &mut moved)
            },
            STATUS_NULL
        );
        assert_eq!(
            unsafe {
                trjoludus_world_set_positions(
                    &table, slots.as_ptr(), values.as_ptr(), values.as_ptr(), 1,
                    std::ptr::null_mut())
            },
            STATUS_NULL
        );
        assert_eq!(
            unsafe {
                trjoludus_world_set_positions(
                    std::ptr::null(), slots.as_ptr(), values.as_ptr(), values.as_ptr(), 1,
                    &mut moved)
            },
            STATUS_NULL
        );
    }

    #[test]
    fn one_bulk_call_handles_a_large_table() {
        let count = 4000usize;
        let mut parts = Arrays::many(count);
        let table = parts.table();
        let slots: Vec<i64> = (0..count as i64).collect();
        let xs: Vec<f64> = (0..count).map(|n| n as f64 + 0.5).collect();
        let mut moved = 0usize;
        let status = unsafe {
            trjoludus_world_set_positions(
                &table, slots.as_ptr(), xs.as_ptr(), xs.as_ptr(), count, &mut moved)
        };
        assert_eq!((status, moved), (STATUS_OK, count));
        assert_eq!(parts.x[count - 1], count as f64 - 0.5);

        let mut out = vec![nowhere(); count];
        let mut found = 0usize;
        let status =
            unsafe { trjoludus_world_gather(&table, out.as_mut_ptr(), count, &mut found) };
        assert_eq!((status, found), (STATUS_OK, count));
        assert_eq!(out[count - 1].x, count as f64 - 0.5);
    }

    // --- scaled glyphs ---------------------------------------------------

    #[test]
    fn scaled_glyphs_fill_a_block_per_lit_pixel() {
        let mut buffer = vec![0u8; 8 * 8 * 4];
        // One column, one lit bit at row 0, scaled two-fold.
        let across = [0i64, 2];
        let down = [0i64, 2];
        let status = unsafe {
            trjoludus_render_draw_glyphs_scaled(
                buffer.as_mut_ptr(), buffer.len(), 8, 8,
                [1u8].as_ptr(), 1, 1, 1, 1,
                across.as_ptr(), 2, down.as_ptr(), 2,
                0, 0, 250, 0, 0)
        };
        assert_eq!(status, STATUS_OK);
        for (x, y) in [(0, 0), (1, 0), (0, 1), (1, 1)] {
            let at = (y * 8 + x) * 4;
            assert_eq!(&buffer[at..at + 4], &[0, 0, 250, 255], "block pixel {x},{y}");
        }
        assert_eq!(&buffer[2 * 4..3 * 4], &[0, 0, 0, 0], "the block was too wide");
    }

    #[test]
    fn scaled_glyphs_refuse_null_edge_tables() {
        let mut buffer = vec![0u8; 16];
        let edges = [0i64, 1];
        assert_eq!(
            unsafe {
                trjoludus_render_draw_glyphs_scaled(
                    buffer.as_mut_ptr(), 16, 2, 2, [1u8].as_ptr(), 1, 1, 1, 1,
                    std::ptr::null(), 0, edges.as_ptr(), 2, 0, 0, 1, 2, 3)
            },
            STATUS_NULL
        );
        assert_eq!(
            unsafe {
                trjoludus_render_draw_glyphs_scaled(
                    buffer.as_mut_ptr(), 16, 2, 2, [1u8].as_ptr(), 1, 1, 1, 1,
                    edges.as_ptr(), 2, std::ptr::null(), 0, 0, 0, 1, 2, 3)
            },
            STATUS_NULL
        );
    }

    #[test]
    fn scaled_glyphs_stop_where_the_edge_table_stops() {
        let mut buffer = vec![0u8; 8 * 8 * 4];
        // Two columns lit, but only enough edges for the first.
        let across = [0i64, 1];
        let down = [0i64, 1];
        let status = unsafe {
            trjoludus_render_draw_glyphs_scaled(
                buffer.as_mut_ptr(), buffer.len(), 8, 8,
                [1u8, 1u8].as_ptr(), 2, 1, 1, 1,
                across.as_ptr(), 2, down.as_ptr(), 2,
                0, 0, 250, 0, 0)
        };
        assert_eq!(status, STATUS_OK, "a short table is not a crash");
        assert_eq!(&buffer[0..4], &[0, 0, 250, 255]);
        assert_eq!(&buffer[4..8], &[0, 0, 0, 0], "drew past its edge table");
    }

    #[test]
    fn a_good_call_reports_success_and_draws() {
        let mut buffer = vec![0u8; 16];
        let status = unsafe {
            trjoludus_render_clear(buffer.as_mut_ptr(), 16, 2, 2, 10, 20, 30)
        };
        assert_eq!(status, STATUS_OK);
        assert_eq!(&buffer[0..4], &[30, 20, 10, 255]);
    }
}
