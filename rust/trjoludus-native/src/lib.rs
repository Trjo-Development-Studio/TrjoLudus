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
//! Three rules hold at this boundary:
//!
//! 1. **Work crosses in bulk.** A native subsystem does a whole frame or a
//!    whole broad-phase pass before returning. Nothing here is called once per
//!    pixel or per entity, because the crossing would cost more than the work.
//! 2. **Nothing calls back into Python.** Data comes in, results go out. A
//!    callback into the interpreter from inside a loop would undo the reason
//!    for the loop being here.
//! 3. **Ownership is explicit.** Buffers are owned by the caller and borrowed
//!    for the length of one call, or owned here and freed by an explicit call.
//!    Nothing is freed by a garbage collector that does not know about it.
//!
//! # What is here now
//!
//! The discovery functions, and nothing else. Milestone 3.0 establishes the
//! architecture; the subsystems move over one at a time afterwards, starting
//! with rendering. There is deliberately no stub implementation of anything:
//! a subsystem that reported itself as implemented while doing nothing would
//! be worse than one that says it is not there.

#![deny(unsafe_op_in_unsafe_fn)]

use std::ffi::CStr;
use std::os::raw::{c_char, c_int};

/// The ABI this library speaks.
///
/// Python refuses a library whose number is not the one it expects, rather
/// than calling a function whose arguments have since moved. Bump it whenever
/// the meaning of any exported function changes.
pub const ABI_VERSION: u32 = 1;

/// The subsystems implemented here.
///
/// Empty, and honestly so. Each name is added in the step that implements it,
/// which is what makes `<system>.engine = "rust"` either work or fail with a
/// clear message rather than silently doing nothing.
///
/// The names are the ones Python uses: `"rendering"`, `"image"`,
/// `"collision"`, `"physics"`, `"ai"`, `"pathfinding"`, `"animation"`,
/// `"audio"`.
pub const IMPLEMENTED: &[&str] = &[];

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

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CString;

    #[test]
    fn abi_version_is_reported() {
        assert_eq!(trjoludus_abi_version(), ABI_VERSION);
    }

    #[test]
    fn nothing_is_implemented_yet() {
        assert!(
            IMPLEMENTED.is_empty(),
            "a subsystem was listed before it was implemented"
        );
    }

    #[test]
    fn an_unimplemented_subsystem_says_so() {
        let name = CString::new("rendering").unwrap();
        assert_eq!(unsafe { trjoludus_implements(name.as_ptr()) }, 0);
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
}
