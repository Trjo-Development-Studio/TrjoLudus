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

Discovery, and the renderer.

```rust
trjoludus_abi_version() -> u32
trjoludus_implements(name: *const c_char) -> c_int

trjoludus_render_clear(...)
trjoludus_render_set_pixel(...)
trjoludus_render_fill_rect(...)
trjoludus_render_draw_line(...)
trjoludus_render_draw_glyphs(...)
trjoludus_render_draw_image(...)
trjoludus_render_draw_image_scaled(...)
```

`IMPLEMENTED` in `src/lib.rs` lists `"rendering"` and nothing else. A subsystem
is added to that list **in the step that implements it** -- one claiming to be
implemented while doing nothing would make `<system>.engine = "rust"` succeed
and change nothing, which is worse than an honest refusal.

Plus the engine's objects:

```rust
trjoludus_world_live(table) -> i64
trjoludus_world_read(table, slot, out) -> i32
trjoludus_world_set_position(table, slot, x, y) -> i32
```

The drawing is in `src/render.rs` and the object view in `src/world.rs`,
neither with any FFI or `unsafe` in it. `src/lib.rs` is the C wrapper: it
borrows the caller's buffers, contains any panic, and returns a status code.

### The world is borrowed, never owned

`WorldTable` is six pointers and a count -- one array per field, all Python's.
Nothing here keeps a copy of the game world, so there is no second world to
drift out of step with the first. A native subsystem reads the same doubles
Python wrote, and `set_position` writes the same ones back, in place.

Native code may move an object. It may not create or destroy one: that is a
decision about what the world contains, and it stays in Python.

### Every drawing function looks like this

```text
(buffer, length, width, height, ...arguments..., colour) -> status
```

* **The buffer belongs to the caller.** It is borrowed for exactly one call and
  never kept. Nothing here allocates anything Python has to free, so there is
  no ownership to get wrong and nothing to leak.
* **Coordinates are already whole numbers.** Python rounds, because Python
  rounds half to even and Rust rounds half away from zero, and a renderer that
  disagreed with the other one about which pixel is "the" pixel would be
  half-right in a way nobody could see.
* **Sizes are already worked out.** A scaled image arrives with its target size
  computed, for the same reason.
* **A status other than 0 becomes a Python exception.** A failed frame must not
  look like a drawn one.

### Panics

Every exported function wraps its work in `catch_unwind`. A panic becomes
`STATUS_PANIC` and then a `RenderingError` in Python -- it never unwinds into
C, which would be undefined behaviour. This is why the release profile does
*not* set `panic = "abort"`: aborting would turn a drawing bug into a dead
process with no traceback.

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
