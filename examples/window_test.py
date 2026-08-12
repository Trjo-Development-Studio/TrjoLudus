"""The first real TrjoLudus window, using nothing but the public API.

Run it from anywhere:

    python examples/window_test.py

TrjoLudus picks the backend for you -- on Linux that is X11. Set
``TRJOLUDUS_BACKEND=null`` to run the same game headless, with no window.

Closing the window is a *request*: the engine reports it and the game decides.
That is why ``on_event`` matters here -- without it, the close button would do
nothing.
"""

import sys
from pathlib import Path

# Run straight from a checkout, without installing first: Python puts this
# script's own directory on sys.path, not the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trjoludus import (  # noqa: E402
    Game,
    WindowCloseRequested,
    WindowResized,
    run,
)


class WindowTest(Game):
    def on_start(self):
        self.elapsed = 0.0
        self.frames = 0
        print("Window open. Close it to quit.")

    def on_event(self, event):
        if isinstance(event, WindowCloseRequested):
            print("Close requested.")
            self.quit()
        elif isinstance(event, WindowResized):
            print(f"Resized to {event.width}x{event.height}")

    def on_update(self, dt):
        self.elapsed += dt
        self.frames += 1

    def on_stop(self):
        average = self.elapsed / self.frames if self.frames else 0.0
        print(
            f"Ran {self.frames} frames in {self.elapsed:.1f}s "
            f"(average dt {average * 1000:.1f}ms). Goodbye."
        )


if __name__ == "__main__":
    run(WindowTest(), title="TrjoLudus — X11 Test", size=(800, 600))
