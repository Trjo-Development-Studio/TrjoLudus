"""The native renderer, seen from Python.

A :class:`NativeFramebuffer` is a drop-in replacement for
:class:`trjoludus.rendering_python.Framebuffer`. Same methods, same arguments,
same pixels. Nothing above it knows which one it has, which is the whole point
of the exercise.

**Python owns the pixels.** The buffer is an ordinary ``bytearray``, allocated
here and freed by Python when this object goes. Every native call borrows a
pointer to it for the length of that one call and keeps nothing. Nothing is
allocated natively, so there is nothing for Python to free and nothing to
leak -- the simplest ownership rule there is, and the reason this file has no
teardown.

It also means :attr:`pixels` is the same ``bytearray`` the Python renderer
hands out. A backend presenting a frame, or a test reading one, cannot tell
the difference.

**Rounding happens here.** Every coordinate is rounded on this side and
crosses as a whole number, and a scaled image's size is worked out here too.
Python rounds half to even; Rust rounds half away from zero. Rounding on both
sides would put about one position in two hundred on a different pixel.
"""

import ctypes

from trjoludus import font
from trjoludus.errors import TrjoLudusError
from trjoludus.native import library

__all__ = ["NativeFramebuffer", "RenderingError", "available"]

#: Bytes per pixel. BGRA, as everywhere else.
BYTES_PER_PIXEL = 4

#: What the native side answers with. Anything but ``OK`` becomes an
#: exception: a frame that failed must never look like a frame that worked.
STATUS_OK = 0
_STATUS_MEANINGS = {
    -1: "a buffer pointer was null",
    -2: "the frame buffer was not the size it said it was",
    -3: "the native renderer failed while drawing",
}

#: The rendering functions, with explicit ``argtypes`` and ``restype``. The
#: same table discipline the platform layer uses: leaving ``restype`` alone
#: makes ctypes assume ``int``, which truncates a 64-bit value and takes the
#: next call with it.
_BUFFER = ctypes.POINTER(ctypes.c_ubyte)
#: Read-only data crosses as ``char *``. Passing a ``bytes`` to one of these
#: hands over a pointer to the object's own buffer -- no copy, no allocation,
#: whatever the size. Wrapping it in an array type instead copied the whole
#: image on every draw call, which is 7 microseconds for a 256 KB sprite and
#: happens once per object per frame.
_READONLY = ctypes.c_char_p
_SIZE = ctypes.c_size_t
_INT = ctypes.c_int64
_BYTE = ctypes.c_uint8

FUNCTION_SIGNATURES = {
    "trjoludus_render_clear": (
        [_BUFFER, _SIZE, _INT, _INT, _BYTE, _BYTE, _BYTE], ctypes.c_int),
    "trjoludus_render_set_pixel": (
        [_BUFFER, _SIZE, _INT, _INT, _INT, _INT, _BYTE, _BYTE, _BYTE],
        ctypes.c_int),
    "trjoludus_render_fill_rect": (
        [_BUFFER, _SIZE, _INT, _INT, _INT, _INT, _INT, _INT,
         _BYTE, _BYTE, _BYTE], ctypes.c_int),
    "trjoludus_render_draw_line": (
        [_BUFFER, _SIZE, _INT, _INT, _INT, _INT, _INT, _INT,
         _BYTE, _BYTE, _BYTE], ctypes.c_int),
    "trjoludus_render_draw_glyphs": (
        [_BUFFER, _SIZE, _INT, _INT, _READONLY, _SIZE, _INT, _INT, _INT,
         _INT, _INT, _BYTE, _BYTE, _BYTE], ctypes.c_int),
    "trjoludus_render_draw_image": (
        [_BUFFER, _SIZE, _INT, _INT, _READONLY, _SIZE, _INT, _INT,
         ctypes.c_int, _INT, _INT], ctypes.c_int),
    "trjoludus_render_draw_image_scaled": (
        [_BUFFER, _SIZE, _INT, _INT, _READONLY, _SIZE, _INT, _INT,
         _INT, _INT, _INT, _INT], ctypes.c_int),
}


class RenderingError(TrjoLudusError):
    """Raised when the renderer could not draw what it was asked to.

    A native failure becomes one of these rather than a status code nobody
    reads. The frame is not silently accepted as drawn: whatever went wrong
    reaches the game as an exception with a sentence about it.
    """


def available() -> bool:
    """Whether a native renderer can be used right now.

    True only when a library is loaded, it says it implements rendering, and
    every function this module needs is actually in it. A library that claims
    rendering but is missing a function would fail on the first frame, which
    is a worse place to find out.
    """
    if not library.implements("rendering"):
        return False
    return _functions() is not None


_prepared = None


def _functions():
    """The rendering functions, with their signatures applied. Once."""
    global _prepared
    if _prepared is not None and _prepared[0] is library.handle():
        return _prepared[1]

    handle = library.handle()
    if handle is None:
        return None

    found = {}
    for name, (argtypes, restype) in FUNCTION_SIGNATURES.items():
        try:
            function = getattr(handle, name)
        except AttributeError:
            return None
        function.argtypes = argtypes
        function.restype = restype
        found[name] = function

    _prepared = (handle, found)
    return found


def forget() -> None:
    """Engine-internal: look the functions up again next time.

    Paired with :func:`trjoludus.native.library.forget`, for tests that swap
    one library for another.
    """
    global _prepared
    _prepared = None


class NativeFramebuffer:
    """A block of BGRA pixels drawn into by the native renderer.

    The same surface as :class:`trjoludus.rendering_python.Framebuffer`, and
    the same pixels. Only the code between the call and the bytes is
    different.

    Args:
        width: Width in pixels.
        height: Height in pixels.

    Raises:
        RenderingError: If there is no native renderer to draw with.
        ValueError: If the size is not positive.
    """

    __slots__ = ("_width", "_height", "_pixels", "_view", "_call")

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError(
                f"framebuffer size must be positive, got {width}x{height}"
            )
        functions = _functions()
        if functions is None or not library.implements("rendering"):
            reason = library.problem() or (
                "The native library implements no renderer.")
            raise RenderingError(
                f"there is no native renderer available. {reason}")
        self._call = functions
        self._width = width
        self._height = height
        self._pixels = bytearray(width * height * BYTES_PER_PIXEL)
        self._view = self._borrow(self._pixels)

    @staticmethod
    def _borrow(buffer):
        """A pointer into a bytearray, without copying it.

        ``from_buffer`` shares the memory rather than duplicating it, so the
        native side writes into the very bytes a backend will present. The
        view is kept for the life of this object because the buffer is too.
        """
        return (ctypes.c_ubyte * len(buffer)).from_buffer(buffer)

    # --- the same surface the Python renderer has -------------------------

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
        # A new buffer rather than a resized one: ctypes holds an exported
        # pointer into the old bytes, and a bytearray cannot be resized while
        # that exists. Releasing the old view first is what makes it possible.
        self._view = None
        self._pixels = bytearray(width * height * BYTES_PER_PIXEL)
        self._view = self._borrow(self._pixels)

    def clear(self, colour=None) -> None:
        """Fill the whole buffer with one opaque colour."""
        from trjoludus.rendering_python import DEFAULT_CLEAR_COLOUR

        red, green, blue = DEFAULT_CLEAR_COLOUR if colour is None else colour
        self._check(self._call["trjoludus_render_clear"](
            self._view, len(self._pixels), self._width, self._height,
            red, green, blue))

    def set_pixel(self, x, y, colour) -> None:
        """Set one pixel, ignoring anything outside the buffer."""
        red, green, blue = colour
        self._check(self._call["trjoludus_render_set_pixel"](
            self._view, len(self._pixels), self._width, self._height,
            round(x), round(y), red, green, blue))

    def fill_rect(self, x, y, width: int, height: int, colour) -> None:
        """Fill a rectangle, clipped to the buffer."""
        red, green, blue = colour
        self._check(self._call["trjoludus_render_fill_rect"](
            self._view, len(self._pixels), self._width, self._height,
            round(x), round(y), width, height, red, green, blue))

    def draw_line(self, x, y, end_x, end_y, colour) -> None:
        """Draw a one-pixel line between two points, ends included."""
        red, green, blue = colour
        self._check(self._call["trjoludus_render_draw_line"](
            self._view, len(self._pixels), self._width, self._height,
            round(x), round(y), round(end_x), round(end_y),
            red, green, blue))

    def draw_text(self, text: str, x, y, colour) -> None:
        """Draw one line of text with the built-in font.

        The font is not sent across as a font. Each character's five column
        bytes are looked up here, in :mod:`trjoludus.font`, and the whole
        string's worth goes over as one buffer -- so there is one font in
        TrjoLudus rather than a copy on each side that could drift.
        """
        if not text:
            return
        columns = bytearray()
        for character in text:
            columns += font.columns_for(character)

        red, green, blue = colour
        self._check(self._call["trjoludus_render_draw_glyphs"](
            self._view, len(self._pixels), self._width, self._height,
            bytes(columns), len(columns),
            font.CHARACTER_WIDTH, font.CHARACTER_HEIGHT,
            font.CHARACTER_WIDTH + font.SPACING,
            round(x), round(y), red, green, blue))

    def draw_image(self, image, x, y, scale: float = 1.0) -> None:
        """Composite an image with its top-left corner at ``(x, y)``.

        The image's pixels are borrowed for the call; nothing is copied and
        nothing is kept. The scaled size is worked out here so that only one
        rounding rule exists.
        """
        x, y = round(x), round(y)
        # image.pixels is bytes, and bytes are immutable, so lending the
        # native side a pointer to them for one call is safe by construction.
        source = image.pixels

        if scale != 1.0:
            target_width = round(image.width * scale)
            target_height = round(image.height * scale)
            self._check(self._call["trjoludus_render_draw_image_scaled"](
                self._view, len(self._pixels), self._width, self._height,
                source, len(image.pixels), image.width, image.height,
                x, y, target_width, target_height))
            return

        self._check(self._call["trjoludus_render_draw_image"](
            self._view, len(self._pixels), self._width, self._height,
            source, len(image.pixels), image.width, image.height,
            1 if image.is_opaque else 0, x, y))

    # --- failures ---------------------------------------------------------

    def _check(self, status: int) -> None:
        """Turn a status code into an exception, or nothing at all."""
        if status == STATUS_OK:
            return
        raise RenderingError(
            f"the native renderer refused to draw: "
            f"{_STATUS_MEANINGS.get(status, f'unknown status {status}')}. "
            f"Set rendering.engine = \"python\" to use the Python renderer "
            f"while this is looked into."
        )

    def __repr__(self) -> str:
        return f"NativeFramebuffer({self._width}x{self._height})"
