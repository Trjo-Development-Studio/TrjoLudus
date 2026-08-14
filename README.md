# TrjoLudus

A lightweight, custom 2D game engine/framework created by **Trjo Development Studio (TDS)**,
written in Python and designed for Windows and Linux.

> **Status: pre-alpha.** On Linux, `run()` opens a **real window**, draws named
> image objects into it, moves and destroys them, draws lines, rectangles and
> text, changes any of it while the game runs, and reads the keyboard and
> mouse -- including which drawing the pointer is over and which one was
> clicked, and plays named animations. Verified on Linux/X11. A Windows backend exists but is **not
> verified on Windows**. Sound, collision, animation, saving and public
> multi-window support are not implemented.

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
    draw.py            drawing the user interface
    color.py           named colours
    ui.py              drawing lists and the interactive drawings in them
    font.py            the built-in text font
    keyboard.py        waiting for key presses
    time.py            waiting, frame delta and frame rate
    animation.py       named frame sequences and how they play
    mouse.py           pointer position, buttons and clicks
    input.py           what the waiting calls can wait for, and input.wait()
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
| 2 | Core engine: objects, drawing, input, interaction | done (Linux; Windows unverified) |
| 3 | Animation | planned |
| 4 | Collision | planned |
| 5 | Audio | planned |
| 6 | Asset management | planned |
| 7 | Save systems | planned |
| 8 | Camera / viewport | planned |
| 9 | Public multi-window support | planned |

Milestone 2 was built in seven steps, each tested before the next began:

| Step | Scope |
| --- | --- |
| 1 | Game objects and image rendering (`create.image`, the scene, PNG loading) |
| 2 | Movement (`move.x`, `move.y`) |
| 3 | Keyboard input and `destroy()` |
| 4 | UI drawing: colours, lines, rectangles, text, drawing lists |
| 5 | Mouse input: position, held buttons, `mouse.wait()` |
| 6 | UI interaction: `hover()`, `clicked()`, scale, draw order |
| 7 | Dynamic drawings: changing text, colour, position and scale in place |

**Not implemented, and deliberately not started:** sliders, text input,
drag-and-drop, layout systems, animation, collision, audio, saving, cameras,
public multi-window support, and any Rust or C++ component.

## License

MIT
