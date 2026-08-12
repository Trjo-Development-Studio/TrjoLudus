"""The first real TrjoLudus window.

Opens an X11 window and runs the engine loop until you close it. Run it from
the repository root:

    python examples/window_test.py

Closing the window is a *request*: the backend reports it, and the game below
decides to honour it by calling ``quit()``. That is why ``on_event`` is not
optional here -- without it the window would refuse to close.

``tl.run()`` still defaults to the headless null backend, so the X11 backend is
passed in explicitly through ``Application``. Choosing a backend automatically
per platform is a later step.
"""

import sys
from pathlib import Path

# Run straight from a checkout, without installing first: Python puts this
# script's own directory on sys.path, not the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import trjoludus as tl  # noqa: E402
from trjoludus.platform.linux import X11Backend  # noqa: E402


class WindowTest(tl.Game):
    def on_start(self):
        self.elapsed = 0.0
        print("Window open. Close it to quit.")

    def on_event(self, event):
        if isinstance(event, tl.WindowCloseRequested):
            print("Close requested.")
            self.quit()
        elif isinstance(event, tl.WindowResized):
            print(f"Resized to {event.width}x{event.height}")

    def on_update(self, dt):
        self.elapsed += dt

    def on_stop(self):
        print(f"Ran for {self.elapsed:.1f}s. Goodbye.")


if __name__ == "__main__":
    tl.Application(
        WindowTest(),
        title="TrjoLudus — X11 Test",
        size=(800, 600),
        backend=X11Backend(),
    ).run()
