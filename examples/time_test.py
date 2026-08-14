"""Movement measured in seconds, and a frame-rate readout.

Run it from anywhere:

    python examples/time_test.py
    python examples/time_test.py 10      # ...and again at 10 frames a second

Two squares cross the window. The blue one moves a fixed amount every frame;
the green one moves a fixed amount every *second*, using ``time.delta``.

Run it twice, once with a frame-rate cap and once without, and watch what
happens: the blue square changes speed with the frame rate, and the green one
does not. That is the whole point of ``delta``.

Close the window to quit.
"""

import sys
from pathlib import Path

# Run straight from a checkout, without installing first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trjoludus import (  # noqa: E402
    Game,
    WindowCloseRequested,
    color,
    draw,
    run,
    time,
)

WIDTH = 640


class TimeTest(Game):
    def on_start(self):
        hud = draw.list("hud")
        hud.rect(0, 0, WIDTH, 24, color.blue)
        hud.text(8, 9, "Close the window to quit.", color.white)

        self.readout = hud.text(8, 40, "fps: --", color.white)

        # The same speed, measured two different ways.
        self.per_frame = hud.rect(0, 100, 40, 40, color.blue)
        self.per_second = hud.rect(0, 160, 40, 40, color.green)
        hud.text(56, 114, "3 pixels per frame", color.white)
        hud.text(56, 174, "200 pixels per second", color.white)

        # Waiting does not freeze the window: the frame drawn before the first
        # update is already on screen, and the window still answers the desktop
        # while this runs.
        time.wait(0.5)

        self.since_readout = 0.0

    def on_event(self, event):
        if isinstance(event, WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        # 200 pixels a second, whatever the frame rate. The fraction of a
        # pixel this is worth in one frame is kept, not lost or rounded up.
        self.per_second.move.x(200 * time.delta)
        # A fixed step: twice as fast when there are twice as many frames.
        self.per_frame.move.x(3)

        for box in (self.per_frame, self.per_second):
            if box.x > WIDTH:
                box.set.x(-40)

        # fps jumps about from frame to frame, so only refresh what is shown a
        # few times a second. Reading it more often would be a blur of digits.
        self.since_readout += time.delta
        if self.since_readout > 0.25:
            self.since_readout = 0.0
            self.readout.set.text(f"fps: {round(time.fps)}")

    def on_stop(self):
        print("Goodbye.")


if __name__ == "__main__":
    cap = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    run(TimeTest(), title=f"TrjoLudus — Time Test ({cap:g} fps)",
        size=(WIDTH, 240), max_fps=cap)
