"""Drawing a small user interface.

Run it from anywhere:

    python examples/ui_test.py

Press SPACE to show and hide the menu, and Escape to quit.

Everything drawn here is drawn once, in ``on_start``. The engine remembers it
and draws it every frame, so ``on_update`` only has to decide what should be
visible -- not repaint anything.
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
    key,
    keyboard,
    run,
)

SPRITE = Path(__file__).resolve().parent / "assets" / "player.png"


class UiTest(Game):
    def on_start(self):
        create.image(60, 150, SPRITE, "player")
        self.player = GameObject("player")

        # A status bar, drawn without a list: it is always on screen.
        draw.rect(0, 0, 480, 24, color.blue)
        draw.text(8, 9, "TrjoLudus UI", color.white)
        draw.line(0, 24, 479, 24, color.white)

        # A menu, drawn into a named list so it can be shown and hidden.
        self.menu = draw.list("menu")
        self.menu.rect(150, 90, 180, 90, color.gray)
        self.menu.rect(154, 94, 172, 82, color.black)
        self.menu.text(170, 110, "PAUSED", color.white)
        self.menu.text(162, 140, "SPACE resumes", color.cyan)
        self.menu.hide()

        self.paused = False
        print("SPACE toggles the menu, Escape quits.")

    def on_event(self, event):
        if isinstance(event, WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        keyboard.wait()

        if key == "SPACE":
            self.paused = not self.paused
            self.menu.show() if self.paused else self.menu.hide()
        if key == "D":
            self.player.move.x(20)
        if key == "A":
            self.player.move.x(-20)
        if key == "ESCAPE":
            self.quit()

    def on_stop(self):
        print("Goodbye.")


if __name__ == "__main__":
    run(UiTest(), title="TrjoLudus — UI Test", size=(480, 320))
