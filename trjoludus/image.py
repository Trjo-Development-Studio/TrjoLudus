"""Images, and the minimum PNG decoding needed to load them.

TrjoLudus has no third-party dependencies, so PNG decoding is done here using
``zlib`` from the standard library. This is a deliberately small decoder: it
handles the 8-bit, non-interlaced PNGs that sprites are normally saved as, and
refuses anything else with a clear message rather than guessing.

**Pixels are stored as BGRA.** That looks arbitrary until you see where they
end up: an X11 ``ZPixmap`` on a little-endian TrueColor display expects blue,
green, red, unused -- and a 32-bit Windows DIB expects exactly the same order.
Decoding straight into that layout means presenting a frame is a memory copy on
both platforms instead of a per-pixel conversion, which in pure Python would
cost more than everything else in the frame put together.
"""

import zlib
from pathlib import Path

from trjoludus.errors import TrjoLudusError

__all__ = ["Image", "ImageError", "load_image"]

#: The 8 bytes every PNG file starts with.
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Samples per pixel for each PNG colour type.
_SAMPLES = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}

_COLOUR_TYPE_NAMES = {
    0: "greyscale",
    2: "truecolour",
    3: "indexed",
    4: "greyscale with alpha",
    6: "truecolour with alpha",
}


class ImageError(TrjoLudusError):
    """Raised when an image cannot be loaded or decoded."""


class Image:
    """Decoded pixel data, ready to be drawn.

    Attributes are read-only; an image is a loaded asset, not a canvas.

    Args:
        width: Width in pixels.
        height: Height in pixels.
        pixels: ``width * height * 4`` bytes in BGRA order.
    """

    __slots__ = ("_width", "_height", "_pixels", "_opaque")

    def __init__(self, width: int, height: int, pixels: bytes) -> None:
        expected = width * height * 4
        if len(pixels) != expected:
            raise ImageError(
                f"Image data is {len(pixels)} bytes but {width}x{height} "
                f"needs {expected}."
            )
        self._width = width
        self._height = height
        self._pixels = bytes(pixels)
        # Worth knowing once rather than per frame: a fully opaque image can be
        # drawn with whole-row copies instead of per-pixel alpha testing.
        self._opaque = all(pixels[i] == 255 for i in range(3, len(pixels), 4))

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def size(self) -> tuple[int, int]:
        """``(width, height)`` in pixels."""
        return (self._width, self._height)

    @property
    def pixels(self) -> bytes:
        """Raw BGRA bytes, row by row from the top."""
        return self._pixels

    @property
    def is_opaque(self) -> bool:
        """Whether every pixel is fully opaque."""
        return self._opaque

    def __repr__(self) -> str:
        return f"Image({self._width}x{self._height})"


def load_image(path) -> Image:
    """Load a PNG file.

    Args:
        path: Path to a PNG file.

    Raises:
        ImageError: If the file is missing, is not a PNG, or uses a PNG
            feature this decoder does not support.
    """
    file = Path(path)
    try:
        data = file.read_bytes()
    except FileNotFoundError:
        raise ImageError(f"No such image file: {file}") from None
    except OSError as exc:
        raise ImageError(f"Could not read image {file}: {exc}") from exc

    try:
        return decode_png(data)
    except ImageError as exc:
        raise ImageError(f"{file}: {exc}") from None


def decode_png(data: bytes) -> Image:
    """Decode PNG bytes into an :class:`Image`.

    Raises:
        ImageError: If the data is not a PNG this decoder supports.
    """
    if not data.startswith(PNG_SIGNATURE):
        raise ImageError(
            "not a PNG file (missing PNG signature). TrjoLudus loads PNG "
            "images; convert other formats to PNG first."
        )

    header = None
    palette = b""
    transparency = b""
    compressed = bytearray()

    offset = len(PNG_SIGNATURE)
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        offset += 12 + length  # length + type + body + CRC

        if kind == b"IHDR":
            header = _read_header(body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            transparency = body
        elif kind == b"IDAT":
            compressed += body
        elif kind == b"IEND":
            break

    if header is None:
        raise ImageError("PNG has no IHDR chunk")
    width, height, colour_type = header
    if not compressed:
        raise ImageError("PNG has no image data")

    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        raise ImageError(f"PNG image data is corrupt: {exc}") from exc

    samples = _SAMPLES[colour_type]
    rows = _unfilter(raw, width, height, samples)
    pixels = _to_bgra(rows, width, height, colour_type, palette, transparency)
    return Image(width, height, pixels)


def _read_header(body: bytes) -> tuple[int, int, int]:
    if len(body) < 13:
        raise ImageError("PNG header chunk is truncated")

    width = int.from_bytes(body[0:4], "big")
    height = int.from_bytes(body[4:8], "big")
    bit_depth = body[8]
    colour_type = body[9]
    interlace = body[12]

    if width == 0 or height == 0:
        raise ImageError(f"PNG has zero size ({width}x{height})")
    if bit_depth != 8:
        raise ImageError(
            f"{bit_depth}-bit PNGs are not supported; save the image as "
            f"8 bits per channel."
        )
    if colour_type not in _SAMPLES:
        raise ImageError(f"unknown PNG colour type {colour_type}")
    if interlace != 0:
        raise ImageError(
            "interlaced PNGs are not supported; save the image without "
            "Adam7 interlacing."
        )
    return width, height, colour_type


def _unfilter(raw: bytes, width: int, height: int, samples: int) -> bytes:
    """Reverse the per-scanline filters PNG applies before compression."""
    stride = width * samples
    expected = (stride + 1) * height
    if len(raw) < expected:
        raise ImageError(
            f"PNG pixel data is truncated: expected {expected} bytes, got "
            f"{len(raw)}"
        )

    out = bytearray(stride * height)
    previous = bytearray(stride)
    position = 0

    for row in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position:position + stride])
        position += stride

        if filter_type == 0:
            pass
        elif filter_type == 1:  # Sub
            for i in range(samples, stride):
                line[i] = (line[i] + line[i - samples]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = line[i - samples] if i >= samples else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = line[i - samples] if i >= samples else 0
                up = previous[i]
                up_left = previous[i - samples] if i >= samples else 0
                estimate = left + up - up_left
                da = abs(estimate - left)
                db = abs(estimate - up)
                dc = abs(estimate - up_left)
                if da <= db and da <= dc:
                    predictor = left
                elif db <= dc:
                    predictor = up
                else:
                    predictor = up_left
                line[i] = (line[i] + predictor) & 0xFF
        else:
            raise ImageError(f"unknown PNG filter type {filter_type}")

        out[row * stride:(row + 1) * stride] = line
        previous = line

    return bytes(out)


def _to_bgra(rows: bytes, width: int, height: int, colour_type: int,
             palette: bytes, transparency: bytes) -> bytes:
    """Convert decoded samples into the BGRA layout both backends present."""
    count = width * height
    out = bytearray(count * 4)

    if colour_type == 6:  # RGBA
        out[0::4] = rows[2::4]
        out[1::4] = rows[1::4]
        out[2::4] = rows[0::4]
        out[3::4] = rows[3::4]
    elif colour_type == 2:  # RGB
        out[0::4] = rows[2::3]
        out[1::4] = rows[1::3]
        out[2::4] = rows[0::3]
        out[3::4] = b"\xff" * count
    elif colour_type == 0:  # greyscale
        out[0::4] = rows
        out[1::4] = rows
        out[2::4] = rows
        out[3::4] = b"\xff" * count
    elif colour_type == 4:  # greyscale + alpha
        grey = rows[0::2]
        out[0::4] = grey
        out[1::4] = grey
        out[2::4] = grey
        out[3::4] = rows[1::2]
    elif colour_type == 3:  # indexed
        if not palette:
            raise ImageError("indexed PNG has no palette")
        entries = len(palette) // 3
        alpha = bytearray(b"\xff" * entries)
        alpha[:len(transparency)] = transparency
        for i, index in enumerate(rows[:count]):
            if index >= entries:
                raise ImageError("indexed PNG references a missing palette entry")
            source = index * 3
            target = i * 4
            out[target] = palette[source + 2]
            out[target + 1] = palette[source + 1]
            out[target + 2] = palette[source]
            out[target + 3] = alpha[index]
    else:  # pragma: no cover -- _read_header rejects anything else
        raise ImageError(
            f"unsupported PNG colour type {colour_type} "
            f"({_COLOUR_TYPE_NAMES.get(colour_type, 'unknown')})"
        )

    return bytes(out)
