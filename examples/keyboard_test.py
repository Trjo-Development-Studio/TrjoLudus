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

from trjoludus import (  # noqa: E402
    Game,
    GameObject,
    WindowCloseRequested,
    create,
    input,
    key,
    keyboard,
    run,
)

SPRITE = Path(__file__).resolve().parent / "assets" / "player.png"
STEP = 20


class KeyboardTest(Game):
    def on_start(self):
        create.image(200, 130, SPRITE, "player")
        self.player = GameObject("player")
        print("Press W A S D to move, Escape to quit.")

    def on_event(self, event):
        if isinstance(event, WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        keyboard.wait(input.key)

        if key == "W":
            self.player.move.y(-STEP)
        if key == "S":
            self.player.move.y(STEP)
        if key == "A":
            self.player.move.x(-STEP)
        if key == "D":
            self.player.move.x(STEP)
        if key == "ESCAPE":
            self.quit()

    def on_stop(self):
        print("Goodbye.")


if __name__ == "__main__":
    run(KeyboardTest(), title="TrjoLudus — Keyboard Test", size=(480, 320))
