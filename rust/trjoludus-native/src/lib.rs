//! Native implementations of TrjoLudus subsystems.
//!
//! # What this is
//!
//! TrjoLudus is a Python game engine that can use a native library, not a
//! Python wrapper around a Rust engine. Everything a game writes is Python,
//! and stays Python whatever is underneath it:
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
//! # Rounding lives in Python
//!
//! Every coordinate arriving here is already a whole number, and scaled sizes
//! are already worked out. Python rounds half-to-even; Rust's `f64::round`
//! rounds half-away-from-zero. Rounding on this side would put roughly one
//! position in two hundred on a different pixel from the Python renderer, so
//! the boundary takes integers and the question never arises.

#![deny(unsafe_op_in_unsafe_fn)]

pub mod render;

use std::ffi::CStr;
use std::os::raw::{c_char, c_int};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

/// The ABI this library speaks.
///
/// Python refuses a library whose number is not the one it expects, rather
/// than calling a function whose arguments have since moved. Bump it whenever
/// the meaning of any exported function changes.
pub const ABI_VERSION: u32 = 2;

/// The subsystems implemented here.
///
/// A name appears in this list in the step that implements it. One that
/// claimed to be implemented while doing nothing would make
/// `<system>.engine = "rust"` succeed and change nothing, which is worse than
/// an honest refusal.
///
/// The names are the ones Python uses.
pub const IMPLEMENTED: &[&str] = &["rendering"];

/// The call did what it was asked.
pub const STATUS_OK: c_int = 0;
/// A pointer was null where one was needed.
pub const STATUS_NULL: c_int = -1;
/// A size was not a size, or a buffer was not the length its size implies.
pub const STATUS_BAD_BUFFER: c_int = -2;
/// Something panicked. Contained here; never unwound into C.
pub const STATUS_PANIC: c_int = -3;

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
            "image",
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
    fn a_good_call_reports_success_and_draws() {
        let mut buffer = vec![0u8; 16];
        let status = unsafe {
            trjoludus_render_clear(buffer.as_mut_ptr(), 16, 2, 2, 10, 20, 30)
        };
        assert_eq!(status, STATUS_OK);
        assert_eq!(&buffer[0..4], &[30, 20, 10, 255]);
    }
}
