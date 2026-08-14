"""The frame buffer the engine draws into.

This is the whole of TrjoLudus's rendering for now: a block of pixels the
engine composites images into, which a backend then puts on screen. There is
no GPU, no texture, and no draw-call ordering beyond "later objects cover
earlier ones".

It is platform-neutral. A :class:`Framebuffer` knows nothing about X11 or
Win32, and the backends know nothing about game objects -- they are handed
pixels and asked to show them.

Pixels are BGRA, matching :mod:`trjoludus.image`; see that module for why.

**This module is the engine's rendering boundary.** Everything above it deals
in objects, drawings and positions; everything below it deals in bytes. That
makes it the one piece a faster implementation would replace -- in Rust, in C,
or in Python that has actually been profiled -- without changing a line of the
public API, because nothing above it knows what is underneath.

A replacement has to keep three promises: pixels stay BGRA, tightly packed,
top row first (that is what makes presenting a frame a memcpy on both X11 and
Windows rather than a conversion); the drawing methods keep producing exactly
the same pixels, which ``tests/test_rendering.py`` and ``tests/test_ui.py``
pin down value by value; and nothing above this module learns what changed.
``ARCHITECTURE.md`` section 11 writes the contract out in full.

Nothing here has been optimised, because nothing has been measured. It is fast
enough for what has been built.
"""

from trjoludus import font

__all__ = ["Framebuffer"]

#: Bytes per pixel. BGRA.
BYTES_PER_PIXEL = 4

#: What a frame is cleared to before anything is drawn: opaque mid-grey. Dark
#: enough that a sprite stands out, light enough that a black window reads as
#: "nothing was drawn" rather than "the background".
DEFAULT_CLEAR_COLOUR = (40, 40, 48)


class Framebuffer:
    """A block of BGRA pixels covering the window's client area.

    Args:
        width: Width in pixels.
        height: Height in pixels.
    """

    __slots__ = ("_width", "_height", "_pixels")

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError(
                f"framebuffer size must be positive, got {width}x{height}"
            )
        self._width = width
        self._height = height
        self._pixels = bytearray(width * height * BYTES_PER_PIXEL)

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def size(self) -> tuple[int, int]:
        return (self._width, self._height)

    @property
    def pixels(self) -> bytearray:
        """The raw BGRA buffer, row by row from the top."""
        return self._pixels

    def resize(self, width: int, height: int) -> None:
        """Grow or shrink to a new size, discarding the contents."""
        if (width, height) == (self._width, self._height):
            return
        if width <= 0 or height <= 0:
            raise ValueError(
                f"framebuffer size must be positive, got {width}x{height}"
            )
        self._width = width
        self._height = height
        self._pixels = bytearray(width * height * BYTES_PER_PIXEL)

    def clear(self, colour: tuple[int, int, int] = DEFAULT_CLEAR_COLOUR) -> None:
        """Fill the whole buffer with one opaque colour."""
        red, green, blue = colour
        pattern = bytes((blue, green, red, 255))
        self._pixels[:] = pattern * (self._width * self._height)

    def set_pixel(self, x: int, y: int, colour) -> None:
        """Set one pixel, ignoring anything outside the buffer."""
        if not (0 <= x < self._width and 0 <= y < self._height):
            return
        red, green, blue = colour
        index = (y * self._width + x) * BYTES_PER_PIXEL
        self._pixels[index] = blue
        self._pixels[index + 1] = green
        self._pixels[index + 2] = red
        self._pixels[index + 3] = 255

    def fill_rect(self, x: int, y: int, width: int, height: int, colour) -> None:
        """Fill a rectangle, clipped to the buffer.

        A rectangle with no area draws nothing rather than being an error: a
        UI built from computed sizes will occasionally produce one, and it is
        not a mistake worth stopping for.
        """
        left = max(0, x)
        top = max(0, y)
        right = min(self._width, x + width)
        bottom = min(self._height, y + height)
        if left >= right or top >= bottom:
            return

        red, green, blue = colour
        row = bytes((blue, green, red, 255)) * (right - left)
        span = len(row)
        for line in range(top, bottom):
            start = (line * self._width + left) * BYTES_PER_PIXEL
            self._pixels[start:start + span] = row

    def draw_line(self, x: int, y: int, end_x: int, end_y: int, colour) -> None:
        """Draw a one-pixel line between two points, ends included.

        Bresenham's algorithm: it steps in whole pixels, so a line never has
        gaps and never needs floating point.

        The endpoints are put in a fixed order first. Bresenham is not
        symmetric on its own -- run from the other end, it rounds the other
        way and lights slightly different pixels -- and a line that changes
        depending on which end you name would be a surprise.
        """
        if (x, y) > (end_x, end_y):
            x, y, end_x, end_y = end_x, end_y, x, y

        dx = abs(end_x - x)
        dy = -abs(end_y - y)
        step_x = 1 if x < end_x else -1
        step_y = 1 if y < end_y else -1
        error = dx + dy

        while True:
            self.set_pixel(x, y, colour)
            if x == end_x and y == end_y:
                return
            doubled = 2 * error
            if doubled >= dy:
                error += dy
                x += step_x
            if doubled <= dx:
                error += dx
                y += step_y

    def draw_text(self, text: str, x: int, y: int, colour) -> None:
        """Draw one line of text with the built-in font.

        ``(x, y)`` is the top-left corner of the first character. Newlines are
        not handled here: a game draws each line where it wants it.
        """
        pen = x
        for character in text:
            for column, bits in enumerate(font.columns_for(character)):
                if not bits:
                    continue
                for row in range(font.CHARACTER_HEIGHT):
                    if bits & (1 << row):
                        self.set_pixel(pen + column, y + row, colour)
            pen += font.CHARACTER_WIDTH + font.SPACING

    def draw_image(self, image, x: int, y: int) -> None:
        """Composite an image with its top-left corner at ``(x, y)``.

        Anything falling outside the buffer is clipped, so an object may be
        partly or entirely off-screen without it being an error.

        Two paths, chosen by whether the image has any transparency. A fully
        opaque image is copied a row at a time, which is one slice assignment
        per row. A transparent one needs per-pixel work, so it is only done
        when the image actually calls for it.
        """
        source_width, source_height = image.width, image.height

        # Clip to the buffer, in image-local coordinates.
        left = max(0, -x)
        top = max(0, -y)
        right = min(source_width, self._width - x)
        bottom = min(source_height, self._height - y)
        if left >= right or top >= bottom:
            return

        source = image.pixels
        target = self._pixels
        span = (right - left) * BYTES_PER_PIXEL

        if image.is_opaque:
            for row in range(top, bottom):
                source_start = (row * source_width + left) * BYTES_PER_PIXEL
                target_start = (
                    (y + row) * self._width + x + left
                ) * BYTES_PER_PIXEL
                target[target_start:target_start + span] = (
                    source[source_start:source_start + span]
                )
            return

        for row in range(top, bottom):
            source_start = (row * source_width + left) * BYTES_PER_PIXEL
            target_start = ((y + row) * self._width + x + left) * BYTES_PER_PIXEL
            for column in range(right - left):
                s = source_start + column * BYTES_PER_PIXEL
                alpha = source[s + 3]
                if alpha == 0:
                    continue
                t = target_start + column * BYTES_PER_PIXEL
                if alpha == 255:
                    target[t:t + 4] = source[s:s + 4]
                    continue
                inverse = 255 - alpha
                target[t] = (source[s] * alpha + target[t] * inverse) // 255
                target[t + 1] = (
                    source[s + 1] * alpha + target[t + 1] * inverse
                ) // 255
                target[t + 2] = (
                    source[s + 2] * alpha + target[t + 2] * inverse
                ) // 255
                target[t + 3] = 255
