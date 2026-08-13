"""Moving an object with the mouse.

Run it from anywhere:

    python examples/mouse_test.py

Click anywhere to send the player there. Right-click quits.

``mouse.wait`` waits for a *click*, not for movement -- otherwise it would
return the instant you nudged the mouse. The pointer position keeps updating
the whole time, so after a click ``mouse.x`` and ``mouse.y`` say where it
happened.
"""

import sys
from pathlib import Path

# Run straight from a checkout, without installing first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trjoludus import (  # noqa: E402
    Game,
    GameObject,
    WindowCloseRequested,
    color,
    create,
    draw,
    input,
    mouse,
    run,
)

SPRITE = Path(__file__).resolve().parent / "assets" / "player.png"


class MouseTest(Game):
    def on_start(self):
        create.image(200, 130, SPRITE, "player")
        self.player = GameObject("player")

        draw.rect(0, 0, 480, 24, color.blue)
        draw.text(8, 9, "Click to move. Right-click quits.", color.white)

        self.clicks = 0
        print("Click anywhere to move the player. Right-click quits.")

    def on_event(self, event):
        if isinstance(event, WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        mouse.wait(input.mouse)

        if mouse.button == "RIGHT":
            self.quit()
            return

        if mouse.button == "LEFT":
            # Centre the sprite on the click rather than putting its corner
            # there, which is what a player means by "go here".
            width, height = self.player.size
            self.player.x = mouse.x - width // 2
            self.player.y = mouse.y - height // 2
            self.clicks += 1

    def on_stop(self):
        print(f"Goodbye. You moved the player {self.clicks} times.")


if __name__ == "__main__":
    run(MouseTest(), title="TrjoLudus — Mouse Test", size=(480, 320))
