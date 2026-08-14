"""An animated object you drive with the mouse.

Run it from anywhere:

    python examples/animation_test.py

Hold the left mouse button to make the block walk: it animates and moves at
the same time. Let go and it goes back to a single still picture. Click the
right button to play a one-shot animation that stops on its last frame.

The frames are written to a temporary folder when the example starts, so it
needs no artwork of its own.

Two things worth noticing in the code below:

*   ``play("walk")`` is called every single update while the button is held,
    and the animation keeps progressing rather than restarting. That is what
    lets "while this is true, be walking" be written the obvious way.
*   Nothing switches animation by itself. The game says what is playing, and
    ``set.image()`` is what puts it back to a still picture.
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
    mouse,
    run,
)

FOLDER = Path(tempfile.mkdtemp(prefix="trjoludus-animation-"))
atexit.register(shutil.rmtree, FOLDER, ignore_errors=True)


def block(name, colour, size=48):
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


WALK = [block("walk_1", (250, 80, 80)), block("walk_2", (250, 160, 60)),
        block("walk_3", (250, 240, 60)), block("walk_4", (160, 250, 60))]
FLASH = [block("flash_1", (80, 160, 250)), block("flash_2", (140, 200, 250)),
         block("flash_3", (200, 230, 250)), block("flash_4", (250, 250, 250))]
STILL = block("still", (120, 120, 140))

WIDTH = 560


class AnimationTest(Game):
    def on_start(self):
        hud = draw.list("hud")
        hud.rect(0, 0, WIDTH, 24, color.blue)
        hud.text(8, 9, "Hold LEFT to walk.  RIGHT for a one-shot.",
                 color.white)
        self.readout = hud.text(8, 40, "", color.white)

        create.image(20, 100, STILL, "player")
        player = GameObject("player")
        player.animation.add("walk", WALK)
        player.animation.add("flash", FLASH)

    def on_event(self, event):
        if isinstance(event, WindowCloseRequested):
            self.quit()

    def on_update(self, dt):
        player = GameObject("player")

        if mouse.pressed("LEFT"):
            # Called every frame while the button is held. The animation
            # carries on rather than restarting, so this reads as "while the
            # button is down, be walking".
            player.animation.play("walk", fps=12, loop=True)
            player.move.x(120 * dt)
            if player.x > WIDTH:
                player.set.x(-48)
        elif mouse.pressed("RIGHT"):
            # Plays once and stops on its last frame.
            player.animation.play("flash", fps=8, loop=False)
        elif player.animation.is_playing:
            # Nothing switches by itself: putting it back to a still picture
            # is the game's decision, and it stops whatever was playing.
            player.set.image(STILL)

        state = player.animation.current or "nothing"
        playing = "playing" if player.animation.is_playing else "stopped"
        done = " (finished)" if player.animation.finished else ""
        self.readout.set.text(
            f"{state}: {playing}{done}   frame "
            f"{player.animation.frame}   x {player.x:.1f}")

    def on_stop(self):
        print("Goodbye.")


if __name__ == "__main__":
    run(AnimationTest(), title="TrjoLudus — Animation Test",
        size=(WIDTH, 220))
