"""Driving something with held keys, and animating while it moves.

Run it from anywhere:

    python examples/keyboard_state_test.py

Hold W, A, S or D to move the block around; it walks while it is moving and
goes still when you let go. Hold two directions at once and it moves
diagonally. Press ESCAPE to quit.

This is the pattern `keyboard.pressed()` exists for:

    if keyboard.pressed("W"):
        player.animation.play("walk", fps=12)
        player.move.y(-100 * time.delta)
    else:
        player.set.image("idle.png")

`pressed()` is *held state* -- true for as long as the key is down, on every
frame, and reading it consumes nothing. `keyboard.wait()` is the other thing
entirely: it blocks until a key arrives and hands that press out once. This
example never calls it, because a game that has to keep moving cannot stop and
wait.
"""

import atexit
import shutil
import struct
import sys
import tempfile
import zlib
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
    keyboard,
    run,
    time,
)

FOLDER = Path(tempfile.mkdtemp(prefix="trjoludus-keys-"))
atexit.register(shutil.rmtree, FOLDER, ignore_errors=True)

WIDTH, HEIGHT = 640, 400
SPEED = 220


def block(name, colour, size=40):
    """Write a solid-colour PNG and return its path."""
    red, green, blue = colour
    rows = b"".join(b"\x00" + bytes([red, green, blue, 255]) * size
                    for _ in range(size))

    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    path = FOLDER / f"{name}.png"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b""))
    return str(path)


WALK = [block("walk_1", (250, 120, 90)), block("walk_2", (250, 180, 90)),
        block("walk_3", (250, 230, 110)), block("walk_4", (200, 250, 130))]
STILL = block("still", (130, 130, 150))


class KeyboardStateTest(Game):
    def on_start(self):
        hud = draw.list("hud")
        hud.rect(0, 0, WIDTH, 24, color.blue)
        hud.text(8, 9, "Hold W A S D to move.  ESCAPE quits.", color.white)
        self.readout = hud.text(8, 40, "", color.white)

        create.image(WIDTH // 2, HEIGHT // 2, STILL, "player")
        GameObject("player").animation.add("walk", WALK)

    def on_event(self, event):
        if isinstance(event, WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        if keyboard.pressed("ESCAPE"):
            self.quit()
            return

        player = GameObject("player")

        # Several keys at once: each is its own question, and both directions
        # can be true, which is what makes diagonal movement work.
        left = keyboard.pressed("A")
        right = keyboard.pressed("D")
        up = keyboard.pressed("W")
        down = keyboard.pressed("S")

        step = SPEED * time.delta
        if left:
            player.move.x(-step)
        if right:
            player.move.x(step)
        if up:
            player.move.y(-step)
        if down:
            player.move.y(step)

        if left or right or up or down:
            # Called every frame while a key is held. The animation carries on
            # rather than restarting, so this reads as "while moving, walk".
            player.animation.play("walk", fps=12, loop=True)
        elif player.animation.is_playing:
            # Nothing switches by itself: standing still is the game's call.
            player.set.image(STILL)

        # Stay on screen.
        player.set.x(max(0, min(WIDTH - 40, player.x)))
        player.set.y(max(24, min(HEIGHT - 40, player.y)))

        held = [name for name in ("W", "A", "S", "D")
                if keyboard.pressed(name)]
        self.readout.set.text(
            f"held: {' '.join(held) or 'nothing'}    "
            f"at {player.x:.0f}, {player.y:.0f}")


if __name__ == "__main__":
    run(KeyboardStateTest(), title="TrjoLudus — Keyboard State Test",
        size=(WIDTH, HEIGHT))
