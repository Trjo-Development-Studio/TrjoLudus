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

import os
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


def _opacity_of(pixels: bytes) -> bool:
    """Whether every pixel is fully opaque. The reference implementation.

    A scan of every alpha byte in the image, which is the single most
    expensive step of decoding a large PNG in Python -- more than
    unfiltering and colour conversion together, for an unfiltered one.
    """
    return all(pixels[index] == 255 for index in range(3, len(pixels), 4))


def opacity_of(pixels: bytes) -> bool:
    """Whether every pixel is fully opaque.

    Runs natively when a native implementation is available and the game has
    not asked for otherwise; otherwise :func:`_opacity_of`. Both give the same
    answer -- the differential tests are what prove it.
    """
    native, insisted = _backend()
    if native is not None:
        answer = native.opaque(pixels)
        if answer is not None:
            return answer
        # As in unfilter: falling back is what "auto" means, and is not what
        # "rust" means.
        if insisted:
            raise ImageError(
                "the native image implementation could not read this image's "
                "opacity, and image.engine is 'rust'. Set image.engine to "
                "'auto' to let TrjoLudus fall back to Python."
            )
    return _opacity_of(pixels)


class Image:
    """Decoded pixel data, ready to be drawn.

    Attributes are read-only; an image is a loaded asset, not a canvas.

    **Building one uses the chosen image backend.** Working out whether every
    pixel is opaque is image processing, so it runs wherever ``image.engine``
    says image processing runs. That means constructing an ``Image`` raises
    :class:`~trjoludus.native.registry.EngineError` when a game has set
    ``image.engine = "rust"`` and there is no native implementation -- the
    same as any other explicit request that cannot be honoured. It is
    deliberate: the alternative is a setting that applies to some image work
    and not the rest.

    Under ``"auto"``, which is the default, this cannot happen: there is
    always a Python implementation to fall back to.

    Args:
        width: Width in pixels.
        height: Height in pixels.
        pixels: ``width * height * 4`` bytes in BGRA order.

    Raises:
        ImageError: If ``pixels`` is not ``width * height * 4`` bytes.
        EngineError: If ``image.engine`` is ``"rust"`` and there is no native
            implementation.
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
        self._opaque = opacity_of(self._pixels)

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
    """Load a PNG file, decoding it once per run.

    A game asks for the same file more than once as a matter of course: an
    animation's frames are a list of paths, and switching an object's picture
    back and forth asks for each of them again. Decoded images are kept for
    the run and handed out again rather than decoded twice.

    That is safe because an :class:`Image` cannot be changed. Two objects
    sharing one is two objects looking at the same picture, which is what they
    asked for.

    **The spelling is looked up before the file is.** Asking again with the
    same string is a dictionary lookup and nothing else -- no filesystem call
    at all. Only a spelling that has not been seen is resolved, and if that
    resolves to something already loaded, the new spelling is remembered as
    another way of naming it. So ``"player.png"`` and its absolute path are
    one decoded image, and asking for either a second time costs nothing.

    **The cache is not invalidated.** If a file changes on disk during a run,
    the image already decoded from it stays. TrjoLudus does not watch files,
    and a game that wants the new one starts a new run. Everything a run loads
    is released when it finishes.

    Args:
        path: Path to a PNG file.

    Raises:
        ImageError: If the file is missing, is not a PNG, or uses a PNG
            feature this decoder does not support.
        EngineError: If ``image.engine`` is ``"rust"`` and there is no native
            implementation to decode with.
    """
    from trjoludus import engine

    cache = engine.current().resources

    # The spelling as given. A game asking twice asks with the same string,
    # so this is the case worth making fast.
    spelling = os.fspath(path)
    found = cache.get(spelling)
    if found is not None:
        return found

    file = Path(path)
    # A spelling not seen before. Resolve it, so that two ways of naming one
    # file are one decoded image rather than two.
    try:
        resolved = str(file.resolve())
    except OSError:                      # pragma: no cover -- unusual paths
        resolved = str(file)

    found = cache.get(resolved)
    if found is not None:
        cache[spelling] = found
        return found

    try:
        data = file.read_bytes()
    except FileNotFoundError:
        raise ImageError(f"No such image file: {file}") from None
    except OSError as exc:
        raise ImageError(f"Could not read image {file}: {exc}") from exc

    try:
        loaded = decode_png(data)
    except ImageError as exc:
        raise ImageError(f"{file}: {exc}") from None

    cache[resolved] = loaded
    if spelling != resolved:
        cache[spelling] = loaded
    return loaded


def loaded_images(state=None) -> int:
    """How many distinct images a run is holding.

    Not the number of keys: one image may be reachable by more than one
    spelling of its path. Engine-internal, for tests and the benchmark.
    """
    from trjoludus import engine

    resources = (engine.current() if state is None else state).resources
    return len({id(image) for image in resources.values()})


#: The largest a chunk may claim to be. PNG stores lengths in four bytes but
#: reserves the top bit, so anything above this is a broken file rather than a
#: big one -- and reading the length before trusting it is what stops a
#: corrupt number from being used as a slice.
_MAX_CHUNK = 0x7FFFFFFF


def _name(kind: bytes) -> str:
    """A chunk type as something readable, even when it is garbage."""
    try:
        return kind.decode("ascii")
    except UnicodeDecodeError:
        return repr(kind)


def decode_png(data: bytes) -> Image:
    """Decode PNG bytes into an :class:`Image`.

    Only what a game needs is supported: 8 bits per channel, no interlacing.
    Everything else is refused with a message saying how to re-save the file.

    Malformed input is refused rather than guessed at. Each chunk has to fit
    inside the file, claim a believable length, and match its own checksum,
    and the file has to start with IHDR and reach IEND. A file that fails any
    of those raises :class:`ImageError` instead of decoding whatever bytes
    happened to follow.

    Raises:
        ImageError: If the data is not a PNG this decoder supports, or is
            damaged.
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
    ended = False
    while not ended:
        # A chunk is a 4-byte length, a 4-byte type, the body, and a 4-byte
        # checksum. Anything less than a whole chunk is a truncated file, and
        # saying so beats decoding whatever happens to be there.
        left = len(data) - offset
        if left < 12:
            raise ImageError(
                f"PNG is truncated: {left} bytes left where a chunk should "
                f"start, and no IEND chunk was reached."
            )

        length = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8]
        if length > _MAX_CHUNK:
            raise ImageError(
                f"PNG chunk {_name(kind)} claims to be {length} bytes, which "
                f"is not a valid chunk length."
            )
        if not kind.isalpha():
            raise ImageError(
                f"PNG is malformed: expected a chunk type at byte {offset}, "
                f"found {kind!r}."
            )

        end = offset + 12 + length  # length + type + body + CRC
        if end > len(data):
            raise ImageError(
                f"PNG chunk {_name(kind)} runs past the end of the file: it "
                f"needs {end} bytes but the file has {len(data)}."
            )

        body = data[offset + 8:offset + 8 + length]
        stored = int.from_bytes(data[offset + 8 + length:end], "big")
        if zlib.crc32(kind + body) & 0xFFFFFFFF != stored:
            raise ImageError(
                f"PNG chunk {_name(kind)} is corrupt: its checksum does not "
                f"match its contents."
            )
        offset = end

        if header is None and kind != b"IHDR":
            raise ImageError(
                f"PNG does not start with an IHDR chunk (found "
                f"{_name(kind)}), so its size and colour type are unknown."
            )

        if kind == b"IHDR":
            header = _read_header(body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            transparency = body
        elif kind == b"IDAT":
            compressed += body
        elif kind == b"IEND":
            ended = True

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
    rows = unfilter(raw, width, height, samples)
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


def unfilter(raw: bytes, width: int, height: int, samples: int) -> bytes:
    """Reverse the per-scanline filters PNG applies before compression.

    Runs natively when a native implementation is available and the game has
    not asked for otherwise; otherwise :func:`_unfilter`. Both produce the
    same bytes -- the differential tests are what prove it -- and both raise
    the same errors, because the messages are raised here either way.

    This is the expensive half of decoding: Paeth filtering a 512x512 sprite
    takes the better part of a third of a second in Python.
    """
    native, insisted = _backend()
    if native is None:
        return _unfilter(raw, width, height, samples)

    stride = width * samples
    expected = (stride + 1) * height
    if len(raw) < expected:
        raise ImageError(
            f"PNG pixel data is truncated: expected {expected} bytes, got "
            f"{len(raw)}"
        )

    answer = native.unfilter(raw, width, height, samples)
    if answer.pixels is not None:
        return answer.pixels
    if answer.bad_filter is not None:
        raise ImageError(f"unknown PNG filter type {answer.bad_filter}")

    # Something the native side could not work with, and not one of the two
    # failures the Python implementation also has. Under "auto" that is a
    # reason to use Python; under "rust" it is not -- a game that asked for
    # the native implementation by name is entitled to hear that it did not
    # run, rather than to quietly get the other one.
    if insisted:
        raise ImageError(
            "the native image implementation could not unfilter this PNG, "
            "and image.engine is 'rust'. Set image.engine to 'auto' to let "
            "TrjoLudus fall back to Python, or to 'python' to use it always."
        )
    return _unfilter(raw, width, height, samples)


def _backend():
    """Which implementation to use, and whether it was insisted upon.

    Returns ``(native, insisted)``. ``native`` is the native module, or
    ``None`` to use Python's. ``insisted`` is true when the game asked for
    ``"rust"`` by name rather than leaving it to ``"auto"`` -- which decides
    whether a native failure may fall back or must be reported.

    Resolved once per operation and passed along, rather than asked again
    part-way through: two answers to one question is how a decode could start
    on one implementation and finish on the other.

    Raises:
        EngineError: If the game asked for ``"rust"`` and there is no native
            implementation. An explicit choice is never quietly replaced.
    """
    from trjoludus.native import PYTHON, RUST, registry

    system = registry.system("image")
    wanted = system.engine
    if wanted == PYTHON:
        return None, False
    if system.resolve() == PYTHON:
        return None, False

    from trjoludus.native import imaging

    return imaging, wanted == RUST


def _unfilter(raw: bytes, width: int, height: int, samples: int) -> bytes:
    """Reverse the per-scanline filters. The reference implementation."""
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


# --- backend ---------------------------------------------------------------
#
# Decoding a PNG is per-pixel work over the whole image: unfiltering every
# scanline and turning samples into BGRA. That is the shape of thing a native
# implementation does far faster, so image processing is an always-native
# system -- ``"auto"`` will prefer Rust once there is a Rust decoder. Nothing
# a game writes changes when that happens: ``create.image(...)`` takes a path
# either way.

from trjoludus.native import RUST, expose  # noqa: E402

#: What a game has asked for: ``"auto"``, ``"rust"`` or ``"python"``.
engine: str

expose(__name__, recommends=RUST,
       python_implementation="trjoludus.image")
