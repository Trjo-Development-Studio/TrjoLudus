"""The first TrjoLudus window with something drawn in it.

Run it from anywhere:

    python examples/image_test.py

`create.image` creates an object that *stays*: it is called once, and the engine
draws it every frame until it is removed. Coordinates are pixels from the
top-left corner of the window, and they place the image's top-left corner.
"""

import sys
from pathlib import Path

# Run straight from a checkout, without installing first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import trjoludus as tl  # noqa: E402

SPRITE = Path(__file__).resolve().parent / "assets" / "player.png"


class ImageTest(tl.Game):
    def on_start(self):
        tl.create.image(120, 90, SPRITE, "player")
        self.player = tl.GameObject("player")
        self.direction = 1
        print(f"Created {self.player.name!r} at {self.player.position}, "
              f"{self.player.size[0]}x{self.player.size[1]} pixels.")
        print("Close the window to quit.")

    def on_event(self, event):
        if isinstance(event, tl.WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        # Relative movement: each call shifts the object from where it is now.
        self.player.move.x(2 * self.direction)
        if not 40 <= self.player.x <= 380:
            self.direction = -self.direction

    def on_stop(self):
        print(f"Goodbye. The player ended at {self.player.position}.")


if __name__ == "__main__":
    tl.run(ImageTest(), title="TrjoLudus — Image Test", size=(480, 320))
