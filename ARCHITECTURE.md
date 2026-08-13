# TrjoLudus Architecture

Design decisions, and the reasoning behind them, for the TrjoLudus engine.

This document records *why* things are the way they are. It is written to be
re-read months later, and to be read by an AI assistant that has no memory of
the conversation the decisions came from.

> **Status:** Milestone 1 (window + game loop) is designed but **not yet
> implemented**. Everything below the "Decision log" is agreed; the code is not
> written.

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

## 7. Public API (Milestone 1)

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

**There is deliberately no `on_draw()` yet.** Milestone 1 has no renderer, so a
draw hook would have nothing to call into. It arrives in **Milestone 3 (2D
shape rendering)**, per the roadmap in the README -- Milestone 2 is keyboard and
mouse input. Adding it then is purely additive: games written against the
Milestone 1 API keep working untouched, because they simply do not override it.

Events are platform-neutral frozen dataclasses. Milestone 1 produces exactly
two:

```python
WindowCloseRequested()
WindowResized(width, height)
```

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
5. **Milestone 1 shows a blank window.** With no renderer, automated tests must
   assert on lifecycle and events rather than pixels; visual confirmation is a
   manual example script.
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
| 2026-08-12 | The scene is cleared when a run finishes | The objects belonged to that run. Leaving them would make a second `run()` inherit the first game's scene and collide on every name; anything created before a run still takes part in it |
| 2026-08-12 | One conformance suite runs the same contract assertions against every backend | A platform abstraction is only real if the layers above cannot tell which backend is underneath. Backends that cannot run on the current machine are skipped, never mocked -- a fake window server would agree with a wrong implementation |
| 2026-08-12 | Tutorial code may use the public API only | No `trjoludus.platform`, no `ctypes`, no private internals. A lesson that cannot be written without reaching past the public API is evidence the public API is unfinished, and the fix belongs in the engine. `examples/window_test.py` currently breaks this rule out of necessity and is therefore classified as an engine smoke test, to be replaced by a real first lesson once backend selection exists |

---

## 10. Milestone 1 build order

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
