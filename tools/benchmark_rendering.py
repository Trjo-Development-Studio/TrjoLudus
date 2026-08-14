"""Time the two renderers on the same work.

    python tools/benchmark_rendering.py

Informational, and deliberately not a test: a number that varies with what
else the machine is doing has no business failing a build. What it is for is
answering "did that help?" with a measurement instead of an opinion.

Each case draws the same scene many times into the same size of buffer through
both renderers, and reports the time and the ratio. If Rust is not faster at
something, that is what it prints.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trjoludus.image import Image  # noqa: E402
from trjoludus.native import library, renderer  # noqa: E402
from trjoludus.rendering_python import Framebuffer  # noqa: E402

WIDTH, HEIGHT = 640, 480


def opaque_image(width, height):
    return Image(width, height, bytes([30, 90, 200, 255]) * (width * height))


def transparent_image(width, height):
    pixels = bytearray()
    for index in range(width * height):
        alpha = (0, 255, 128, 64)[index % 4]
        pixels += bytes([index % 251, (index * 7) % 251,
                         (index * 13) % 251, alpha])
    return Image(width, height, bytes(pixels))


SPRITE = opaque_image(64, 64)
GHOST = transparent_image(64, 64)


def clearing(buffer):
    buffer.clear((20, 30, 40))


def rectangles(buffer):
    for index in range(200):
        buffer.fill_rect(index % 60, index % 40, 40, 30,
                         (index % 250, 40, 200))


def lines(buffer):
    for index in range(200):
        buffer.draw_line(0, index % HEIGHT, WIDTH - 1,
                         (index * 7) % HEIGHT, (250, index % 250, 0))


def text(buffer):
    for index in range(60):
        buffer.draw_text("The quick brown fox jumps over it",
                         4, (index * 8) % HEIGHT, (250, 250, 250))


def images_opaque(buffer):
    for index in range(120):
        buffer.draw_image(SPRITE, (index * 13) % WIDTH, (index * 7) % HEIGHT)


def images_transparent(buffer):
    for index in range(120):
        buffer.draw_image(GHOST, (index * 13) % WIDTH, (index * 7) % HEIGHT)


def images_scaled(buffer):
    for index in range(60):
        buffer.draw_image(SPRITE, (index * 13) % WIDTH, (index * 7) % HEIGHT,
                          2.0)


def a_whole_frame(buffer):
    """What a modest game's frame actually looks like."""
    buffer.clear()
    for index in range(20):
        buffer.draw_image(SPRITE, (index * 31) % WIDTH, (index * 17) % HEIGHT)
    for index in range(10):
        buffer.draw_image(GHOST, (index * 57) % WIDTH, (index * 23) % HEIGHT)
    buffer.fill_rect(0, 0, WIDTH, 24, (20, 20, 60))
    buffer.draw_text("Score: 1234    Lives: 3", 8, 8, (250, 250, 250))
    buffer.draw_line(0, 26, WIDTH - 1, 26, (120, 120, 160))


CASES = (
    ("clear", clearing, 40),
    ("rectangles", rectangles, 20),
    ("lines", lines, 20),
    ("text", text, 20),
    ("images, opaque", images_opaque, 20),
    ("images, transparent", images_transparent, 10),
    ("images, scaled 2x", images_scaled, 10),
    ("a whole frame", a_whole_frame, 20),
)


def measure(make, work, rounds):
    """Best of three: the fastest run is the one least disturbed."""
    times = []
    for _ in range(3):
        buffer = make(WIDTH, HEIGHT)
        buffer.clear()
        start = time.perf_counter()
        for _ in range(rounds):
            work(buffer)
        times.append(time.perf_counter() - start)
    return min(times)


def main() -> int:
    library.forget()
    renderer.forget()
    if not renderer.available():
        print("No native renderer is built, so there is nothing to compare.")
        print("Run `cargo build --release` in rust/ and copy the library into")
        print("trjoludus/native/lib/. See rust/README.md.")
        return 1

    print(f"Frame buffer: {WIDTH}x{HEIGHT}. Best of three runs each.")
    print()
    print(f"{'case':<22}{'Python':>12}{'Rust':>12}{'ratio':>10}")
    print("-" * 56)

    total_python = total_rust = 0.0
    for name, work, rounds in CASES:
        python = measure(Framebuffer, work, rounds)
        rust = measure(renderer.NativeFramebuffer, work, rounds)
        total_python += python
        total_rust += rust
        ratio = python / rust if rust > 0 else float("inf")
        verdict = f"{ratio:.1f}x" if ratio >= 1 else f"{1 / ratio:.1f}x slower"
        print(f"{name:<22}{python * 1000:>10.1f}ms{rust * 1000:>10.1f}ms"
              f"{verdict:>10}")

    print("-" * 56)
    overall = total_python / total_rust if total_rust else float("inf")
    print(f"{'total':<22}{total_python * 1000:>10.1f}ms"
          f"{total_rust * 1000:>10.1f}ms"
          f"{f'{overall:.1f}x':>10}")
    print()
    print("Same pixels either way; the equivalence tests are what prove it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
