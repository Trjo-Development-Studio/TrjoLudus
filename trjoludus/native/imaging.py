"""The two expensive parts of decoding a PNG, done natively.

**A game never imports this.** Loading a PNG is still
:func:`trjoludus.image.load_image`, and whether these functions were used is
not visible from anywhere above it.

Not a decoder. Python still walks the chunks, checks lengths and checksums,
runs zlib and expands palettes. What crosses here is the two loops that touch
every byte -- unfiltering the scanlines, and asking whether every pixel is
opaque -- because those are where the time measurably went.

**Python owns the buffers.** The output of unfiltering is a ``bytearray``
allocated here and lent for the length of one call; the native side allocates
nothing and keeps nothing. The same rule the renderer and the world view
follow.
"""

import ctypes

from trjoludus.native import library

__all__ = ["available", "opaque", "unfilter"]

STATUS_OK = 0
STATUS_SHORT_DATA = -5
STATUS_BAD_FILTER = -6

_BYTES = ctypes.c_char_p
_OUT = ctypes.POINTER(ctypes.c_ubyte)
_SIZE = ctypes.c_size_t

FUNCTION_SIGNATURES = {
    "trjoludus_image_unfilter": (
        [_BYTES, _SIZE, _OUT, _SIZE, _SIZE, _SIZE, _SIZE,
         ctypes.POINTER(ctypes.c_int32)], ctypes.c_int),
    "trjoludus_image_opaque": (
        [_BYTES, _SIZE, ctypes.POINTER(ctypes.c_int)], ctypes.c_int),
}

_prepared = None


def _functions():
    """The image functions, with their signatures applied. Once."""
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
    """Engine-internal: look the functions up again next time."""
    global _prepared
    _prepared = None


def available() -> bool:
    """Whether native image decoding can be used right now.

    The library saying it implements images is necessary but not enough: a
    library missing one of the two functions would fail on the first PNG,
    which is a worse place to find out.
    """
    if not library.implements("image"):
        return False
    return _functions() is not None


class Unfiltered:
    """What :func:`unfilter` answers with.

    Either the bytes, or which filter byte was wrong, or that there was not
    enough data. Python turns those into the messages it has always raised --
    the wording belongs there, with the file name and the rest of the context.
    """

    __slots__ = ("pixels", "bad_filter", "short")

    def __init__(self, pixels=None, bad_filter=None, short=False):
        self.pixels = pixels
        self.bad_filter = bad_filter
        self.short = short


def unfilter(raw: bytes, width: int, height: int, samples: int) -> Unfiltered:
    """Reverse PNG's per-scanline filters.

    Returns an :class:`Unfiltered`. The caller raises; this reports.
    """
    functions = _functions()
    if functions is None:  # pragma: no cover -- callers check available()
        raise RuntimeError("no native image implementation")

    stride = width * samples
    out = bytearray(stride * height)
    view = (ctypes.c_ubyte * len(out)).from_buffer(out)
    found = ctypes.c_int32(-1)

    status = functions["trjoludus_image_unfilter"](
        raw, len(raw), view, len(out), width, height, samples,
        ctypes.byref(found))

    if status == STATUS_OK:
        return Unfiltered(pixels=bytes(out))
    if status == STATUS_BAD_FILTER:
        return Unfiltered(bad_filter=found.value)
    if status == STATUS_SHORT_DATA:
        return Unfiltered(short=True)
    # Anything else is a size that could not describe an image, which the
    # caller has already checked; treat it as too little data rather than
    # inventing a new kind of failure.
    return Unfiltered(short=True)


def opaque(pixels: bytes) -> "bool | None":
    """Whether every pixel is fully opaque, or ``None`` if it cannot say.

    ``None`` when the data is not a whole number of BGRA pixels, which
    :class:`~trjoludus.image.Image` has already refused -- so the caller falls
    back rather than raising something new.
    """
    functions = _functions()
    if functions is None:  # pragma: no cover -- callers check available()
        return None

    answer = ctypes.c_int(-1)
    status = functions["trjoludus_image_opaque"](
        pixels, len(pixels), ctypes.byref(answer))
    if status != STATUS_OK:
        return None
    return bool(answer.value)
