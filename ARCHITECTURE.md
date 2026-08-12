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
