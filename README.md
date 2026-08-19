# TrjoLudus

TrjoLudus is a Python game-development library for building 2D games entirely
through code, created by **Trjo Development Studio (TDS)** and designed for
Windows and Linux.

It is not a traditional game engine: there is no editor, no scene file, no
project format and nothing to click. What it gives you is the systems a game
needs -- a window, a loop, objects, drawing, input, timing, animation -- as
Python you write, with the native implementation details kept out of the way.

> **Status: pre-alpha.** On Linux, `run()` opens a **real window**, draws named
> image objects into it, moves and destroys them, draws lines, rectangles and
> text, changes any of it while the game runs, plays named animations, and
> reads the keyboard and mouse -- including which drawing the pointer is over
> and which one was clicked. Rendering and PNG decoding have native
> implementations; everything runs in Python without them. Verified on
> Linux/X11. A Windows backend exists but is **not verified on Windows**.
> Objects can be asked whether they are overlapping. Sound, physics, saving
> and public multi-window support are not implemented.

## Philosophy

- **Built ourselves.** TrjoLudus does not use Pygame, and does not wrap another
  engine or framework. The OS is accessed directly through `ctypes`.
- **No dependencies.** It runs on the Python standard library alone.
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
Subsystem implementation    <- Python, or Rust where measurement asked for it
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
    draw.py            drawing the user interface
    color.py           named colours
    ui.py              drawing lists and the interactive drawings in them
    font.py            the built-in text font
    keyboard.py        waiting for key presses
    time.py            waiting, frame delta and frame rate
    animation.py       named frame sequences and how they play
    collision.py       whether two objects overlap
    objects.py         questions a game asks about its objects
    rendering.py       the rendering subsystem's backend choice
    collision.py       ) subsystems with no implementation yet: each exists
    physics.py         ) so that its backend can be chosen before the code
    ai.py              ) that implements it is written
    pathfinding.py     )
    audio.py           )
    native/            the boundary to the native library
        registry.py    which implementation each subsystem uses
        library.py     finding and loading the native library
        lib/           a built native library goes here, if there is one
    mouse.py           pointer position, buttons and clicks
    input.py           what the waiting calls can wait for, and input.wait()
    scene.py           named game objects and the scene holding them
    image.py           images, and PNG decoding
    rendering_python.pythe frame buffer objects are composited into
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

**To make games with TrjoLudus:** Python 3.11 or newer. Nothing else. There is
no Rust to install and nothing to compile -- a released wheel already contains
whatever native code it needs.

**To work on TrjoLudus itself:** Python 3.11+, and the Rust toolchain if you
are touching the native side. See [Development](#development).

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
python examples/mouse_test.py
python examples/ui_test.py
python examples/button_test.py
```

### Drawing a user interface

```python
from trjoludus import color, draw

draw.rect(0, 0, 480, 24, color.blue)
draw.text(8, 9, "Score: 0", color.white)
draw.line(0, 24, 479, 24, color.white)
```

Like `create.image`, **what you draw stays drawn**: the engine remembers it and
draws it every frame, so draw your interface once when the game starts rather
than again on every update. `draw.clear()` throws it away.

A colour is a `(red, green, blue)` tuple, so the named ones and your own both
work: `color.black`, `color.white`, `color.red`, `color.green`, `color.blue`,
`color.yellow`, `color.cyan`, `color.magenta`, `color.gray` -- or
`(128, 40, 200)`.

For a whole screen you want to switch on and off, give it a name:

```python
start_menu = draw.list("start_menu")
start_menu.rect(150, 90, 180, 90, color.gray)
start_menu.text(170, 110, "PAUSED", color.white)

start_menu.hide()
start_menu.show()
```

A list keeps what it holds until you `clear()` or `destroy()` it, and lists are
drawn in the order they were made. Reusing a name is an error rather than a
silent replacement. UI is drawn on top of the game's objects.

### Buttons that react

Every drawing call hands back the thing it drew, which you can scale and ask
about the mouse:

```python
play_button = menu.rect(160, 120, 160, 60, color.gray)

if play_button.mouse.hover():
    play_button.set.scale(1.1)
else:
    play_button.set.scale(1.0)

if play_button.mouse.clicked():
    start_game()
```

`hover()` is true while the pointer is inside; `clicked()` is true for the one
frame a button went down on it, so **holding the mouse down does not keep
firing**. Both account for scale, and both are false while the drawing or its
list is hidden.

Where drawings overlap, the one **drawn last** gets the interaction -- the one
you can actually see. A drawing only answers to the mouse in its own window.

Scale grows a drawing from its top-left corner, so scaling never moves the
corner you placed. `set.scale(2)`, `add.scale(0.25)` and `remove.scale(0.25)`
are the three ways to change it.

### Changing a drawing

Nothing is repainted every frame. A drawing is made once and then changed in
place, and the next frame shows it:

```python
score = hud.text(10, 10, "Score: 0", color.white)

score.set.text(f"Score: {points}")
score.set.color(color.yellow)
score.move.x(4)
```

`set` gives an exact value, `move` nudges by an amount, and `add` / `remove`
change a value relative to what it is now. Only the properties that mean
something for a drawing are there, so asking a rectangle for its text says so
rather than doing nothing:

| Drawing | `set.text` | `set.color` | `set.x` / `set.y` | `set.scale` | `add`/`remove.scale` | `move.x` / `move.y` |
| --- | --- | --- | --- | --- | --- | --- |
| Text | yes | yes | yes | yes | yes | yes |
| Rectangle | no | yes | yes | yes | yes | yes |
| Line | no | yes | yes | yes | yes | yes |

Position works the same way everywhere:

```python
button.set.x(200)     # exactly 200 pixels from the left
button.move.x(25)     # and now 25 pixels further right
```

`set.x` and `set.y` place a drawing **absolutely**; `move.x` and `move.y`
change it **relative** to where it is now, so calls add up. There is no
`add.x` or `remove.x` -- relative movement already has a word, and it is
`move`. Setting a line's position moves the whole line, so it keeps the shape
it was drawn with.

Positions may be fractional here too. `drawing.x` is the exact value and
`drawing.screen_position` is the pixel it lands on -- the same rounding the
hitbox uses, so the two cannot disagree.

Changes show up in what the mouse finds as well as in what is drawn: there is
one copy of a drawing's position and size, and drawing and hit-testing both
read it. A button that has moved, grown or changed its words is hovered and
clicked where it is now.

See [`examples/button_test.py`](examples/button_test.py).

Text uses a small built-in font, so it needs no font files: printable ASCII at
5x7 pixels per character. See [`examples/ui_test.py`](examples/ui_test.py).

### Keyboard input

There are two different questions, and it is worth knowing which you are
asking. **Is a key held down right now?**

```python
from trjoludus import keyboard, time

if keyboard.button.pressed("W"):
    player.animation.play("walk", fps=12)
    player.move.y(-100 * time.delta)
else:
    player.set.image("idle.png")
```

`pressed()` is **held state**. It is true from the moment the key goes down
until it comes back up, on every frame in between -- not "was it pressed this
frame". Reading it consumes nothing, so ask about as many keys as you like, as
often as you like:

```python
if keyboard.button.pressed("W"):
    player.move.y(-100 * time.delta)
if keyboard.button.pressed("D"):
    player.move.x(100 * time.delta)
```

Both can be true at once, and letting go of one does not affect the other.
`keyboard.button.released("W")` is the exact opposite -- also state, so it is
true for a key nobody has touched, not only for one just let go of.

**Or: wait until a key arrives.**

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

`wait` is **blocking event input**; `pressed()` is **held state**. They do not
interfere: a press read by `wait` still counts as held, and asking what is held
never takes a press away from a wait.

Key names are uppercase and the same on every platform, and the same names work
for both: `"W"` … `"Z"`, `"0"` … `"9"`, `"ESCAPE"`, `"ENTER"`, `"SPACE"`,
`"UP"`, `"DOWN"`, `"LEFT"`, `"RIGHT"`. Keys outside that list are ignored rather
than reported under a guessed name, and asking about one by a name that is not
in it is an error rather than a silent `False`.

See [`examples/keyboard_state_test.py`](examples/keyboard_state_test.py).

> `key` is a live value, not a string. It compares, prints and formats like the
> key name, which covers ordinary use. To keep a copy that will not change with
> the next press, use `str(key)` or `key.value`.
>
> `from trjoludus import input` shadows Python's built-in `input()` in that
> file. If a file needs both, import `trjoludus.input` under another name.

See [`examples/keyboard_test.py`](examples/keyboard_test.py).

### Mouse input

```python
from trjoludus import input, mouse

if mouse.pressed("LEFT"):
    print(mouse.x, mouse.y)

mouse.wait(input.mouse)
print(mouse.button)     # LEFT
```

Where the pointer is and whether a button is held are **state**: read
`mouse.x`, `mouse.y`, `mouse.position` or `mouse.pressed("LEFT")` whenever you
like and you get the current answer. A button going down is an **input**:
`mouse.wait(input.mouse)` hands each press out exactly once, in order, exactly
as `keyboard.wait` does with keys.

Moving the mouse does not end a wait -- only a button does. Afterwards
`mouse.x` and `mouse.y` report where that click happened. The buttons are
`"LEFT"`, `"RIGHT"` and `"MIDDLE"`; the scroll wheel is not reported yet.

#### `pressed()` and `button` are different questions

```python
mouse.pressed("LEFT")   # is the left button down *right now*?
mouse.button            # which button did the last wait read?
```

`pressed()` follows the physical button: true from the moment it goes down
until it comes up, true on every frame in between, and reading it does not use
it up. Use it for holding -- dragging something, charging a shot.

`button` names the last mouse input that was **read** by a wait. It does not
change until the next one is read, so it still says `"LEFT"` long after the
left button came back up, and it is `None` until something has been read.

```python
mouse.wait(input.mouse)     # the player clicks and releases

mouse.button                # "LEFT"  -- what was read
mouse.pressed("LEFT")       # False   -- it is not held any more
```

For "was this drawing clicked this frame", neither is the tool: ask the
drawing, with `button.mouse.clicked()`.

### Time

```python
from trjoludus import time

time.wait(1)        # pause for a second
print(time.fps)
```

**Measure movement in time, not in frames.** `move.x(2)` moves twice as far on
a machine drawing twice as many frames. Scaling by `time.delta` -- how long the
last frame took -- moves the same distance per second on both.

```python
def on_update(self, dt):
    self.player.move.x(100 * time.delta)   # 100 pixels every second
```

That is all there is to it. **Positions carry fractions.** At 60 frames a
second each of those steps is 1.67 pixels, and the object keeps the fraction
rather than losing it or rounding it up, so a second later it has gone exactly
100 pixels. Only the renderer rounds, when it turns a position into a pixel.

`player.x` is the exact value -- `100.5` comes back as `100.5`. There is no
separate "precise position" to reach for; this is the position, and what gets
drawn is it, rounded. Whole numbers behave exactly as they always did.

`time.delta` is the same number `on_update(dt)` is handed. It exists so that
code which is not in `on_update` -- a helper, a method of your own -- can reach
it without it being passed down. It is `0.0` on the first frame of a run,
because nothing has been measured yet, so movement scaled by it stands still
for one frame instead of jumping by a made-up amount. It is also clamped, so a
frame that stalls cannot teleport your game.

`time.fps` is worked out from the most recent frame, so it jumps about. To show
it to a player, round it or only update the number a few times a second.

Both are read-only and read live: assigning to them raises, and reading always
gives the current answer. Reach them through the module -- `from trjoludus.time
import delta` would take a copy that never changes.

`time.wait()` keeps the window alive while it waits: events are still
delivered, so closing the window still reaches your game mid-wait. Like every
blocking call in TrjoLudus, it stops early if the game quits or its window
disappears, so a wait can never outlive the game it is in.

### Waiting for either

```python
from trjoludus import input, key, mouse

input.wait()

if input.type == input.key:
    print(key)
elif input.type == input.mouse:
    print(mouse.button)
```

The three waits share one queue in arrival order. `keyboard.wait` answers only
to keys and `mouse.wait` only to the mouse -- and the kind you did not ask for
is **kept**, not thrown away, so a click that arrives while you wait for a key
is still there afterwards. `input.wait()` takes whichever came first.

Every wait ends if the game quits or its last window disappears, so nothing
can block forever on input that can no longer arrive.

See [`examples/mouse_test.py`](examples/mouse_test.py).

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
player.set.x(250)    # put it exactly there
player.move.x(50)    # and now 50 pixels further right
```

Every absolute setter can also be assigned, which is the same operation
written the other way:

```python
player.set.x = 250
player.set.scale = 1.25
```

`set.x` and `set.y` set an **absolute** position. `move.x` and `move.y` change
it **relative** to wherever the object is now, so calls add up: two
`move.x(50)` calls move it 100 pixels in total. Negative values move left and
up. Nothing is clamped -- an object may be moved off screen.

Both take fractions. A position is a number, not a pixel: `set.x(100.5)` is a
real place to be, and it is kept exactly. Rounding happens once, in the
renderer, so what is drawn and what can be clicked always agree.

This is the same spelling drawings use, so one way of saying "put this here"
works on everything with a position. Assigning `player.x = 250` does the same
thing and still works; `set.x` is the spelling that reads the same next to
`move.x`.

### Objects by name

`create.image(...)` makes an object and files it under a name.
`GameObject(name)` looks that name up -- it never makes a second object:

```python
create.image(100, 100, "player.png", "player")

GameObject("player").move.x(50)
GameObject("player").set.scale(1.25)
```

A handle is a way of *reaching* an object, not the object itself, so you do
not have to keep one in a variable, and every handle to a name reaches the
same thing. Keeping one is still the shorter way to write it:

```python
player = GameObject("player")
player.move.x(50)
```

`destroy()` removes the object for good, through any handle. Every other
handle to it stops working at that moment, so nothing can go on moving
something that is gone.

### Making an object bigger

```python
player.set.scale(2)        # twice the size of its image
player.add.scale(0.25)     # a quarter bigger than it is now
player.remove.scale(0.25)  # and back
```

Scale grows an object from its top-left corner, which is where its position
already is, so scaling never moves what you placed. `size` then reports the
size it is drawn at, not the image's own size.

Images are scaled by nearest-neighbour: each drawn pixel takes the colour of
the source pixel it lands on. That keeps pixel art crisp instead of blurring
it, which is what a 2D engine usually wants.

### Animation

An animation is a list of pictures with a name. Define it once, then play it:

```python
player.animation.add("walk", ["walk_1.png", "walk_2.png",
                              "walk_3.png", "walk_4.png"])

player.animation.play("walk", fps=12, loop=True)
```

`fps` defaults to 10 and `loop` to `True`. `loop=False` plays once and stays
on the last frame. Every frame is loaded by `add()`, so a missing file is
reported where the list is written rather than mid-game.

**Playing does not block.** The engine advances the animation a little each
frame, using how long the frame took, so a game carries on moving, reading
input and drawing while it runs -- and the animation looks the same on a slow
machine as on a fast one.

**Calling `play()` again does nothing.** A game that plays "walk" every frame
while a key is held means "keep walking", not "start walking again", so the
second call is ignored and the animation carries on. It warns once, in case
that was not what you meant:

```python
if mouse.pressed("LEFT"):
    player.animation.play("walk", fps=12)   # every frame; carries on
    player.move.x(120 * time.delta)
```

To change how it plays, stop it first -- the ignored call ignores new `fps`
and `loop` settings too:

```python
player.animation.stop("walk")
player.animation.play("walk", fps=24)
```

The rest:

```python
player.animation.pause("walk")    # freeze on this frame
player.animation.resume("walk")   # carry on from it
player.animation.stop("walk")     # stop, keeping this frame

player.animation.current          # "walk", or None
player.animation.is_playing       # advancing right now?
player.animation.finished         # a loop=False animation reached its end?
```

Playing a *different* animation switches to it, from its first frame.

**Nothing switches by itself.** TrjoLudus never decides that an object should
be idling or walking. To go back to a single still picture, say so:

```python
player.set.image("idle.png")
```

That stops whatever was playing -- an animation and a hand-picked image cannot
both decide what is drawn, so the one you asked for wins. It warns, because a
game that did not realise something was playing would otherwise see its image
quietly overwritten on the next frame.

Animation only changes the picture. Position, fractional position, scale and
everything else about the object are untouched.

See [`examples/animation_test.py`](examples/animation_test.py).

### Collision

Ask whether two objects are overlapping:

```python
from trjoludus import objects

if objects.collide("player", "zombie"):
    zombie.animation.play("attack")
```

**TrjoLudus tells you what happened. You decide what it means.** Nothing moves,
nothing is destroyed and no health is lost unless you write it:

```python
if objects.collide("player", "zombie"):
    zombie.animation.play("attack")

    if objects.collide("player", "zombie_sword"):
        player.animation.play("take_damage")
        health -= 25
```

An object collides with the rectangle it is drawn in -- where it is, and how
big its picture is once its scale is applied. You never work that rectangle
out yourself, and you never keep it in step with anything: move the object and
what it collides with moves, scale it and what it collides with grows.

```python
player.set.scale(2.0)      # twice as big on screen, and twice as big to hit
```

Two things worth knowing:

- **Touching is not overlapping.** An object 10 wide at `x = 0` ends exactly
  where one at `x = 10` begins. They are side by side, not on top of each
  other, so laying walls in a row does not report a collision at every seam.
- **Invisible is not gone.** An object with `visible = False` still collides,
  which is how invisible walls and level boundaries are made. A **destroyed**
  object does not collide at all.

```python
boundary.visible = False           # can't be seen, still stops the player
old_wall.destroy()                 # gone; collides with nothing
```

If you name an object that does not exist, you get `False` and a warning
saying which name it was -- a typo should be easy to find, not silent:

```python
objects.collide("player", "zomby")     # False, and warns about 'zomby'
```

Asking whether something collides with *itself* is a mistake rather than a
question, so it raises `CollisionError`:

```python
objects.collide("player", "player")    # CollisionError
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

> **Windows is unverified.** The Win32 backend is implemented and its
> structure is tested on Linux -- signatures, types, the window procedure's
> shape -- but nothing here has ever opened a window on Windows. Those tests
> check that the code is *consistent*, not that it *works*; only running it on
> a real Windows machine can show that. Linux/X11 is verified: the tests open
> real windows and read their pixels back from the X server.

## Learning TrjoLudus

[`examples/`](examples/README.md) is the home of the **Introduction & Tutorial
project** -- how to *use* the engine, as opposed to `tests/`, which verifies
that the engine is *correct*. It grows as engine features land.

## Development

This section is for people working on the engine. **If you are making a game,
you do not need any of it** -- see [Requirements](#requirements).

### What you need

| | Making a game | Working on TrjoLudus |
| --- | --- | --- |
| Python 3.11+ | required | required |
| `rustc` and `cargo` | **not needed** | needed for the native side |

TrjoLudus is a Python library that *can* use a native library, not a Python
wrapper around a Rust one. An installed TrjoLudus runs entirely on Python and
never needs a compiler. The Rust toolchain is a contributor's tool.

Install it with [rustup](https://rustup.rs) if you need it:

```sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustc --version
cargo --version
```

### Building a package

```sh
python -m pip wheel . --no-deps -w dist
```

With a Rust toolchain present this compiles the native library and produces a
platform wheel:

```text
trjoludus-0.0.1-py3-none-linux_x86_64.whl     contains the native library
```

Without one it produces a pure-Python wheel, which is a complete engine:

```text
trjoludus-0.0.1-py3-none-any.whl              no native library
```

`TRJOLUDUS_BUILD_NATIVE` decides when you want to be sure: `1` requires the
toolchain and fails the build without it, `0` skips it. The library is always
compiled from `rust/` during the build -- a leftover build in
`trjoludus/native/lib/` is never packaged.

### Tests

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

The native side has its own tests, and they are separate:

```sh
cd rust
cargo build
cargo test
```

The packaging tests build real wheels and look inside them, which takes about
half a minute, so they are asked for rather than run by default:

```sh
TRJOLUDUS_PACKAGING_TESTS=1 python -m unittest tests.test_packaging
```

The Python suite passes whether or not a native library has been built: the
loader tests point at directories they create, rather than at whatever happens
to be in your working tree. A handful skip when there is no compiled library
anywhere to load, which is the one thing that genuinely cannot be faked.

To give a checkout a native library, build it and copy it in --
`TRJOLUDUS_NATIVE_DIR` points the loader somewhere else if you would rather not.
See [`rust/README.md`](rust/README.md).

## Advanced: choosing a backend

**You can skip this section.** TrjoLudus is a Python library, everything above
is normal Python, and a game never has to mention any of what follows. There is
no Rust in the beginner path and no Rust to learn.

TrjoLudus is growing native implementations of the parts where Python is the
bottleneck. Which implementation each subsystem uses is its own setting:

```python
from trjoludus import image, rendering

rendering.engine = "rust"     # insist on the native one
image.engine = "python"       # insist on the Python one
```

| Value | Meaning |
| --- | --- |
| `"auto"` | **The default.** TrjoLudus uses whichever it recommends for that subsystem, and the other one if the recommended one is not available. An error only if neither is. |
| `"rust"` | Insist on the native implementation. A clear error if there is not one -- **never** a silent fall back to Python. |
| `"python"` | Insist on the Python implementation. A clear error if there is not one -- **never** a silent fall back to Rust. Useful for debugging, for comparing the two, and where no native library is available. |

Only `"auto"` ever falls back. That is what it is for.

The subsystems, what `"auto"` prefers for each, and what exists today:

| Subsystem | `"auto"` prefers | Implemented today |
| --- | --- | --- |
| `rendering` | native | **Python and Rust** |
| `image` | native | **Python and Rust** |
| `animation` | Python | Python |
| `collision` | Python | Python |
| `physics` | -- | neither yet |
| `ai` | -- | neither yet |
| `pathfinding` | -- | neither yet |
| `audio` | -- | neither yet |

The subsystems with nothing written prefer nothing: TrjoLudus does not have an
opinion about how a system should be implemented before it is.

**A registered name is not an implementation.** `physics`, `ai`, `pathfinding`
and `audio` have a setting and nothing behind it. Setting one is
accepted; *using* it is an error that says so:

```python
>>> from trjoludus import physics
>>> physics.engine = "python"          # accepted -- it is a valid setting
>>> # ... and when something asks physics to do anything:
EngineError: physics.engine is 'python', but there is no Python
implementation of physics: nothing implements it yet in either language.
```

They are registered now so that an implementation can arrive without the API
around it being invented at the same time. Each will be written in Python
first.

Rendering and image are where the work is per-pixel every frame, which is why
they are the two that recommend the native implementation and the two that
have one. Nothing is moved to Rust to fill in a table -- a subsystem gets a
Python implementation first, and moves only when something measured says it
should.

**Rendering and image decoding have moved.** With a native library present,
`"auto"` uses Rust for both; without one it uses Python, and the results are
identical -- the test suite compares them byte for byte, including which
errors a damaged PNG produces. Every other subsystem is still Python, and
asking one of them for `"rust"` says so rather than pretending. The error distinguishes the two reasons it might fail:

```text
The native library is loaded but does not implement it yet.
The native library is not built or could not be loaded; see rust/README.md.
```

### Native platforms

| Platform | Native library | How it was verified |
| --- | --- | --- |
| Linux x86-64 | **supported** | built, packaged, installed, loaded and rendering here |
| Windows | not verified | never built or run |
| macOS | not verified | never built or run |
| Linux ARM | not verified | never built or run |

TrjoLudus installs and runs everywhere Python does. The table is about the
*native* library only: where it is not supported, every subsystem runs its
Python implementation, which is what happens on every platform today anyway.

The Linux x86-64 wheel is tagged `py3-none-linux_x86_64`. That tag is truthful
but deliberately not `manylinux`: a manylinux wheel promises compatibility with
a defined range of C libraries, and that promise has not been tested, so it has
not been made. The wheel installs directly; it is not yet a PyPI upload.

**Set it before `run()`.** Changing a subsystem's engine while a game is
running is refused, because half of it would already have started on the old
one.

```python
rendering.engine = "python"    # fine
run(MyGame())
```

Settings are per subsystem and independent: choosing one backend for rendering
says nothing about physics. They last for the life of the process, because they
are a statement about how the program should run rather than about one game.

### Images are decoded once

TrjoLudus keeps decoded images for the life of a run, so asking for the same
file twice does not decode it twice:

```python
create.image(100, 100, "player.png", "player")
player.animation.add("walk", ["walk_1.png", "walk_2.png"])
player.set.image("player.png")     # already decoded; nothing happens again
```

An animation's frames, an image switched back and forth, and two objects
sharing a picture are all one decode each. Images cannot be changed, so
sharing one is simply two objects looking at the same picture.

The images a run loads are released when it finishes, so a second `run()`
starts with nothing held.

If a file changes on disk while a game is running, the picture already loaded
from it stays -- TrjoLudus does not watch files. Restart the game to pick up
the new one.

### How much faster is it?

Rendering the same scenes into a 640x480 frame, on this machine:

| Work | Python | Rust |
| --- | --- | --- |
| clearing | 5.2 ms | 1.1 ms |
| rectangles | 22.9 ms | 9.9 ms |
| lines | 856 ms | 16.8 ms |
| text | 172 ms | 14.6 ms |
| images, opaque | 42.4 ms | 9.4 ms |
| images, transparent | 1419 ms | 11.6 ms |
| images, scaled 2x | 2444 ms | 15.7 ms |
| **a whole frame** | **278 ms** | **4.8 ms** |

Loading a PNG, on the same machine. Filter type matters more than size --
`Paeth` is what real drawing programs emit:

| Work | Python | Rust |
| --- | --- | --- |
| unfilter, Paeth 256x256 | 65.9 ms | 1.4 ms |
| unfilter, Paeth 512x512 | 283.9 ms | 5.9 ms |
| opacity scan, 512x512 | 9.7 ms | 0.11 ms |
| **whole decode, 256x256 Paeth** | **80.8 ms** | **1.5 ms** |

Run them yourself with `python tools/benchmark_rendering.py` and
`python tools/benchmark_images.py`. They are informational: the numbers move
with the machine, and no test depends on them.

The pixels are identical either way, which is the part that is tested rather
than measured.

Building the native library is documented in [`rust/README.md`](rust/README.md),
and is only of interest if you are working on the engine itself.

## Roadmap

The initial engine targets 2D only. 3D is explicitly out of scope and may be
considered much later.

| Milestone | Scope | Status |
| --- | --- | --- |
| 0 | Project foundation, platform detection | done |
| 1 | Window creation + game loop | done (Linux; Windows unverified) |
| 2 | Core engine: objects, drawing, input, interaction | done (Linux; Windows unverified) |
| 3.0 | Native architecture: backend selection, packaging, shared state | done |
| 3.1 | Native rendering | done (Linux x86-64; other platforms unverified) |
| 3.2 | Native PNG unfiltering and opacity scan | done (Linux x86-64; other platforms unverified) |
| 3.3 | Architecture cleanup: bulk world passes, result convention | done |
| 4 | Collision | in progress -- `objects.collide` in Python |
| 5 | Audio | planned -- Python first |
| 6 | Asset management | planned |
| 7 | Save systems | planned |
| 8 | Camera / viewport | planned |
| 9 | Public multi-window support | planned |

Milestone 2 was built in ten steps, each tested before the next began:

| Step | Scope |
| --- | --- |
| 1 | Game objects and image rendering (`create.image`, the scene, PNG loading) |
| 2 | Movement (`move.x`, `move.y`) |
| 3 | Keyboard input and `destroy()` |
| 4 | UI drawing: colours, lines, rectangles, text, drawing lists |
| 5 | Mouse input: position, held buttons, `mouse.wait()` |
| 6 | UI interaction: `hover()`, `clicked()`, scale, draw order |
| 7 | Dynamic drawings: changing text, colour, position and scale in place |
| 8 | Time: waiting, frame delta, frame rate, sub-pixel positions |
| 9 | Animation: named frame sequences |
| 10 | Keyboard held-key state |

**Not implemented, and deliberately not started:** sliders, text input,
drag-and-drop, layout systems, physics, AI, pathfinding, audio, saving,
cameras and public multi-window support.

Those four subsystems have a registered name and a backend setting, and
nothing behind either. That is deliberate -- it is what lets an implementation
arrive without the API around it being invented at the same time -- but a
registered name is not an implementation, and asking one of them for a backend
says so rather than pretending. Each will be written in Python first, and
moved only if a measurement asks for it.

## License

MIT
