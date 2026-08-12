# TrjoLudus

A lightweight, custom 2D game engine/framework created by **Trjo Development Studio (TDS)**,
written in Python and designed for Windows and Linux.

> **Status: pre-alpha.** On Linux, `run()` opens a **real window**, draws
> named image objects into it, moves them, destroys them, and waits for
> keyboard input. A Windows backend exists but is **not yet verified on
> Windows**. Mouse, sound, collision and animation are not implemented yet.

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
    create.py          creating persistent game objects
    keyboard.py        waiting for key presses
    input.py           what wait() can wait for
    scene.py           named game objects and the scene holding them
    image.py           images, and PNG decoding
    render.py          the frame buffer objects are composited into
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
from trjoludus import Game, GameObject, WindowCloseRequested, create, run


class MyGame(Game):
    def on_start(self):
        create.image(100, 100, "player.png", "player")
        self.player = GameObject("player")

    def on_event(self, event):
        if isinstance(event, WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        self.player.move.x(1)


run(MyGame(), title="My Game", size=(800, 600))
```

Import the names you use and then use them directly -- no prefix on every
call. `import trjoludus` on its own would only bind the name `trjoludus`,
because that is what an `import` statement does; naming what you want is how
Python brings the names themselves into a file.

`create.image` creates something that *stays*: call it once, and the engine draws
it every frame. Coordinates are pixels from the top-left corner of the window,
and they position the image's top-left corner.

On Linux that opens a real window. The engine owns the loop; a game supplies
callbacks. Closing the window is a *request* -- a game that wants to honour it
calls `quit()`, as above. TrjoLudus picks the backend for you, so a game never
imports anything from `trjoludus.platform`. Runnable versions of all of this
live in [`examples/`](examples/README.md):

```sh
python examples/image_test.py
python examples/keyboard_test.py
```

### Keyboard input

```python
from trjoludus import input, key, keyboard

keyboard.wait(input.key)

print(key)          # W

if key == "W":
    player.move.y(-50)
if key == "S":
    player.move.y(50)
```

`wait` does not give you a value to store: it waits for a key press and updates
`key`. Each press answers exactly one `wait`, so calling it twice waits twice --
it never repeats the last key. Nothing else happens while waiting; no frame is
drawn until a key arrives.

Key names are uppercase and the same on every platform: `"W"` … `"Z"`, `"0"` …
`"9"`, `"ESCAPE"`, `"ENTER"`, `"SPACE"`, `"UP"`, `"DOWN"`, `"LEFT"`, `"RIGHT"`.
Keys outside that list are ignored rather than reported under a guessed name.

> `key` is a live value, not a string. It compares, prints and formats like the
> key name, which covers ordinary use. To keep a copy that will not change with
> the next press, use `str(key)` or `key.value`.
>
> `from trjoludus import input` shadows Python's built-in `input()` in that
> file. If a file needs both, import `trjoludus.input` under another name.

See [`examples/keyboard_test.py`](examples/keyboard_test.py).

### Removing an object

```python
player.destroy()
```

The object stops being drawn and its name is free again. Every handle to it
stops working, so nothing can go on moving something that no longer exists --
using one says so rather than failing quietly. Destroying twice is an error.

### Placing and moving objects

There are two ways to change where an object is, and they mean different
things:

```python
player.x = 250       # put it exactly there
player.move.x(50)    # and now 50 pixels further right
```

Assigning `x` or `y` sets an **absolute** position. `move.x` and `move.y`
change it **relative** to wherever the object is now, so calls add up: two
`move.x(50)` calls move it 100 pixels in total. Negative values move left and
up. Nothing is clamped -- an object may be moved off screen.

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
that the engine is *correct*. It grows as engine features land.

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
