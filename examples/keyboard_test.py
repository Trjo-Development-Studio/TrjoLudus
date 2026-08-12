"""Moving an object with the keyboard.

Run it from anywhere:

    python examples/keyboard_test.py

Press W, A, S or D to move the player, and Escape to quit.

``keyboard.wait`` does exactly what it says: nothing else happens until a key
is pressed. That is why the player only moves on a key press rather than
gliding -- continuous movement needs a different shape, which is later work.
"""

import sys
from pathlib import Path

# Run straight from a checkout, without installing first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import trjoludus as tl  # noqa: E402

SPRITE = Path(__file__).resolve().parent / "assets" / "player.png"
STEP = 20


class KeyboardTest(tl.Game):
    def on_start(self):
        tl.create.image(200, 130, SPRITE, "player")
        self.player = tl.GameObject("player")
        print("Press W A S D to move, Escape to quit.")

    def on_event(self, event):
        if isinstance(event, tl.WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        tl.keyboard.wait(tl.input.key)

        if tl.key == "W":
            self.player.move.y(-STEP)
        if tl.key == "S":
            self.player.move.y(STEP)
        if tl.key == "A":
            self.player.move.x(-STEP)
        if tl.key == "D":
            self.player.move.x(STEP)
        if tl.key == "ESCAPE":
            self.quit()

    def on_stop(self):
        print("Goodbye.")


if __name__ == "__main__":
    tl.run(KeyboardTest(), title="TrjoLudus — Keyboard Test", size=(480, 320))
