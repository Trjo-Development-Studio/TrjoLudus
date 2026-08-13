"""A button you can hover and click.

Run it from anywhere:

    python examples/button_test.py

Move the mouse over the button to make it grow, click it to count a press, and
click the small red square to quit.

Nothing is rebuilt here. Everything is drawn once in ``on_start`` and then
changed in place: each frame asks what the mouse is doing, adjusts a scale,
and writes a new number into the counter that is already on screen.
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

        self.counter = menu.text(20, 260, "Clicks: 0", color.white)
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
            self.presses += 1
            self.counter.set.text(f"Clicks: {self.presses}")
            # Warm the label up as the count grows, so a change of colour is
            # visible as well as a change of words.
            self.counter.set.color((250, max(0, 250 - self.presses * 25), 80))

        if self.quit_button.mouse.clicked():
            self.quit()

    def on_stop(self):
        print(f"Goodbye. The button was clicked {self.presses} times.")


if __name__ == "__main__":
    run(ButtonTest(), title="TrjoLudus — Button Test", size=(480, 320))
