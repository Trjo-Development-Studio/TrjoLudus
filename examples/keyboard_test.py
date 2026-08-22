"""Moving an object with the keyboard.

Run it from anywhere:

    python examples/keyboard_test.py

Press W, A, S or D to move the player, and Escape to quit.

``keyboard.wait`` does exactly what it says: nothing else happens until a key
is pressed, and it hands back the key it took. That is why the player steps
rather than glides. For continuous movement, ask ``keyboard.pressed`` inside
an ordinary update instead -- ``keyboard_state_test.py`` does that.
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
    keyboard,
    run,
)

SPRITE = Path(__file__).resolve().parent / "assets" / "player.png"
STEP = 20


class KeyboardTest(Game):
    def on_start(self):
        self.player = create.image(200, 130, SPRITE, "player")
        print("Press W A S D to move, Escape to quit.")

    def on_event(self, event):
        if isinstance(event, WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        pressed_key = keyboard.wait()

        if pressed_key == "W":
            self.player.move.y(-STEP)
        if pressed_key == "S":
            self.player.move.y(STEP)
        if pressed_key == "A":
            self.player.move.x(-STEP)
        if pressed_key == "D":
            self.player.move.x(STEP)
        if pressed_key == "ESCAPE":
            self.quit()

    def on_stop(self):
        print("Goodbye.")


if __name__ == "__main__":
    run(KeyboardTest(), title="TrjoLudus — Keyboard Test", size=(480, 320))
