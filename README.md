# TrjoLudus

A lightweight, custom 2D game engine/framework created by **Trjo Development Studio (TDS)**,
written in Python and designed for Windows and Linux.

> **Status: pre-alpha.** Milestone 1 is in progress. The platform-neutral
> foundation -- events, frame timing and the backend contracts -- is in place;
> there is no window, game loop or renderer yet.

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
    errors.py          exception hierarchy
    events.py          platform-neutral event types
    clock.py           frame timing
    platform/
        __init__.py    OS detection
        base.py        backend contracts
        null.py        headless backend, for tests and CI
tests/                 stdlib unittest suite
```

## Requirements

Python 3.11 or newer. Nothing else.

## Usage

```python
import trjoludus

print(trjoludus.__version__)        # 0.0.1
print(trjoludus.detect_platform())  # linux
```

## Development

```sh
python -m unittest discover -s tests
```

## Roadmap

The initial engine targets 2D only. 3D is explicitly out of scope and may be
considered much later.

| Milestone | Scope | Status |
| --- | --- | --- |
| 0 | Project foundation, platform detection | done |
| 1 | Window creation + game loop | in progress |
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
