# TrjoLudus Architecture

Design decisions, and the reasoning behind them, for the TrjoLudus engine.

This document records *why* things are the way they are. It is written to be
re-read months later, and to be read by an AI assistant that has no memory of
the conversation the decisions came from.

> **Status:** Milestones 1 (window + game loop) and 2 (core engine: objects,
> drawing, input, interaction) are **implemented and verified on Linux/X11**.
> The Win32 backend is implemented and structurally tested, but has **never
> been run on Windows**.
>
> Sections 1-6 describe the platform investigation and the loop, and are still
> current. Section 7 has been rewritten to describe the API that exists rather
> than the one that was planned. Section 10 records how it was built.

---

## 1. Layering

Games talk to a stable public API. Everything beneath it is free to change.

```
Your game
    |
TrjoLudus public API        <- stable, documented, platform-neutral
    |
Engine implementation       <- Python today; possibly Rust/C++ later
    |
Platform layer              <- the only OS-aware code
    |
Windows (Win32)   /   Linux (Xlib initially, native Wayland later)
```

Backends are plural and additive. Xlib is the *first* Linux backend, not the
only one TrjoLudus will ever have; a native Wayland backend is expected to sit
alongside it, selected at runtime. Nothing above the platform layer should ever
need to change when that happens.

Two rules keep this honest:

1. **`ctypes` is imported only under `trjoludus/platform/`.** Anything else
   importing it is a bug. This is mechanically checkable and should have a test.
2. **No module outside `trjoludus/platform/` may branch on the host OS.**

The platform layer is deliberately the piece that a future Rust or C++
implementation would replace. Keeping it narrow keeps that option open.

### Planned module layout

```
trjoludus/
  __init__.py          public API surface
  errors.py            exception hierarchy
  app.py               Application + the loop      (no OS code)
  game.py              Game base class             (no OS code)
  window.py            Window handle               (no OS code)
  events.py            platform-neutral event types
  clock.py             frame timing                (pure Python)
  platform/
    __init__.py        detect_platform(), get_backend()
    base.py            PlatformBackend / PlatformWindow contracts
    linux/
      _xlib.py         raw ctypes declarations only -- no logic
      x11.py           backend implementation
    windows/
      _user32.py       raw ctypes declarations only -- no logic
      win32.py         backend implementation
    null.py            headless backend, for tests and CI
```

Raw ctypes declarations (structs, constants, prototypes) live in `_xlib.py` and
`_user32.py` and contain no logic. Backend behaviour lives in `x11.py` and
`win32.py`. That split is what makes the backend swappable without rewriting
the bindings.

---

## 2. Platform investigation

Measured on the primary development machine on 2026-08-12. These findings are
what the Linux decision rests on, so they are recorded rather than summarised.

**Machine:** Bazzite 44 (Fedora Silverblue based), Python 3.14.6.

| Probe | Result |
| --- | --- |
| Session type | **Wayland** (GNOME / mutter) |
| Xwayland | **running**, rootless, on `:0` |
| `libX11.so.6` via `ctypes` | **works** -- opened display, read 1920x1200 |
| `libwayland-client.so.0` | present |
| `wayland-scanner` + protocol XML | **absent** (immutable image, no `-devel`) |
| `time.perf_counter` | `CLOCK_MONOTONIC`, 1 ns resolution |
| `time.sleep(1 ms)` | avg 1.07 ms, worst 1.15 ms |

X extensions exposed through Xwayland (25 total): `BIG-REQUESTS`, `Composite`,
`DAMAGE`, `DOUBLE-BUFFER`, `DRI3`, `GLX`, `Generic Event Extension`, `MIT-SHM`,
`Present`, `RANDR`, `RECORD`, `RENDER`, `SECURITY`, `SHAPE`, `SYNC`,
`X-Resource`, `XC-MISC`, `XFIXES`, `XFree86-VidModeExtension`, `XINERAMA`,
`XInputExtension`, `XKEYBOARD`, `XTEST`, `XVideo`, `XWAYLAND`.

`MIT-SHM`, `GLX` and `Present` being available matters for later rendering
milestones, not for Milestone 1.

---

## 3. Linux: Xlib via ctypes, through Xwayland (initial backend)

**Decision: the *first* Linux backend uses Xlib.** This is a starting point
chosen for what is achievable now, not a permanent commitment to X11. A native
Wayland backend is expected to be added later, behind the same interface and
selected at runtime; Xlib then becomes the fallback rather than the only path.
The `TRJOLUDUS_BACKEND` environment override exists partly so a second Linux
backend can be developed and tested side by side with the first.

Wayland has won the *session*, but that does not make X11 unavailable -- it
means X11 clients are served by **Xwayland**, which mutter starts
automatically and which is confirmed running with a full extension set.
Xwayland is not going away; Steam, Wine and most shipping games depend on it.

### Why native Wayland is deferred

Three concrete blockers, not a preference:

1. **No usable ABI without code generation.** `libwayland-client` exposes
   marshalling primitives (`wl_proxy_marshal_flags`) driven by
   `wl_interface`/`wl_message` tables that are normally generated at build time
   by `wayland-scanner` from protocol XML. Neither the scanner nor the XML is
   installed here, and both are build-time artifacts anyway, so they cannot be
   depended on at runtime on user machines. We would have to hand-transcribe
   those tables for `wl_display`, `wl_registry`, `wl_compositor`, `wl_surface`,
   `wl_shm`, `xdg_wm_base`, `xdg_surface`, `xdg_toplevel` and `wl_seat` before
   a single pixel appears.
2. **GNOME has no server-side decorations.** Mutter does not implement
   `xdg-decoration`. A native Wayland window means TrjoLudus draws its own
   title bar and implements drag-to-move, resize edges and the close button --
   a UI subsystem, required during Milestone 1, before a renderer exists.
3. **A Wayland surface cannot be mapped without a buffer.** There is no "show
   an empty window" path; a surface needs `wl_shm` content attached. Milestone 1
   would be forced to pull in rendering.

This is the same path SDL took: X11 only for roughly a decade, with Wayland
added later. It remains SDL's fallback today.

### Why Xlib rather than XCB

XCB has a cleaner ABI and avoids Xlib's fragile struct layouts, but it has far
less documentation and requires real X protocol knowledge. Xlib's main hazard
is the `XEvent` union; that is manageable because `XEvent` is guaranteed to be
at least `long pad[24]`, so a fixed 192-byte buffer can be allocated and only
the few event structs actually read need defining.

### Accepted costs

Xwayland adds a little input latency and does not do fractional-scale HiDPI
(it scales and blurs). Neither matters for Milestone 1.

### Calls needed for Milestone 1

`XOpenDisplay` · `XDefaultScreen` · `XRootWindow` · `XCreateSimpleWindow` ·
`XStoreName` and `_NET_WM_NAME`/`UTF8_STRING` via `XChangeProperty` ·
`XSelectInput` · `XMapWindow` · `XDestroyWindow` · `XCloseDisplay` ·
`XPending` · `XNextEvent` · `XFlush` · `XInternAtom` · `XSetWMProtocols` ·
`XSetErrorHandler` · `XSetIOErrorHandler`

Two are load-bearing and easy to overlook:

- **`WM_DELETE_WINDOW`** -- without registering this atom, clicking the window's
  close button kills the X connection instead of delivering a closable event.
  On X11 this *is* "window closing".
- **`XSetIOErrorHandler`** -- a fatal I/O error means the connection to the X
  server is gone: the server exited, the session ended, or the socket broke.
  Xlib's default handler prints to stderr and terminates the process.

  Installing our own handler does **not** prevent that. This was verified
  rather than assumed, by closing the connection's file descriptor and making
  a request: our handler runs, and then Xlib terminates the process with
  status 1 anyway. Execution does not resume, and Python's `atexit` callbacks
  do not run -- so this is not a hook that can free resources or unwind.

  What TrjoLudus therefore guarantees is narrow and worth stating plainly:
  **the process still dies, but it says why first.** The handler writes a
  diagnostic naming the lost display connection, so the failure is legible
  instead of an unexplained exit. It is installed before any display is
  opened, because a connection can die at any moment after that.

  Recovering from this would need `XSetIOErrorExitHandler` (libX11 1.7+),
  which is present on the development machine but not assumed to exist
  everywhere. Nothing in the engine relies on surviving a lost connection.

### Window titles use two properties with two encodings

A title is written twice, because the two X properties have different types:

| Property | Type | Encoding | Read by |
| --- | --- | --- | --- |
| `_NET_WM_NAME` | `UTF8_STRING` | UTF-8 | modern window managers |
| `WM_NAME` | `STRING` | ISO 8859-1 | old ICCCM clients |

`_NET_WM_NAME` is authoritative and lossless. `WM_NAME` is a Latin-1 property,
so it gets Latin-1 bytes; characters with no Latin-1 form become `?`. That is
lossy but valid, and the complete title is always in `_NET_WM_NAME`.

Writing UTF-8 into `WM_NAME` is a type error, not a harmless shortcut: an em
dash lands as three bytes that a conforming client decodes as three Latin-1
characters, which is exactly the mojibake this split avoids.

---

## 4. Windows: user32 + kernel32 via ctypes

**Decision: Win32 directly.** There is no alternative worth considering; this
is the foundation every Windows framework sits on.

| Purpose | Calls |
| --- | --- |
| Window class | `RegisterClassExW`, `GetModuleHandleW` |
| Create / destroy | `CreateWindowExW`, `DestroyWindow`, `ShowWindow` |
| Events | `PeekMessageW`, `TranslateMessage`, `DispatchMessageW`, `DefWindowProcW`, `PostQuitMessage` |
| Sizing | `AdjustWindowRectEx`, `GetClientRect` |
| DPI | `SetProcessDpiAwarenessContext` |

**Use the `W` (wide) variants throughout.** The `A` variants mangle non-ASCII
window titles.

**Set DPI awareness at startup.** Without `SetProcessDpiAwarenessContext`,
Windows silently reports incorrect window dimensions on scaled displays.

**Timing needs nothing special.** Python's `time.perf_counter()` already uses
`QueryPerformanceCounter` on Windows, and Python 3.11+ uses high-resolution
waitable timers for `time.sleep`. This should be verified rather than assumed,
but `winmm.timeBeginPeriod` is not expected to be necessary.

---

## 5. Differences that shape the design

| | Linux / X11 | Windows |
| --- | --- | --- |
| **Event delivery** | **pull** -- drain a queue | **push** -- OS calls your `WndProc` |
| Close request | `WM_DELETE_WINDOW` ClientMessage | `WM_CLOSE` message |
| Text encoding | UTF-8 bytes | UTF-16 wide strings |
| Size semantics | you specify the client area | you specify the outer rect (`AdjustWindowRectEx`) |
| Fatal errors | handler may `exit()` | `GetLastError` |
| Integer widths | `Atom`/`Window` are 64-bit `unsigned long` | `LONG` is 32-bit |
| **Resize / move** | ordinary events | **modal loop -- `DispatchMessageW` blocks** |

Two consequences drive the architecture:

**Push versus pull means the backend interface must be pull-based.**
`poll_events() -> Iterable[Event]`. The Win32 backend's `WndProc` appends to an
internal list that `poll_events` drains. This normalises the two models at the
lowest possible level, so nothing above the platform layer knows the difference.

**Windows' modal resize loop means delta time must be clamped.** While the user
drags or resizes the window, `DispatchMessageW` does not return and the loop
stalls. The next frame then reports a multi-second `dt`, and any game doing
`x += speed * dt` teleports. Debugger breakpoints cause the same thing on both
platforms. **`dt` clamping is a Milestone 1 requirement, not polish.**

---

## 6. Game loop: engine-owned

**Decision: the engine owns the loop.** `tl.run(game)`, with the game supplying
callbacks -- rather than the game writing `while window.is_open():`.

Three arguments, in order of weight:

1. **The Rust/C++ path depends on it.** The loop is the hot path. If the engine
   owns it, the entire loop -- event pump, timing, dispatch -- can eventually
   move into Rust, calling back into Python once per frame. If the game owns it,
   every iteration crosses the language boundary and the loop can never move.
2. **Asymmetry.** Engine-owned does not preclude adding a manual-stepping escape
   hatch later. Game-owned *does* preclude adding engine-owned cleanly, because
   the loop body becomes the API -- the exact order of poll/clear/present calls
   gets baked into every game written against it, and adding fixed-timestep or
   vsync later would be a breaking change. Engine-owned is the reversible
   choice; game-owned is the one-way door.
3. **Cross-platform necessity.** Windows' modal resize loop, and any future
   backend where the OS wants to own the run loop, are only solvable if the
   engine controls the loop.

On AI usability: a callback shape is easier for a model to get right. A
hand-rolled loop invites forgetting to pump events or miscomputing `dt`; there
is no way to get the callback order wrong.

The honest cost is inversion of control -- "where does my code run?" is less
obvious, and embedding TrjoLudus inside an external loop (a notebook, an
existing application) is harder. Since this engine exists to build our own
games, that trade is worth it.

### Timing model

**Variable `dt`, clamped, with a frame cap.** Not a fixed-timestep accumulator
-- that is a later milestone and would be over-engineering now. `on_update(dt)`
has an identical signature under both models, so introducing a fixed timestep
later changes no game code.

A frame cap is needed specifically because Milestone 1 has no renderer and
therefore no vsync; an uncapped loop would spin a CPU core at 100%.

---

## 7. Public API

```python
import trjoludus as tl


class Game:
    def on_start(self) -> None: ...
    def on_event(self, event) -> None: ...
    def on_update(self, dt: float) -> None: ...
    def on_stop(self) -> None: ...
    def quit(self) -> None: ...        # request shutdown

    @property
    def quit_requested(self) -> bool: ...   # read-only; set only by quit()


tl.run(game, *, title="TrjoLudus", size=(1280, 720), max_fps=60) -> None
```

**There is still no `on_draw()`, and it is no longer expected.** The reason it
was deferred was that there was nothing to draw into; what arrived instead was
*retained* drawing. A game says what should exist -- `create.image(...)`,
`menu.rect(...)` -- and the engine keeps drawing it every frame. Nothing has
needed a per-frame draw hook, because nothing has needed to re-issue drawing
commands. If an immediate-mode hook is ever added it stays additive: games
that do not override it are unaffected.

Events are platform-neutral frozen dataclasses:

```python
WindowCloseRequested()
WindowResized(width, height)
KeyPressed(key, window)
KeyReleased(key, window)
MouseMoved(x, y, window)
MouseButtonPressed(button, x, y, window)
MouseButtonReleased(button, x, y, window)
```

### The rest of the public API

```python
create.image(x, y, path, name)        # a named object the engine keeps drawing
GameObject(name)                      # a handle on one
    .set.x(v) / .set.y(v)             # absolute position
    .move.x(v) / .move.y(v)           # relative movement
    .x / .y / .position / .size       # where and how big
    .visible / .destroy()

draw.list(name)                       # a named group of drawing
    .line(x, y, end_x, end_y, colour) -> Drawable
    .rect(x, y, width, height, colour) -> Drawable
    .text(x, y, message, colour) -> Drawable
    .show() / .hide() / .clear() / .destroy()

Drawable                              # what a drawing call hands back
    .set.x/.set.y/.set.scale/.set.color/.set.text
    .add.scale / .remove.scale
    .move.x / .move.y
    .mouse.hover() / .mouse.clicked()
    .show() / .hide() / .bounds / .contains(x, y)

keyboard.wait(input.key)              # blocks; updates `key`
mouse.wait(input.mouse)               # blocks; updates `mouse.button`
input.wait()                          # blocks for whichever comes first
mouse.x / mouse.y / mouse.position    # where the pointer is now
mouse.pressed("LEFT")                 # is it held now
color.red, color.blue, ...            # named colours, or a plain (r, g, b)
```

**Position is spelled the same everywhere.** `set.x()` places something
absolutely and `move.x()` nudges it, on both game objects and drawings. There
is no `add.x()`: relative movement already has a word.

### What a game will look like

```python
import trjoludus as tl


class Pong(tl.Game):
    def on_start(self):
        self.elapsed = 0.0

    def on_event(self, event):
        if isinstance(event, tl.WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        self.elapsed += dt

    def on_stop(self):
        print(f"ran for {self.elapsed:.1f}s")


tl.run(Pong(), title="Pong", size=(800, 600))
```

Nothing platform-specific is visible, and this stays valid as backends and
renderers are added underneath.

---

## 8. Risks

Ordered by severity.

1. **ctypes pointer truncation causes segfaults.** Not hypothetical -- this
   happened during the investigation above, by omitting `argtypes` on
   `XCloseDisplay`, which truncated a 64-bit display pointer to `int`.
   *Mitigation:* every function gets explicit `argtypes` **and** `restype`,
   declared in one dedicated module, with no exceptions.
2. **Windows `WndProc` garbage collection crashes the process.** The
   `WINFUNCTYPE` callback object must be stored on the window instance. If only
   the OS holds a reference, Python frees it and the next message crashes.
3. **Xlib's default I/O error handler calls `exit(1)`**, bypassing Python
   cleanup. Install handlers before opening the display.
4. **The Windows backend cannot be tested on the development machine.** Win32
   code will be written against documentation and remain unverified until run
   on Windows or in a VM. Plan for it to need iteration.
5. **The renderer is pure Python, and its cost is unmeasured.** Every pixel is
   touched by the interpreter. It is fast enough for what has been built, and
   nothing has been optimised on a guess. See section 11 for the boundary a
   faster implementation would replace.
6. **Native Wayland is deferred, not free.** See section 3. It is a real project
   of its own whenever it is taken on.

---

## 9. Decision log

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-08-12 | No Pygame; no third-party engine or framework | Build it ourselves; the engine is the point |
| 2026-08-12 | Raw OS APIs via `ctypes`; no runtime dependencies | Keeps the platform layer thin and replaceable |
| 2026-08-12 | Flat package layout, `main` branch | Simplicity |
| 2026-08-12 | **Initial** Linux backend: Xlib via Xwayland | Works today; native Wayland has three hard blockers (section 3). A native Wayland backend is expected later, alongside rather than replacing this one |
| 2026-08-12 | Xlib rather than XCB | Documentation and simplicity; `XEvent` risk is manageable |
| 2026-08-12 | Windows backend: `user32` + `kernel32`, `W` variants | The only real option |
| 2026-08-12 | Pull-based backend event interface | Normalises Windows' push model at the lowest level |
| 2026-08-12 | Engine-owned game loop | Rust path, API stability, reversibility (section 6) |
| 2026-08-12 | Games subclass `tl.Game` with `on_*` methods | Consistent naming, natural home for state, AI-legible |
| 2026-08-12 | Variable `dt`, clamped; `max_fps=60` default | Avoids pinning a core with no vsync; fixed timestep can be added later without API change |
| 2026-08-12 | Headless `null` backend, built before any OS code | Proves the loop with zero platform code; runs in CI and without a display |
| 2026-08-12 | `on_draw()` deferred to Milestone 3 (2D shape rendering) | Adding a hook to a base class later is purely additive -- existing games simply do not override it -- so there is no churn to avoid by adding it early |
| 2026-08-12 | 3D is out of scope | 2D engine first; revisit much later |
| 2026-08-12 | Loop order: poll -> dispatch -> `clock.tick()` -> `on_update(dt)` | Follows the lifecycle agreed in section 5. The pacing sleep sits between dispatch and update, so events are up to one frame stale by the time a game reacts; ticking first would remove that. Not observable without a renderer, so revisit at Milestone 3 |
| 2026-08-12 | `tl.run()` defaults to the null backend | Development-stage behaviour only: no real backend exists yet, so a window is simulated and never closes itself. Real per-platform selection arrives with the X11 and Win32 backends |
| 2026-08-12 | `Application` is public alongside `tl.run()` | `tl.run()` stays the simple entry point; `Application` gives an explicit API and the testing seam, including direct backend injection |
| 2026-08-12 | `Game.quit_requested` is a public read-only property | `Game` owns the shutdown request through `quit()`; `Application` only observes it. Keeps the application off `Game`'s private state, and leaves exactly one way to request a stop |
| 2026-08-12 | X11 backend owns the display connection; windows own only their own X window | X delivers events per *connection*, and closing a display invalidates every window on it. The backend opens the connection when constructed and closes it in `shutdown()`; `X11Window.close()` destroys one window and never touches the connection |
| 2026-08-12 | The X11 backend pumps the connection and files events per window | X has one event queue per connection, not per window, so draining it from one window would swallow another window's events. The backend routes each event to the window it names; `poll_events()` returns only that window's events |
| 2026-08-12 | `tl.run()` still defaults to the null backend in Step 4 | Running on X11 means passing `Application(..., backend=X11Backend())` explicitly. Automatic per-platform selection is deliberately deferred, so Step 4 changes nothing above the platform layer |
| 2026-08-12 | `examples/` becomes the Introduction & Tutorial project | One project rather than a separate tutorial tree, so there is nothing to duplicate or keep in sync. It answers "how do I make a game with TrjoLudus?"; `tests/` keeps answering "is TrjoLudus correct?", and is never weakened because a tutorial covers the same ground. See `examples/README.md` |
| 2026-08-12 | Backend selection resolves explicit name -> `TRJOLUDUS_BACKEND` -> platform default | Completes the override recorded in section 3. One rule, checkable in one place, and the override is what lets tests and CI pin the null backend without a display |
| 2026-08-12 | The backend is created when `run()` starts, not when `Application` is constructed | Constructing an application must never open a display, or every test that merely builds one would need an X server. Resolution and construction are separate functions so the decision itself stays testable headlessly |
| 2026-08-12 | Windows has no default backend; selecting one there raises | Its backend does not exist yet, and defaulting to something else would fail further from the cause. The error names `TRJOLUDUS_BACKEND=null` as the way to run meanwhile |
| 2026-08-12 | **Superseded:** Windows now defaults to the `win32` backend | Step 6 implemented it. There is still no silent fallback to `null`: a headless fallback on a desktop OS would look like success while showing nothing |
| 2026-08-12 | Win32 types are declared at Windows' widths, not the host's | `ctypes.wintypes` derives `LONG` from the *host* C ABI -- 8 bytes on 64-bit Linux, 4 on Windows -- so structures built from it have the wrong layout anywhere but Windows. Declaring fixed-width types where Win32 is fixed-width, and pointer-sized types where it is pointer-sized, makes a declaration mean the same thing on every machine and lets the layouts be unit-tested on Linux |
| 2026-08-12 | `_user32.py` imports on any platform; only `load_libraries()` fails off Windows | Development happens on Linux, so the declarations have to be reviewable and testable there. `ctypes.WinDLL` and `WINFUNCTYPE` do not exist off Windows, so both are used lazily |
| 2026-08-12 | The Win32 backend answers `WM_CLOSE` itself instead of calling `DefWindowProcW` | The default handler destroys the window. Queuing `WindowCloseRequested` and leaving the window alive is what makes closing the game's decision, matching `WM_DELETE_WINDOW` on X11 |
| 2026-08-12 | The Win32 backend never calls `PostQuitMessage` | `WM_QUIT` exists to end a message loop, and the loop belongs to `Application`. Posting it would make the backend a second loop owner |
| 2026-08-12 | Each teardown step in `Application.run()` gets its own `finally` | Closing the window and shutting the backend down release *different* resources: an X display connection and a registered window class outlive the window that used them. They were previously in one block, so a raising `close()` skipped `shutdown()` and leaked the backend |
| 2026-08-12 | `NullBackend.create_window()` rejects calls after `shutdown()` | The real backends cannot make a window once the display connection or window class is gone. A stand-in that quietly allowed it would let a test pass on code that breaks on Linux and Windows, which defeats the point of having one |
| 2026-08-12 | `shutdown()` closing open windows stays backend-specific | The contract says shutdown runs *after* the windows are closed, so doing it anyway is defensive. X11 and Win32 must, or they leak native handles; the null backend has nothing to leak and deliberately does not, keeping its teardown observable in tests |
| 2026-08-12 | X11 property tests read over the engine's own connection rather than shelling out to `xprop` | `xprop` resolves the window ID on its *own* connection, and X reuses IDs aggressively, so probes raced with ownership; it also transcodes values into the terminal locale, so it could not show the stored bytes these tests exist to check. X orders one connection's requests, so a same-connection read is deterministic without adding any synchronisation to production code |
| 2026-08-12 | The rendering contract is one method: `present(pixels, width, height)` | The backend is handed finished pixels and asked to show them. It is told nothing about game objects, images or draw order, so no game concept reaches the platform layer, and a backend needs one method rather than a drawing API |
| 2026-08-12 | Frames are composited as BGRA | Not arbitrary: an X11 `ZPixmap` on a little-endian TrueColor display and a 32-bit Windows DIB expect exactly that order, so presenting a frame is a memory copy on both platforms. Any other layout would need a per-pixel conversion every frame, which in pure Python would cost more than the rest of the frame together |
| 2026-08-12 | PNG decoding is written here, using `zlib` | Keeps the no-dependency rule. Deliberately small: 8-bit non-interlaced PNGs, which is what sprites are saved as, and a clear refusal otherwise rather than a guess |
| 2026-08-12 | `draw.image()` creates a lasting object rather than painting once | The engine keeps the object and draws it every frame, so a game says what exists instead of repainting it. Worth stating because `draw` reads like an immediate-mode call in most 2D libraries; calling it every frame would try to reuse a name and fail |
| 2026-08-12 | Duplicate object names are an error, not a replacement | Replacing silently would make a repeated or mistyped name look like it worked while one of the two objects quietly vanished |
| 2026-08-12 | `GameObject(name)` finds an object; it never creates one | Creation goes through `draw`. A handle carries no state of its own and reads through to the scene record, so anything done through it affects what is actually drawn, and a later `player.move.x(50)` has an obvious home |
| 2026-08-12 | Coordinates: origin top-left, y downward, pixels, positioning the image's top-left corner | What X11 and Win32 both use natively, so nothing is transformed on the way to the screen. Camera and world coordinates are a later concern |
| 2026-08-12 | **Superseded:** the call is `create.image()`, not `draw.image()` | Same behaviour, better name. `create` is for things that become part of the scene and persist; `draw` is reserved for immediate, per-frame drawing such as UI. Naming a lasting object after `draw` invited calling it every frame, which would reuse a name and fail |
| 2026-08-12 | Movement is `player.move.x(50)`, relative, on a namespace object | Assigning `x` sets an absolute position; `move` changes it by an offset, so calls accumulate. Keeping them separate means the two readings of "set the position" cannot be confused. `move` is a small object holding the handle, which gives later movement concepts somewhere to go without widening `GameObject` |
| 2026-08-12 | Movement clamps nothing | There is no world boundary or collision system, so an object may be moved off screen. Inventing a limit here would silently disagree with a game that meant to do that |
| 2026-08-12 | Positions must be whole pixels | A float position reaches the frame buffer as a slice index and fails there with a message about slice indices, far from the line that caused it. Checking at the call site names the actual mistake |
| 2026-08-12 | Using a removed object is an error, not a no-op | A handle outlives what it points at. Letting it keep working would move something nobody draws, which reads as the engine ignoring the game. Removal marks the record, and handles report it |
| 2026-08-12 | `keyboard.wait(input.key)` updates `key` instead of returning it | A game reads the key where it needs it rather than threading a variable through. `key` is a live value, not a string: Python cannot let one module rebind a plain variable belonging to another, so it proxies comparison, printing and formatting, and `key.value` gives a plain copy |
| 2026-08-12 | Each key press answers exactly one wait | Presses queue and are handed out oldest first, each consumed once. That is what makes a second wait actually wait, without throwing away input that arrived while the game was busy |
| 2026-08-12 | `wait()` pumps the existing loop rather than starting one | It drains the same window and delivers non-key events exactly as the main loop does, so a close request still reaches the game mid-wait and a game that honours it is not left blocked. No thread, no second loop |
| 2026-08-12 | Key presses do not also reach `on_event` | One press belongs to one place. Delivering it to both would show a game the same press twice and leave it unclear which handled it |
| 2026-08-12 | `GameObject.destroy()` replaces `create.remove()` | Removal is something an object does, not something the creation namespace does. One way to remove an object, and no competing spelling |
| 2026-08-12 | Destroying twice is an error | The second call cannot mean anything. Staying silent would hide the same confusion in code that runs it in a loop |
| 2026-08-12 | An application stops when its last window is gone | A game whose window has vanished cannot be seen or interacted with. The loop and every blocking engine call ask the backend one question, `keeps_application_alive`, so the rule is general rather than a patch on whichever call happened to hang |
| 2026-08-12 | A window can go away without a close request | Closing is a request the desktop *may* send; destruction is something it can simply do. Waiting for an event that is not coming is what hung `keyboard.wait()`, so window liveness -- not the close event -- is the condition |
| 2026-08-12 | The null backend is exempt from that rule | It has no window on screen to lose, and it is what headless runs and tests use. Ending a run because a simulated window was closed would make the stand-in behave unlike the thing it stands in for |
| 2026-08-12 | Drawing to a window that is gone is skipped, not suppressed | `present()` does nothing once a window is destroyed. One protocol error can still occur when the window dies mid-frame, because X is asynchronous and the notification has not arrived yet; that error is reported rather than swallowed |
| 2026-08-12 | `draw` is the user interface; `create` is the world | `draw.rect/line/text` paint interface on top of the game, and images stay objects made by `create.image`. Keeping the two words apart is what stops "draw" meaning both "paint this now" and "make a thing that exists" |
| 2026-08-12 | Drawing is remembered, like everything else | A game says what should be on screen and the engine keeps drawing it, so a menu is built once rather than repainted every frame. Drawing inside `on_update` therefore adds another copy each frame, which is why `draw.clear()` and named lists exist |
| 2026-08-12 | Unnamed drawing goes into an ordinary list called `default` | The named and unnamed forms then behave identically, and `draw.clear()` is just that list being cleared. One code path rather than a special case |
| 2026-08-12 | Duplicate drawing-list names are an error | Same reason as object names: replacing silently would lose whatever the first list held with nothing to show for it |
| 2026-08-12 | The engine carries its own 5x7 font | There are no dependencies and no font file can be assumed present, so text ships as a 475-byte bitmap of printable ASCII. Unsupported characters draw a hollow box, so text with a missing character reads as text with something missing rather than quietly losing letters |
| 2026-08-12 | Lines put their endpoints in a fixed order first | Bresenham is not symmetric: run from the other end it rounds the other way and lights different pixels. A line that changes depending on which end you name would be a surprise |
| 2026-08-12 | A frame is drawn before the loop starts | The loop draws after `on_update`, so a game whose first update blocks -- waiting for a key, say -- would sit on an empty window until the player pressed something. Drawing once after `on_start` makes the opening screen appear |
| 2026-08-13 | Pointer position is state; a button press is input | Where the mouse is can be read at any time and is always current. A press happens once and is handed out once. That split is why moving the mouse does not end `mouse.wait()` -- waiting on movement would return the instant anyone nudged it, which is not what waiting for input means |
| 2026-08-13 | `mouse.x`, `mouse.y` and `mouse.button` are looked up, not stored | Reading them always gives the current answer, so nothing has to be refreshed and there is no copy to fall out of date. The keyboard's `key` is a live object for the same reason, by a different route: it has to survive being bound to a bare name |
| 2026-08-13 | `mouse.wait()` reports where the *click* happened | Several events can arrive in one batch, so the pointer may already have moved on by the time the click is answered. A game acting on a click means the place it was made |
| 2026-08-13 | Button releases are selected, though key releases are not | "Is this button held" has to know when it stops being held. Nothing yet asks the same of a key, and selecting events no one reads only costs round trips |
| 2026-08-13 | One wait implementation serves keyboard and mouse | Both queue input, hand it out oldest first, and have to stop for the same reasons -- the game quitting, or the last window disappearing. Two copies would let a new kind of waiting quietly miss one of those reasons |
| 2026-08-13 | All input shares one queue in arrival order | Separate queues per kind lose the order between a key and a click, which `input.wait()` has to preserve. Each wait scans for the oldest item of the kind it wants and leaves the rest alone, so nothing is discarded and nothing is answered twice |
| 2026-08-13 | A wait answers only its own kind, and keeps the others | A click must not wake `keyboard.wait()`, but throwing it away instead would be worse: it is still input the game has not read. It waits for whoever asks |
| 2026-08-13 | `input.wait()` takes whichever input came first | With one ordered queue this is the same mechanism as the specific waits, with no kind filter. `input.type` then says which arrived, and the value is wherever that kind normally goes |
| 2026-08-13 | Every blocking call stops for the game quitting *or* the last window going | One implementation serves all three waits, so a new kind of waiting cannot quietly miss a reason to stop. The testing rule that goes with it: a test containing a blocking wait must script its own way out, never rely on a timeout, or a hang becomes a slow pass |
| 2026-08-13 | Mouse state lives per window, behind the global names | A position only means something against a particular window's drawable area. `MouseState` is per window and queued input records which window it came from, so a future `some_window.mouse` is the same object rather than a redesign. A single-window game reads the same names it always did |
| 2026-08-13 | Every drawing call returns the thing it drew | A drawing has to be held to be hovered, clicked or scaled, so `rect()` and friends hand back a `Drawable` instead of the list. Chaining went with it; being able to name a button is worth more |
| 2026-08-13 | Interaction uses the existing draw order | Where drawings overlap, the one drawn last is the one visible there, so it is the one the mouse finds. Inventing a separate z-order would let what you see and what you click disagree |
| 2026-08-13 | `hover()` is a question about now; `clicked()` is about this frame | Holding a button down must not keep firing a click, so a press counts only for the frame it arrived in. Asking twice in that frame gives the same answer -- it is a query, not something used up |
| 2026-08-13 | Clicks are recorded per frame *as well as* queued for the waits | A UI query and a blocking wait want different things from the same press: one asks what happened, the other consumes it. Making `clicked()` take from the queue would let a button steal input from `mouse.wait()` |
| 2026-08-13 | Scale grows a drawing from its top-left corner | That corner is where the position already is, so scaling never moves what a game placed. Text scales by drawing each font pixel as a block measured from the scaled edges, which tiles without gaps at fractional scales |
| 2026-08-13 | A drawing answers only to the mouse in its own window | The window a list belongs to is part of the hit test, so a pointer in one window cannot hover a button in another, and a drawing elsewhere cannot cover one here |
| 2026-08-13 | A drawing is changed in place, not redrawn | Retained mode already keeps what was drawn, so the honest way to change it is to change that one record. Rebuilding a list every frame would throw away the identity a button needs to be hovered and clicked |
| 2026-08-13 | `set` for exact values, `move` for nudging, `add`/`remove` for relative change | Three spellings for three intentions. `set.x()` is deliberately absent: movement already has a word, and having two ways to place something invites them to disagree |
| 2026-08-13 | Only scale gets `add` and `remove` | Relative change has to mean something. Growing a colour does not, and moving is what `move` is for, so generating a relative form of every property would add spellings without adding sense |
| 2026-08-13 | A drawing has only the properties its kind has | `set.text()` on a rectangle raises rather than being ignored, and names what that kind does have. A property that quietly does nothing is a bug the game cannot see |
| 2026-08-13 | Position and size are stored once and read by both drawing and hit-testing | There is one copy of where a drawing is, so a change cannot make what is drawn and what is clickable disagree. Bounds are computed from it on demand rather than cached, which is why no change needs to remember to invalidate anything |
| 2026-08-13 | Drawings hold named fields, not the arguments they were made with | Mutation needs somewhere to put a new value. Keeping `x`, `message` and the rest as fields is what makes changing one of them a one-line assignment instead of rebuilding a tuple |
| 2026-08-14 | A stop request belongs to one run, and a run clears it as it begins | Without this a `Game` instance could only ever be run once: the flag it set the first time was still true, so the second run stopped before its first frame. Cleared at the start rather than the end so the answer stays readable afterwards -- a caller can still tell a game that asked to stop from one whose window went away |
| 2026-08-14 | The application asks the game to clear it, rather than writing the flag itself | `app.py` reads `quit_requested` and never names the private attribute, which a test enforces. The reset is `Game._begin_run()`, so the one piece of state stays owned by the class that owns the request |
| 2026-08-14 | `set.x()` and `move.x()` mean absolute and relative, on drawings *and* game objects | Supersedes 2026-08-13's "there is no `set.x`". One concept should have one spelling wherever it appears, and a drawing that could never be repositioned was the price of the old rule. `add.x`/`remove.x` are still absent -- relative movement already has a word |
| 2026-08-14 | A drawing's fields are read-only; `set` and `move` are how it changes | They used to be plain slots, so `drawing.x = 1.5` wrote a float straight into a position and failed much later somewhere else. Routing every change through a namespace means every change is checked |
| 2026-08-14 | Placing a line moves the whole line | `set.x()` on a line shifts both ends, so it keeps the shape it was drawn with. Moving one end is a different operation and would need a different name |
| 2026-08-14 | `GameObject.x = 250` stays supported alongside `set.x(250)` | It is what Step 2 shipped and what existing games are written against. Removing a working spelling to make room for a new one costs more than keeping both |
| 2026-08-14 | The PNG decoder refuses damage rather than decoding past it | Every chunk must fit inside the file, claim a believable length, and match its own checksum, and the file must start with IHDR and reach IEND. Slicing past the end of a `bytes` yields a short string rather than an error, so without these checks a truncated file decoded quietly into wrong pixels |
| 2026-08-14 | CRCs are checked, though they were optional | `zlib` is already imported for the pixel data, so it cost one line and catches the damage a length check cannot -- a flipped bit inside a chunk that is still the right size |
| 2026-08-14 | `mouse.pressed()` and `mouse.button` are documented as different questions | One is the physical button now, the other is which input a wait last read. They disagree the moment a button is released, and the difference was true in the code but written down nowhere |
| 2026-08-14 | `Framebuffer` is the named boundary a faster renderer would replace | Writing down the contract -- BGRA, top-down, clipped, exactly these methods -- is what makes a future Rust implementation a swap rather than a redesign. No measurement has been taken, so no optimisation has been made |
| 2026-08-15 | A `GameObject` is a handle on a record, not the record | `GameObject(name)` looks a name up and never creates anything; `create.image(...)` is the only thing that makes an object. Any number of handles can name the same object, they all see the same changes, and one made and thrown away in a single expression works exactly like one kept in a variable. Identity lives in the scene, so there is nothing for two handles to disagree about |
| 2026-08-15 | Destroying marks the record, so every handle to it goes stale at once | The flag is on the `SceneObject`, not the handle, which is what makes `GameObject("player").destroy()` invalidate a handle held somewhere else. A per-handle flag would let a forgotten variable keep moving something nobody draws |
| 2026-08-15 | `set.x = 200` and `set.x(200)` are the same operation | Assignment routes to the method of the same name through one `__setattr__`, so there is a single implementation of each value and the two forms cannot drift apart. It also means the assignment form raises the same errors -- `rect.set.text = "x"` refuses exactly as `rect.set.text("x")` does |
| 2026-08-15 | Only `set` accepts assignment | `add.scale = 0.25` would read as "the scale is now 0.25" while meaning "add 0.25", so relative namespaces stay callable only. `move` likewise |
| 2026-08-15 | Game objects can be scaled, and it is nearest-neighbour | Each drawn pixel takes the colour of the source pixel it lands on: crisp for pixel art, no memory beyond the frame, and the index is derived from the destination size so it cannot read outside the source. Smoothing is a choice a game should make, and nothing has asked for it |
| 2026-08-15 | Scale 1 keeps the unscaled drawing path, byte for byte | Scaled compositing has no row-at-a-time fast path -- a scaled row is not a contiguous run of source bytes -- so it is a separate route rather than a general case that every frame pays for |
| 2026-08-15 | `GameObject.size` reports the drawn size, not the image's | "How big is this on screen" is the question a game asks. At the default scale of 1 the answer is unchanged, so nothing that existed before sees a difference |
| 2026-08-16 | One clock measures time for the whole engine | `Clock` already paced frames and measured deltas, so `time.delta` and `time.fps` read it rather than keeping figures of their own, and `Clock.now()` is what durations are measured against. A second timer somewhere else would be a second answer to the same question |
| 2026-08-16 | `time.wait()` turns the same crank as the input waits | Both go through `Application._keep_waiting`, which polls, delivers events, and gives up if the game quit or its last window went. A wait with a loop of its own would be a second game loop, and the next kind of waiting would have to remember all three reasons to stop again |
| 2026-08-16 | Waiting keeps the window alive rather than freezing it | Events are still polled and delivered mid-wait, so a close request reaches the game during `time.wait(5)` instead of five seconds later. A wait that stopped answering the desktop would look like the game had hung, which on Windows is what the desktop would then report |
| 2026-08-16 | `time.delta` and `time.fps` are read-only, and enforced | The module's type refuses assignment instead of letting `time.delta = 5` shadow the engine's measurement for good. A plain module `__getattr__` reads live but cannot stop that; the value a game only reads is exactly the one worth protecting |
| 2026-08-16 | Both are looked up on every read, never stored | The same reason `mouse.x` is: a stored copy is one that can fall out of date, and there is nothing to refresh if there is no copy. The cost is that `from trjoludus.time import delta` takes a snapshot, which the module says plainly |
| 2026-08-16 | The first frame of a run reports a delta of zero | There is no previous frame to measure against, so any other answer would be invented. Movement scaled by it stands still for one frame rather than jumping, which is the behaviour a game wants from a number it did not measure |
| 2026-08-16 | A run resets the clock as it begins | Alongside clearing the stop request. Without it a second run would open with a delta measuring the gap between the two runs -- clamped, but still meaningless -- and a frame count carried over from the first |
| 2026-08-16 | `fps` stays instantaneous, with no smoothing | It is `1 / delta`, which is jittery and honest. Smoothing is a display choice with a window length attached, and a game that wants one can average what it reads; baking one in would hide the frame that actually took long |
| 2026-08-17 | A position is a number; a pixel is not | Positions keep fractions and the renderer rounds when it draws. Movement measured in seconds is fractional by nature -- 100 pixels a second is 1.67 of one at 60 frames a second -- and whole-pixel positions forced a game to either drop that fraction every frame or round it up every frame. One crawls, the other drifts 20% in a second |
| 2026-08-17 | Rounding happens in one place, on the way to pixels | `Framebuffer` rounds every coordinate it is given, and `Drawable` rounds once into `screen_position`, which both its drawing and its hitbox are built from. Two roundings of the same number can disagree -- `round(x + n)` is not always `round(x) + n` -- so there is only ever one |
| 2026-08-17 | The exact position *is* the public position | `player.x` returns 100.5 when that is where it is. Adding a separate precise API would mean two answers to "where is it", and the rounded one would only ever be a rendering detail leaking upward |
| 2026-08-17 | Integers stay integers | A position keeps the type it was given, so a game that never uses fractions sees exactly what it saw before -- the same values, the same pixels, the same types |
| 2026-08-17 | Sizes stay whole numbers | A position can fall between pixels because it is a place; a width cannot be half a pixel because it is a count of them. `rect(0.5, 0, 5, 5)` is fine and `rect(0, 0, 5.5, 5)` is not |
| 2026-08-17 | Infinities and NaN are refused where positions are set | They cannot be rounded to a pixel, and `round(nan)` fails inside the renderer with a message about nothing a game would recognise. Catching them at the setter names the value that was wrong |
| 2026-08-18 | Defining an animation and playing it are separate | `add` says what an animation is, once; `play` says how it should run this time. The same walk cycle is played at different speeds in different situations, so speed belongs to the playing rather than to the thing being played |
| 2026-08-18 | Every frame is loaded when the animation is defined | A missing file is then reported where the list of frames is written, not mid-game when the animation first reaches that frame. It costs memory up front, which is the right trade for a handful of sprites |
| 2026-08-18 | `play()` on something already playing is ignored, settings and all | A game holding a key writes `play("walk")` every frame and means "keep walking". Restarting would pin it to frame 1 forever. Honouring a new `fps` while ignoring the restart would be worse -- half the call would apply -- so the whole call is ignored, and stopping first is how settings change |
| 2026-08-18 | Being ignored is a warning, not silence and not an error | The game keeps running because the ignore is usually correct, but a game that meant to restart would otherwise see nothing happen. Warned once per playback rather than every frame, because the call that causes it is in `on_update` |
| 2026-08-18 | Animation state lives on the scene record, not the handle | The same reason position does: `GameObject("player")` made and thrown away in one expression has to reach the same animator as one kept in a variable, and two handles must not disagree about what is playing |
| 2026-08-18 | The loop advances animations, between update and render | After the update, so an animation started this frame shows its first frame now; before the render, so what moved on is what gets drawn. Paced by the same clock as everything else, which is why an animation takes the same time on any machine |
| 2026-08-18 | A stalled frame advances several animation frames | The alternative is slow motion: an animation that lost time whenever a frame ran long would drift out of step with everything else measured in seconds |
| 2026-08-18 | Animation changes the image and nothing else | Position, fractional position, scale and visibility belong to the object. An animation that moved things would make two systems responsible for where something is |
| 2026-08-18 | `set.image()` stops a running animation, and says so | They cannot both decide what is drawn, and the picture a game explicitly asked for is the more specific instruction. Silently letting the animation overwrite it on the next frame would look like the image change did nothing |
| 2026-08-18 | Nothing switches animation automatically | No idle/walk state machine, no inferring intent from movement. A game says what is playing. Guessing would be wrong exactly when a game did something unusual, which is when it matters most |
| 2026-08-18 | Warnings are a `TrjoLudusWarning`, deduplicated by the engine | `warnings.warn` makes them visible, filterable and testable, but its own deduplication is per source line and can be reset by anything. Remembering what has been said, and forgetting when playback changes, is what keeps a per-frame call quiet without hiding a new mistake |
| 2026-08-19 | Held keys are state; presses are events; both come from one event | A `KeyPressed` marks the key held *and* queues a press for the waits. They are separate questions about the same thing, so neither takes anything from the other: a press read by `keyboard.wait()` still counts as held, and asking what is held never empties the queue |
| 2026-08-19 | A key coming up is state only, and is never queued | Waiting is for input that happened; a release is the *end* of something rather than a new thing to answer. Queuing it would let `keyboard.wait()` return on a key being let go, which is not what waiting for a key means |
| 2026-08-19 | Key state is a set, updated as events arrive | `pressed()` is asked about several keys every frame, so it has to be a lookup rather than a scan of the queue. The set is maintained at the point events are delivered, which is the only place that knows a key changed |
| 2026-08-19 | `pressed()` is not "pressed this frame" | Holding W means `pressed("W")` is true the whole time it is down. A one-frame edge is a different question, and calling it `pressed` would make the obvious reading wrong |
| 2026-08-19 | X11 asks for detectable auto-repeat | Holding a key makes the server send a stream of KeyRelease/KeyPress pairs, which would make held state flicker many times a second. `XkbSetDetectableAutoRepeat` asks for one release at the real release instead. Probed before use: present in libX11.so.6 and supported here. If a server refuses it, presses still work and only held state suffers, so it is not worth failing to start over |
| 2026-08-19 | Windows needs no equivalent | It repeats `WM_KEYDOWN` while a key is held but sends `WM_KEYUP` once, when the key really comes up. `WM_SYSKEYUP` is handled alongside it, because a key released while Alt is held arrives that way and would otherwise look permanently held |
| 2026-08-19 | Key state is per window, like the pointer | A key is held *in* a window, and one that is not focused is not receiving it. The public `keyboard.button` reads the running game's window; a future `some_window.keyboard` is the same object rather than a redesign |
| 2026-08-19 | A window going away releases everything held in it | There is no release coming for a window that no longer exists, so a key held at that moment would stay held for good -- and the next run would start with a key down that nobody is pressing |
| 2026-08-19 | An unknown key name raises rather than answering `False` | A misspelling would otherwise report "not held" forever, which looks exactly like a key that is simply not being pressed. Lowercase gets its own message, because that is the mistake people actually make |
| 2026-08-12 | The scene is cleared when a run finishes | The objects belonged to that run. Leaving them would make a second `run()` inherit the first game's scene and collide on every name; anything created before a run still takes part in it |
| 2026-08-12 | One conformance suite runs the same contract assertions against every backend | A platform abstraction is only real if the layers above cannot tell which backend is underneath. Backends that cannot run on the current machine are skipped, never mocked -- a fake window server would agree with a wrong implementation |
| 2026-08-12 | Tutorial code may use the public API only | No `trjoludus.platform`, no `ctypes`, no private internals. A lesson that cannot be written without reaching past the public API is evidence the public API is unfinished, and the fix belongs in the engine. `examples/window_test.py` currently breaks this rule out of necessity and is therefore classified as an engine smoke test, to be replaced by a real first lesson once backend selection exists |

---

## 10. Build order

Each step is independently testable. Steps 1-3 prove the loop, timing and
lifecycle with **zero platform code**, so when the X11 backend lands, any bug is
unambiguously in the backend.

| # | Step | Verified by |
| --- | --- | --- |
| 1 | `events.py`, `clock.py`, `platform/base.py` contract | unit tests, no OS |
| 2 | `null` backend | unit tests, headless |
| 3 | `app.py` + `game.py` loop on the null backend | unit tests -- loop proven before any OS code |
| 4 | X11 backend: display, window, title, `WM_DELETE_WINDOW`, poll, destroy | manual example |
| 5 | X11 wired into the real loop | manual: window opens, closes cleanly, `dt` sane |
| 6 | Win32 backend to the same contract | **needs a Windows machine** |
| 7 | Resize events and `dt` clamping on both | manual and unit |

Milestone 2 built the engine on top of that loop, one step at a time, each one
tested before the next began:

| # | Step | Verified by |
| --- | --- | --- |
| 1 | Game objects and image rendering | unit tests on the framebuffer; X11 pixel readback |
| 2 | Movement | unit tests; rendered position checked |
| 3 | Keyboard input and `destroy()` | unit tests; real X11 key events |
| 4 | UI drawing: lines, rectangles, text | pixel-level unit tests; X11 readback |
| 5 | Mouse input | unit tests; real X11 button events |
| 6 | UI interaction: hover, click, scale | unit tests; X11 readback of a hovered button |
| 7 | Dynamic drawings | pixel-count unit tests; X11 readback of changed text and colour |
| -- | Polish: lifecycle, position API, PNG hardening | unit tests; X11 readback |

---

## 11. The renderer boundary

The renderer is pure Python and touches every pixel through the interpreter.
That is fine for what has been built and has not been optimised, because
nothing has been measured. This section exists so that a future faster
implementation -- in Rust, in C, or in Python that has been profiled -- knows
exactly what it must replace and what it must not touch.

**The boundary is `Framebuffer`.** Everything above it deals in objects,
drawings and positions; everything below it deals in bytes.

```
scene / ui         "there is a button at (20, 20), 60 by 40, blue"
     |
     |  render(framebuffer)             <-- above here: what to draw
     v
Framebuffer        set_pixel, fill_rect, draw_line, draw_text, draw_image
     |
     |  present(pixels, width, height)  <-- below here: how to show it
     v
backend            XPutImage / StretchDIBits
```

`Framebuffer` is the only thing that writes pixels, and it is
platform-neutral: it knows nothing about X11 or Win32, and the backends know
nothing about game objects. Its whole contract is:

| Member | Contract |
| --- | --- |
| `pixels` | a `bytearray`, `width * height * 4` bytes, **BGRA**, row-major, top row first |
| `width`, `height` | the size in pixels |
| `resize(w, h)` | change the size; contents undefined afterwards |
| `clear()` | fill with `DEFAULT_CLEAR_COLOUR`, opaque |
| `set_pixel`, `fill_rect`, `draw_line`, `draw_text` | draw, clipped to the buffer, never raising for out-of-range coordinates; coordinates may be fractional and are rounded here |
| `draw_image(image, x, y, scale=1.0)` | composite, clipped; `x` and `y` may be fractional and are rounded; `scale` grows from the top-left corner, nearest-neighbour, and `scale=1.0` must produce exactly the unscaled pixels |

Rounding is part of the contract, not an implementation detail: everything
above this module works in exact positions, and this is where they become
pixels. A replacement that rounded differently would move every sprite by up
to half a pixel and, worse, disagree with the hitboxes computed above it.

**A replacement implementation has to keep three promises**, all of which are
already tested:

1. **BGRA, tightly packed, top-down.** This is not an internal choice: it is
   what X11's `ZPixmap` wants on little-endian TrueColor *and* what a 32-bit
   Windows DIB wants, which is what makes presenting a frame a `memcpy`
   instead of a conversion. Changing it means changing both backends.
2. **The same pixels.** `tests/test_rendering.py` and `tests/test_ui.py` assert
   exact pixel values -- blending, clipping at all four edges, Bresenham lines,
   the 5x7 font, scaled text tiling without gaps. Those tests are the
   specification; a faster renderer has to pass them unchanged.
3. **No leakage upwards.** Nothing above `Framebuffer` may learn what is
   underneath it. `scene`, `ui` and `app` call the methods in the table above
   and nothing else, so swapping the implementation cannot change a single
   line of the public Python API.

What is deliberately *not* promised: that `pixels` is a `bytearray` rather
than any buffer of the right shape, that drawing happens on the calling
thread, or that the buffer is reallocated on resize. Those are free to change.

**Not now.** No Rust, no C, no rewrite -- and no optimisation until something
has been measured and found too slow. This section is a map, not a plan.
