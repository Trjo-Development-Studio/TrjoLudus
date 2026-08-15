"""Lending the engine's objects to native code, a whole pass at a time.

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

**What native code may change.** Positions, and nothing else. Creating and
destroying objects belongs to Python: a subsystem that could conjure them
would be a second place where the world is decided.

# One call for a pass, not one call per object

:func:`gather` and :func:`set_positions` are what a native subsystem is meant
to use. They read and write the whole table in a single crossing.

:func:`live`, :func:`read` and :func:`set_position` are the same thing one
object at a time. They exist to *prove* that Python and native code share
memory -- a test can move one object and see the change from the other side --
and they are the wrong shape for doing work. A pass built out of them pays the
crossing per object, which measured 128 times slower than the Python array
write it was replacing. They are kept because what they prove is worth
proving, and marked here so nobody builds a subsystem on them.

# Results that vary in length

Whatever a future subsystem produces -- pairs that collided, steps in a path --
follows one convention, which is the ownership rule rather than an exception
to it::

    Python allocates a buffer -> native fills what fits -> native says how
                                                           many there were

The count that comes back is what there *was*, not what was stored, so asking
with no buffer at all is a counting pass and asking with one that turns out to
be too small still tells you the size to use next time. Nothing is allocated
natively, so there is nothing to free.
"""

import ctypes

from trjoludus.errors import TrjoLudusError
from trjoludus.native import library

__all__ = ["Object", "WorldError", "available", "gather", "live", "read",
           "set_position", "set_positions"]

#: What the native side answers with.
STATUS_OK = 0
_STATUS_MEANINGS = {
    -1: "a pointer into the object table was null",
    -2: "the object table's arrays were not all the same length",
    -3: "the native side failed while reading the world",
    -4: "there is no object in that slot",
    -7: "the buffer was too small to hold every result",
}

#: Slot asked about holds nothing. An answer rather than a failure.
STATUS_NO_OBJECT = -4

#: The buffer could not hold every result. An answer too: the count comes back
#: regardless, so a caller knows what to allocate.
STATUS_TOO_SMALL = -7


class WorldError(TrjoLudusError):
    """Raised when shared engine state could not be read or changed."""


class Object(ctypes.Structure):
    """One object's numbers, copied out for the caller.

    A copy on purpose, and a small one: changing it changes nothing. To move
    objects, use :func:`set_positions`, which writes the table itself.

    :attr:`slot` is which slot it came from, so a pass that gathers objects
    can say something about them afterwards and write the answer back.
    """

    _fields_ = [
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("scale", ctypes.c_double),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("flags", ctypes.c_int32),
        ("slot", ctypes.c_int32),
    ]

    def __repr__(self) -> str:
        return (f"Object(slot={self.slot}, at=({self.x}, {self.y}), "
                f"size=({self.width}, {self.height}), scale={self.scale}, "
                f"flags={self.flags})")


class WorldTable(ctypes.Structure):
    """The object table, as the native side sees it.

    Six pointers and a count. Python builds one of these per call; nothing
    native learns anything about how Python stores the world, and nothing
    Python holds learns anything about Rust.

    The pointers are declared ``c_void_p`` rather than typed pointers. Both
    are one machine word and the native side declares the types it expects, so
    the struct's layout is the same either way -- but a ``c_void_p`` field
    takes an integer address directly, where a typed one needs
    :func:`ctypes.cast`, and six casts measured five-sixths of the cost of
    building this. The types that matter are the ones in the Rust struct.
    """

    _fields_ = [
        ("x", ctypes.c_void_p),
        ("y", ctypes.c_void_p),
        ("scale", ctypes.c_void_p),
        ("width", ctypes.c_void_p),
        ("height", ctypes.c_void_p),
        ("flags", ctypes.c_void_p),
        ("count", ctypes.c_size_t),
    ]


_TABLE = ctypes.POINTER(WorldTable)
_COUNT = ctypes.POINTER(ctypes.c_size_t)

FUNCTION_SIGNATURES = {
    "trjoludus_world_live": ([_TABLE], ctypes.c_int64),
    "trjoludus_world_read": (
        [_TABLE, ctypes.c_size_t, ctypes.POINTER(Object)], ctypes.c_int),
    "trjoludus_world_set_position": (
        [_TABLE, ctypes.c_size_t, ctypes.c_double, ctypes.c_double],
        ctypes.c_int),
    "trjoludus_world_gather": (
        [_TABLE, ctypes.POINTER(Object), ctypes.c_size_t, _COUNT],
        ctypes.c_int),
    "trjoludus_world_set_positions": (
        [_TABLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
         ctypes.c_size_t, _COUNT], ctypes.c_int),
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
    moved. Cheap enough to do per call -- but per *pass*, not per object.
    """
    from trjoludus import engine

    if table is None:
        table = engine.current().objects

    return WorldTable(
        x=table.x.buffer_info()[0],
        y=table.y.buffer_info()[0],
        scale=table.scale.buffer_info()[0],
        width=table.width.buffer_info()[0],
        height=table.height.buffer_info()[0],
        flags=table.flags.buffer_info()[0],
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


# --- a whole pass at a time -----------------------------------------------


def gather(into=None, table=None):
    """Every live object, in one call.

    The read half of a bulk pass. One crossing walks the whole table, however
    many objects are in it.

    Args:
        into: A buffer to fill -- an ``Object * capacity`` array. ``None``
            allocates one big enough, which costs a counting call first.
        table: Which object table, for tests. The running one by default.

    Returns:
        ``(objects, count)``. ``objects`` is the buffer, ``count`` how many
        live objects there **are** -- which is larger than the buffer when one
        was supplied and did not fit, so a caller can allocate from the answer
        and ask again. Only the first ``min(count, len(objects))`` entries were
        written.
    """
    borrowed = view(table)
    found = ctypes.c_size_t(0)

    if into is None:
        # The counting pass: no buffer, no writing, just the size to allocate.
        status = _call("trjoludus_world_gather", ctypes.byref(borrowed),
                       None, 0, ctypes.byref(found))
        _check(status)
        into = (Object * found.value)()
        if found.value == 0:
            return into, 0
        borrowed = view(table)

    status = _call("trjoludus_world_gather", ctypes.byref(borrowed),
                   into, len(into), ctypes.byref(found))
    if status != STATUS_TOO_SMALL:
        _check(status)
    return into, found.value


def set_positions(slots, xs, ys, table=None) -> int:
    """Move many objects in one call.

    The write half of a bulk pass, and the counterpart of :func:`gather`. The
    three sequences line up: entry ``n`` of each is one move.

    Writes the table Python is holding -- there is no copy and nothing to
    write back. A slot that is out of range or holds no live object is skipped,
    because an object destroyed part-way through a pass is an ordinary thing
    to happen rather than a failure of the pass.

    Args:
        slots: Which slots to move, as an ``array("q")`` or a sequence.
        xs: New horizontal positions, as an ``array("d")`` or a sequence.
        ys: New vertical positions.
        table: Which object table, for tests.

    Returns:
        How many objects actually moved.
    """
    from array import array

    if not isinstance(slots, array) or slots.typecode != "q":
        slots = array("q", slots)
    if not isinstance(xs, array) or xs.typecode != "d":
        xs = array("d", xs)
    if not isinstance(ys, array) or ys.typecode != "d":
        ys = array("d", ys)

    count = len(slots)
    if len(xs) < count or len(ys) < count:
        raise WorldError(
            f"there are {count} slots to move but {len(xs)} x and {len(ys)} y "
            f"positions. Each slot needs one of each."
        )

    borrowed = view(table)
    moved = ctypes.c_size_t(0)
    status = _call(
        "trjoludus_world_set_positions", ctypes.byref(borrowed),
        slots.buffer_info()[0] if count else None,
        xs.buffer_info()[0] if count else None,
        ys.buffer_info()[0] if count else None,
        count, ctypes.byref(moved))
    _check(status)
    return moved.value


# --- one object at a time: proof of shared memory, not a way to work ------


def live(table=None) -> int:
    """How many objects the native side can see.

    Proof that native code is reading the same table. For work, gather.
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

    One object at a time. A pass over the world should use :func:`gather`.
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

    One object at a time. A pass that moves things should use
    :func:`set_positions`, which crosses the boundary once instead of once per
    object.
    """
    borrowed = view(table)
    status = _call("trjoludus_world_set_position", ctypes.byref(borrowed),
                   slot, float(x), float(y))
    if status == STATUS_NO_OBJECT:
        return False
    _check(status)
    return True
