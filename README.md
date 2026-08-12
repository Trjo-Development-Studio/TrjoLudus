# TrjoLudus

A lightweight, custom 2D game engine/framework created by **Trjo Development Studio (TDS)**,
written in Python and designed for Windows and Linux.

> **Status: pre-alpha.** Milestone 1 is complete on Linux: `tl.run()` opens a
> **real window**, runs the engine-owned loop with frame timing, delivers
> platform-neutral events and shuts down cleanly. A Windows backend exists but
> is **not yet verified on Windows**. Rendering is not implemented at all.

## Philosophy

- **Built ourselves.** TrjoLudus does not use Pygame, and does not wrap another
  game engine or framework. The OS is accessed directly through `ctypes`.
- **No dependencies.** The engine runs on the Python standard library alone.
- **Incremental.** One subsystem at a time, tested before the next one starts.
- **No premature engineering.** Interfaces are defined when a real feature needs
  them, not in advance.

## Architecture

The public API is kept separate from the internal implementation. Games talk to
a stable surface; everything underneath is free to change.

```
Your game
    |
TrjoLudus public API        <- stable, documented
    |
Engine implementation       <- Python today; possibly Rust/C++ later
    |
Platform layer              <- the only OS-aware code
    |
Windows (Win32)   /   Linux (Xlib initially, native Wayland later)
```

All operating-system knowledge lives in `trjoludus/platform/`. No other module
may import OS libraries or branch on the host platform. This keeps the engine
portable and makes the platform layer the natural first candidate should a
performance-critical rewrite in Rust or C++ ever be needed.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design decisions and the
reasoning behind them.

## Layout

```
trjoludus/
    __init__.py        public API surface
    app.py             application and the engine-owned game loop
    game.py            Game base class
    errors.py          exception hierarchy
    events.py          platform-neutral event types
    clock.py           frame timing
    platform/
        __init__.py    OS detection
        base.py        backend contracts
        null.py        headless backend, for tests and CI
        linux/
            _xlib.py   raw Xlib ctypes declarations
            x11.py     X11 backend
        windows/
            _user32.py raw Win32 ctypes declarations
            win32.py   Win32 backend
examples/              runnable examples
tests/                 stdlib unittest suite
```

## Requirements

Python 3.11 or newer. Nothing else.

## Usage

```python
import trjoludus as tl


class MyGame(tl.Game):
    def on_start(self):
        self.elapsed = 0.0

    def on_event(self, event):
        if isinstance(event, tl.WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        self.elapsed += dt
        if self.elapsed > 1.0:
            self.quit()


tl.run(MyGame(), title="My Game", size=(800, 600))
```

On Linux that opens a real window. The engine owns the loop; a game supplies
callbacks. Closing the window is a *request* -- a game that wants to honour it
calls `quit()`, as above.

TrjoLudus picks the backend for you, so a game never imports anything from
`trjoludus.platform`. A runnable version of the above is in
[`examples/window_test.py`](examples/window_test.py):

```sh
python examples/window_test.py
```

### Running without a window

Set `TRJOLUDUS_BACKEND=null` to run the same game headless -- useful for tests,
CI, and machines with no display:

```sh
TRJOLUDUS_BACKEND=null python examples/window_test.py
```

| Value | Backend |
| --- | --- |
| unset | the platform default (`x11` on Linux, `win32` on Windows) |
| `x11` | real windows through Xlib/Xwayland |
| `win32` | real windows through user32 |
| `null` | headless; no window, no close events |

> **Milestone 1 caveat.** The Windows backend is implemented but has not been
> run on Windows yet -- TrjoLudus is developed on Linux. Treat it as untested
> until someone exercises it on a real Windows machine.

## Learning TrjoLudus

[`examples/`](examples/README.md) is the home of the **Introduction & Tutorial
project** -- how to *use* the engine, as opposed to `tests/`, which verifies
that the engine is *correct*. It grows as engine features land, and currently
holds only the window smoke test above.

## Development

```sh
python -m unittest discover -s tests
```

Tests that need a real window are skipped when there is nothing to open them
on, so it is worth checking the headless path too -- it is what proves the
engine does not quietly depend on a display:

```sh
env -u DISPLAY -u WAYLAND_DISPLAY -u XDG_RUNTIME_DIR -u XDG_SESSION_TYPE \
    python -m unittest discover -s tests
```

That run should report skips. If it reports none, a test found a display it
should not have.

## Roadmap

The initial engine targets 2D only. 3D is explicitly out of scope and may be
considered much later.

| Milestone | Scope | Status |
| --- | --- | --- |
| 0 | Project foundation, platform detection | done |
| 1 | Window creation + game loop | done (Linux; Windows unverified) |
| 2 | Keyboard and mouse input | planned |
| 3 | 2D shape rendering | planned |
| 4 | Images / textures | planned |
| 5 | Text rendering | planned |
| 6 | Animation | planned |
| 7 | Collision | planned |
| 8 | UI | planned |
| 9 | Asset management | planned |
| 10 | Save systems | planned |

## License

MIT
