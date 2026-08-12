# TrjoLudus Introduction & Tutorial

This directory is the home of the official **TrjoLudus Introduction & Tutorial
project**.

It is not a throwaway technical test. It is intended to become the way a new
user learns TrjoLudus, and it grows alongside the engine.

> **Status.** Barely started. The engine can open a window and run a loop, so
> that is all there is to teach so far. See "Current state" below.

## Purpose

1. Introduce new users to TrjoLudus.
2. Demonstrate what the engine can do.
3. Act as a practical tutorial for learning it.
4. Show what normal TrjoLudus game development looks like.
5. Give us a real project for manually verifying that the engine works.
6. Grow as new engine features land.

## How this differs from `tests/`

Both exist, and neither replaces the other. They answer different questions:

| | Question it answers | Audience |
| --- | --- | --- |
| `tests/` | *Does TrjoLudus work correctly?* | engine developers |
| `examples/` | *How do I make a game with TrjoLudus?* | game developers |

The automated suite in `tests/` remains the authority on correctness, and is
never weakened or replaced because something here demonstrates the same
feature. A tutorial that reads well is not evidence that the engine is right.

## Rules for tutorial code

**Public API only.** Tutorial code must import `trjoludus` and nothing deeper.
It must never touch:

- `trjoludus.platform` or any backend
- Xlib, Win32, or any OS API
- `ctypes`
- private engine internals (anything with a leading underscore)
- test-only helpers such as the null backend's event injection

The whole point is to show what an ordinary game developer writes. If a
tutorial can only be written by reaching past the public API, that is a signal
the public API is not finished yet -- and the fix belongs in the engine, not
here.

**Only teach what exists.** No lesson may demonstrate a feature the current
version does not have. It is better to have three honest lessons than fifteen
aspirational ones.

**Written for a beginner.** Simple, readable, commented where a comment
earns its place, and built up progressively so each lesson adds one idea to
the last.

## Current state

| File | What it is |
| --- | --- |
| `window_test.py` | **Engine smoke test, not tutorial material.** |

`window_test.py` opens a real X11 window and is how the Linux backend was
manually verified. It deliberately breaks the public-API-only rule above: it
imports `trjoludus.platform.linux.X11Backend`, because `tl.run()` cannot yet
select a backend on its own.

That makes it a poor first lesson, so it is not one. Once automatic backend
selection exists, `tl.run()` alone will be enough to open a window, and this
file gets replaced by a proper first lesson that needs no `platform` import.

## Planned progression

Indicative only. Each entry arrives when -- and only when -- the engine
supports it.

1. Creating your first TrjoLudus game
2. Creating a window
3. Understanding the game loop
4. Handling events
5. Keyboard input
6. Mouse input
7. Drawing shapes
8. Loading images and textures
9. Rendering text
10. Creating UI
11. Animation
12. Collision
13. Asset management
14. Saving and loading game data
15. Putting it together into a small playable game

## Running an example

From the repository root:

```sh
python examples/window_test.py
```
