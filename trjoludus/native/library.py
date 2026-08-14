"""Finding and loading the native library, if there is one.

This is the only place in TrjoLudus that talks to compiled code that is not
the operating system, and it is deliberately small. It answers one question --
*is there a native implementation of this subsystem?* -- and holds the handle
that the implementations themselves will use.

**Nothing here is required.** TrjoLudus is a Python engine that can use a
native library, not a Python wrapper around one. With no library present
every subsystem falls back to Python, which is exactly what happens today.

**The boundary is a C ABI, not a Python extension.** The library exports plain
C functions, loaded with :mod:`ctypes` the same way the X11 and Win32 backends
load the system libraries. That keeps TrjoLudus free of build-time coupling to
a particular Python version, keeps the engine installable as pure Python when
no library is built, and means the same library would be loadable from
anything with a C FFI. Every function gets explicit ``argtypes`` **and**
``restype``, for the same reason the platform layer does: leaving ``restype``
alone truncates a 64-bit pointer to an int and the next call segfaults.

**Work crosses the boundary in bulk.** The point of a native subsystem is that
it does a great deal before returning -- a whole frame, a whole broad-phase
pass -- rather than being called once per pixel or per entity. Nothing here
calls back into Python.
"""

import ctypes
from pathlib import Path

__all__ = ["ABI_VERSION", "implements", "library_path", "loaded", "version"]

#: The ABI this version of TrjoLudus speaks. A library built for a different
#: one is refused rather than called: the alternative is calling a function
#: whose arguments have moved, which is a crash with no explanation.
ABI_VERSION = 1

#: Where a built library is looked for, in order. Several names rather than a
#: branch on the host operating system: only one of them will exist, and
#: asking the filesystem is cheaper than deciding who we are.
LIBRARY_NAMES = (
    "libtrjoludus_native.so",
    "trjoludus_native.dll",
    "libtrjoludus_native.dylib",
)

#: The functions the library must export, with their signatures. The same
#: table-of-signatures discipline the platform layer uses.
FUNCTION_SIGNATURES = {
    # The ABI this library was built against.
    "trjoludus_abi_version": ([], ctypes.c_uint32),
    # Whether the library implements one named subsystem. The name is ASCII,
    # NUL-terminated, and belongs to the caller.
    "trjoludus_implements": ([ctypes.c_char_p], ctypes.c_int),
}


class _NotLoaded:
    """Stands in for a library that is not there.

    A sentinel rather than ``None`` so that "we have not looked yet" and "we
    looked and there is nothing" are different states, and the search happens
    once rather than on every question.
    """

    __slots__ = ()


_UNSEARCHED = _NotLoaded()

#: The loaded library, ``None`` if there is none, or the sentinel if the
#: search has not happened yet.
_library = _UNSEARCHED

#: Where the loaded library came from, for error messages.
_path: "Path | None" = None

#: Why loading failed, if it did.
_problem: "str | None" = None


def search_directory() -> Path:
    """Where a built library is expected to sit.

    Beside this module, so that a wheel carrying a compiled library and a
    checkout that has just built one both work without configuration.
    """
    return Path(__file__).parent / "lib"


def _load():
    """Find and load the library, or record why there is none."""
    global _library, _path, _problem

    folder = search_directory()
    for name in LIBRARY_NAMES:
        candidate = folder / name
        if not candidate.is_file():
            continue
        try:
            library = ctypes.CDLL(str(candidate))
        except OSError as error:  # pragma: no cover -- needs a broken build
            _problem = f"{candidate} could not be loaded: {error}"
            _library, _path = None, None
            return

        for function_name, (argtypes, restype) in FUNCTION_SIGNATURES.items():
            try:
                function = getattr(library, function_name)
            except AttributeError:  # pragma: no cover -- needs a bad build
                _problem = (
                    f"{candidate} does not export {function_name}, so it is "
                    f"not a TrjoLudus native library."
                )
                _library, _path = None, None
                return
            function.argtypes = argtypes
            function.restype = restype

        found = library.trjoludus_abi_version()
        if found != ABI_VERSION:
            _problem = (
                f"{candidate} speaks ABI version {found}, but this TrjoLudus "
                f"speaks {ABI_VERSION}. Rebuild the native library."
            )
            _library, _path = None, None
            return

        _library, _path, _problem = library, candidate, None
        return

    _library, _path = None, None
    _problem = (
        f"no native library found in {folder}. TrjoLudus runs in Python "
        f"without one; see rust/README.md to build it."
    )


def _handle():
    """The loaded library, or ``None``. Searches once."""
    if _library is _UNSEARCHED:
        _load()
    return _library


def loaded() -> bool:
    """Whether a native library is loaded."""
    return _handle() is not None


def version() -> "int | None":
    """The ABI version of the loaded library, or ``None`` if there is none."""
    library = _handle()
    return None if library is None else library.trjoludus_abi_version()


def problem() -> "str | None":
    """Why there is no library, or ``None`` when one is loaded."""
    _handle()
    return _problem


def library_path() -> "Path | None":
    """Where the loaded library came from, or ``None``."""
    _handle()
    return _path


def implements(name: str) -> bool:
    """Whether the native library implements one named subsystem.

    ``False`` whenever there is no library, which is the ordinary case: a
    TrjoLudus installed as pure Python implements nothing natively and every
    subsystem falls back.
    """
    library = _handle()
    if library is None:
        return False
    return bool(library.trjoludus_implements(name.encode("ascii")))


def forget() -> None:
    """Engine-internal: search again next time.

    For tests, which need to see what happens both with a library and
    without one.
    """
    global _library, _path, _problem
    _library, _path, _problem = _UNSEARCHED, None, None
