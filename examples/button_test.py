"""A button you can hover and click.

Run it from anywhere:

    python examples/button_test.py

Move the mouse over the button to make it grow, click it to count a press, and
click the small red square to quit.

Nothing is repainted here. The buttons are drawn once in ``on_start``; each
frame only asks what the mouse is doing and adjusts a scale.
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
)


class ButtonTest(Game):
    def on_start(self):
        menu = draw.list("menu")
        menu.rect(0, 0, 480, 24, color.blue)
        menu.text(8, 9, "Hover the button. Red square quits.", color.white)

        self.play = menu.rect(160, 120, 160, 60, color.gray)
        self.label = menu.text(196, 143, "PLAY", color.white)
        self.quit_button = menu.rect(430, 260, 30, 30, color.red)

        # A row of lamps: one lights up per click. Changing a drawing's text
        # after it is made is not something TrjoLudus can do yet, so the count
        # is shown by revealing things that were drawn up front.
        self.lamps = [
            menu.rect(20 + index * 24, 260, 16, 16, color.yellow).hide()
            for index in range(8)
        ]
        self.presses = 0

    def on_event(self, event):
        if isinstance(event, WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        # Grow while hovered, back to normal when not.
        if self.play.mouse.hover():
            self.play.set.scale(1.1)
        else:
            self.play.set.scale(1.0)

        if self.play.mouse.clicked():
            if self.presses < len(self.lamps):
                self.lamps[self.presses].show()
            self.presses += 1

        if self.quit_button.mouse.clicked():
            self.quit()

    def on_stop(self):
        print(f"Goodbye. The button was clicked {self.presses} times.")


if __name__ == "__main__":
    run(ButtonTest(), title="TrjoLudus — Button Test", size=(480, 320))
