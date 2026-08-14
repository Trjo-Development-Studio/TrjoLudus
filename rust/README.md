# The TrjoLudus native library

**You do not need this to use TrjoLudus, and you do not need to understand
Rust to write a game with it.** With no library built, every subsystem runs its
Python implementation, which is what happens on a normal install today. This
directory is for people working on the engine.

## What it is

A plain C ABI shared library. TrjoLudus loads it with `ctypes`, the same way it
already loads `libX11` on Linux and `user32` on Windows.

It is deliberately **not** a Python extension module. A `PyO3` extension would
tie each build to one Python version, make the wheel stop being pure Python,
and put the Python C API in the middle of the engine's hot path. A C ABI keeps
the engine installable as pure Python, keeps the library buildable once, and
keeps the boundary something anything with a C FFI could call.

## What you need

The stable Rust toolchain. [rustup](https://rustup.rs) is the usual way:

```sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

Verified against **rustc 1.97.1 / cargo 1.97.1** on Linux. The crate has no
dependencies, so any recent stable toolchain should do.

## Building it

```sh
cd rust
cargo build --release
cargo test
```

Then put the result where TrjoLudus looks for it:

```sh
mkdir -p ../trjoludus/native/lib
cp target/release/libtrjoludus_native.so ../trjoludus/native/lib/    # Linux
# macOS:   target/release/libtrjoludus_native.dylib
# Windows: target/release/trjoludus_native.dll
```

Check that TrjoLudus found it:

```python
from trjoludus.native import library

library.loaded()        # True
library.version()       # 1
library.library_path()  # .../trjoludus/native/lib/libtrjoludus_native.so
library.problem()       # None, or why there is no library
```

## How it gets into a package

You do not have to do the copy above by hand for a release: building a package
does it. `setup.py` runs `cargo build --release`, puts the result in the
package, and tags the wheel for this machine:

```sh
python -m pip wheel . --no-deps -w dist
# trjoludus-0.0.1-py3-none-linux_x86_64.whl
```

With no toolchain it builds a pure-Python wheel instead, which is a complete
engine. `TRJOLUDUS_BUILD_NATIVE=1` requires the toolchain and fails without it;
`=0` skips it.

The build never copies whatever is sitting in `trjoludus/native/lib/`. It
empties that directory in the build tree and puts a freshly compiled file
there, so a build from last week cannot end up in a release. Which is also why
that directory is gitignored: a library there is yours, not the project's.

## What is in it

Right now: the two discovery functions, and nothing else.

```rust
trjoludus_abi_version() -> u32
trjoludus_implements(name: *const c_char) -> c_int
```

`IMPLEMENTED` in `src/lib.rs` is empty, and that is deliberate. Milestone 3.0
built the architecture; the subsystems move across one at a time afterwards,
starting with rendering. A subsystem is added to that list **in the step that
implements it** -- one that claimed to be implemented while doing nothing would
be worse than one that honestly reports itself missing, because
`rendering.engine = "rust"` would then succeed and change nothing.

## The three rules at this boundary

1. **Work crosses in bulk.** A native subsystem does a whole frame, or a whole
   broad-phase pass, before returning. Nothing is called once per pixel or per
   entity: the crossing would cost more than the work.
2. **Nothing calls back into Python.** Data in, results out. A callback into
   the interpreter from inside a loop undoes the reason the loop is here.
3. **Ownership is explicit.** A buffer is either owned by the caller and
   borrowed for one call, or owned here and freed by an explicit call. Nothing
   is freed by a garbage collector that does not know about it.

## The ABI version

`ABI_VERSION` in `src/lib.rs` and `ABI_VERSION` in
`trjoludus/native/library.py` must match. TrjoLudus refuses a library whose
version differs rather than calling functions whose arguments may have moved --
a mismatch is a crash with no explanation otherwise. Bump both whenever the
meaning of an exported function changes.

## Layout

```
rust/
    Cargo.toml                  the workspace
    trjoludus-native/
        Cargo.toml              the one crate
        src/lib.rs              the C ABI, and the list of what is implemented
```

Subsystem implementations get their own modules under `src/` as they arrive, so
that where a native implementation belongs is never a question.
