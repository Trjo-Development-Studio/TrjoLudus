"""Lending the engine's objects to native code.

**A game never imports this.** It is how a native subsystem gets at the object
table without anyone copying the world.

**Nothing is copied.** :func:`view` builds a small C struct of six pointers
into the arrays :class:`~trjoludus.engine.ObjectTable` already holds. Native
code reads and writes those very doubles; there is no snapshot, no mirror and
nothing to write back. The struct is rebuilt per call because an ``array`` can
move when it grows, and a pointer taken before an object was created would be
pointing at the old allocation.

**Ownership.** Python allocates the arrays, Python frees them, native code
borrows them for the length of one call and keeps nothing. The same rule the
renderer follows.

**What native code may change.** Positions, through
:func:`set_position`, and nothing else. Creating and destroying objects
belongs to Python: a subsystem that could conjure them would be a second place
where the world is decided.
"""

import ctypes

from trjoludus.errors import TrjoLudusError
from trjoludus.native import library

__all__ = ["Object", "WorldError", "available", "live", "read", "set_position"]

#: What the native side answers with.
STATUS_OK = 0
_STATUS_MEANINGS = {
    -1: "a pointer into the object table was null",
    -2: "the object table's arrays were not all the same length",
    -3: "the native side failed while reading the world",
    -4: "there is no object in that slot",
}

#: Slot asked about holds nothing. An answer rather than a failure.
STATUS_NO_OBJECT = -4


class WorldError(TrjoLudusError):
    """Raised when shared engine state could not be read or changed."""


class Object(ctypes.Structure):
    """One object's numbers, copied out for the caller.

    A copy on purpose, and a small one: changing it changes nothing. To move
    an object, use :func:`set_position`, which writes the table itself.
    """

    _fields_ = [
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("scale", ctypes.c_double),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("flags", ctypes.c_int32),
        ("reserved", ctypes.c_int32),
    ]

    def __repr__(self) -> str:
        return (f"Object(at=({self.x}, {self.y}), size=({self.width}, "
                f"{self.height}), scale={self.scale}, flags={self.flags})")


class WorldTable(ctypes.Structure):
    """The object table, as the native side sees it.

    Six pointers and a count. Python builds one of these per call; nothing
    native learns anything about how Python stores the world, and nothing
    Python holds learns anything about Rust.
    """

    _fields_ = [
        ("x", ctypes.POINTER(ctypes.c_double)),
        ("y", ctypes.POINTER(ctypes.c_double)),
        ("scale", ctypes.POINTER(ctypes.c_double)),
        ("width", ctypes.POINTER(ctypes.c_int32)),
        ("height", ctypes.POINTER(ctypes.c_int32)),
        ("flags", ctypes.POINTER(ctypes.c_int32)),
        ("count", ctypes.c_size_t),
    ]


_TABLE = ctypes.POINTER(WorldTable)

FUNCTION_SIGNATURES = {
    "trjoludus_world_live": ([_TABLE], ctypes.c_int64),
    "trjoludus_world_read": (
        [_TABLE, ctypes.c_size_t, ctypes.POINTER(Object)], ctypes.c_int),
    "trjoludus_world_set_position": (
        [_TABLE, ctypes.c_size_t, ctypes.c_double, ctypes.c_double],
        ctypes.c_int),
}

_prepared = None


def _functions():
    """The world functions, with their signatures applied. Once."""
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
    """Whether native code can be handed the object table."""
    return _functions() is not None


def view(table=None) -> WorldTable:
    """A borrowed view of the object table, for one call.

    Built fresh each time: ``array`` reallocates as it grows, so a pointer
    kept from before an object was created could address memory that has since
    moved.
    """
    from trjoludus import engine

    if table is None:
        table = engine.current().objects

    def pointer(values, kind):
        address = values.buffer_info()[0]
        return ctypes.cast(address, ctypes.POINTER(kind))

    return WorldTable(
        x=pointer(table.x, ctypes.c_double),
        y=pointer(table.y, ctypes.c_double),
        scale=pointer(table.scale, ctypes.c_double),
        width=pointer(table.width, ctypes.c_int32),
        height=pointer(table.height, ctypes.c_int32),
        flags=pointer(table.flags, ctypes.c_int32),
        count=len(table),
    )


def _call(name, *arguments):
    functions = _functions()
    if functions is None:
        raise WorldError(
            "there is no native library to share engine state with. "
            f"{library.problem() or ''}".strip()
        )
    return functions[name](*arguments)


def _check(status: int) -> None:
    if status == STATUS_OK:
        return
    raise WorldError(
        "the native side could not work with the engine's objects: "
        f"{_STATUS_MEANINGS.get(status, f'unknown status {status}')}."
    )


def live(table=None) -> int:
    """How many objects the native side can see.

    The point of this being here rather than counted in Python: it proves
    native code is reading the same table, and it is what any future
    subsystem's first line will look like.
    """
    borrowed = view(table)
    count = _call("trjoludus_world_live", ctypes.byref(borrowed))
    if count < 0:
        _check(int(count))
    return int(count)


def read(slot: int, table=None) -> "Object | None":
    """One object's numbers, as native code sees them.

    ``None`` when that slot holds nothing, which is an answer rather than a
    failure -- a destroyed object leaves a slot behind until it is reused.
    """
    borrowed = view(table)
    found = Object()
    status = _call("trjoludus_world_read", ctypes.byref(borrowed), slot,
                   ctypes.byref(found))
    if status == STATUS_NO_OBJECT:
        return None
    _check(status)
    return found


def set_position(slot: int, x: float, y: float, table=None) -> bool:
    """Move one object, from the native side, in place.

    Writes the table Python is holding: there is no copy and nothing to write
    back. Returns whether the slot held a live object; a slot that did not is
    left alone.
    """
    borrowed = view(table)
    status = _call("trjoludus_world_set_position", ctypes.byref(borrowed),
                   slot, float(x), float(y))
    if status == STATUS_NO_OBJECT:
        return False
    _check(status)
    return True
