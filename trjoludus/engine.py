"""The engine's state, and who is allowed to touch it.

**A game never imports this.** It exists so that Python and native subsystems
can work on the same state rather than on copies of it that drift apart.

# The rule

There is one authoritative copy of anything. When rendering, physics and
collision all want an object's position, they read *the same number*, not
three numbers that are supposed to be equal.

That is why an object's numbers live in :class:`ObjectTable` rather than as
attributes on the object. A :class:`~trjoludus.scene.SceneObject` is a name and
an image and a slot number; ``obj.x`` reads the table, and so does anything
native that borrows it. Nobody holds a second copy to keep in step, because
there is no second copy.

# Who owns what

============  =====================================================
State         Owner
============  =====================================================
objects       :class:`ObjectTable`, owned by :class:`EngineState`
the scene     :class:`~trjoludus.scene.Scene`, owned by the state
drawings      :class:`~trjoludus.ui.Ui`, owned by the state
timing        :class:`~trjoludus.clock.Clock`, lent by the application
images        the :class:`~trjoludus.image.Image` objects themselves
input         the running :class:`~trjoludus.app.Application`
============  =====================================================

Python allocates all of it, Python frees all of it, and native code borrows
what it is given for the length of one call. That is the same rule the
renderer already follows, and it is the reason there is nothing here to leak.

# Lifetime

One :class:`EngineState` exists at a time. A run replaces it, so a second run
begins with an empty world rather than the last one's, and anything a game
kept from the first run points at a state nobody is using any more.

Configuration is *not* part of it. ``rendering.engine`` says how the program
should run, not what is in this world, and it survives runs on purpose.

# Threading

Single-threaded, and assumed so. Nothing here is guarded, and a native call
borrows the tables for the length of that call, so a second thread mutating
the scene during a native call would be a data race. No part of the engine
starts a thread today, and no claim of thread safety is made because none has
been tested.
"""

from array import array

__all__ = ["EngineState", "ObjectTable", "current", "begin_run", "end_run",
           "resources_of"]

#: Bit set while an object is in the scene. Cleared when it is destroyed, so
#: a native pass can skip it without asking Python anything.
ALIVE = 1

#: Bit set while an object should be drawn.
VISIBLE = 2


class ObjectTable:
    """Where objects' numbers actually live.

    One array per field rather than one record per object: a native pass over
    every position touches one contiguous run of doubles instead of striding
    over interleaved fields it does not want. It is also the layout that stays
    useful if any of this is ever vectorised.

    Slots are handed out on request and returned when an object is destroyed.
    A returned slot is reused, so a game that creates and destroys objects
    forever does not grow this without limit.

    Nothing here knows what an object *is*. It holds numbers;
    :class:`~trjoludus.scene.SceneObject` gives them meaning.
    """

    __slots__ = ("x", "y", "scale", "width", "height", "flags", "_free",
                 "_used")

    def __init__(self) -> None:
        #: Position. Fractional on purpose -- see ARCHITECTURE.md; rounding is
        #: a rendering concern and happens nowhere else.
        self.x = array("d")
        self.y = array("d")
        #: How much bigger than its image an object is drawn.
        self.scale = array("d")
        #: The image's size in whole pixels. Kept here so that a native pass
        #: can work out what an object covers without reaching into Python.
        self.width = array("i")
        self.height = array("i")
        #: ALIVE and VISIBLE.
        self.flags = array("i")
        self._free: list[int] = []
        self._used = 0

    def __len__(self) -> int:
        """How many slots exist, used or not."""
        return len(self.x)

    @property
    def live(self) -> int:
        """How many slots hold an object that has not been destroyed."""
        return sum(1 for flags in self.flags if flags & ALIVE)

    def claim(self, x=0.0, y=0.0, width=0, height=0) -> int:
        """Take a slot for a new object and return its number."""
        if self._free:
            slot = self._free.pop()
            self.x[slot] = float(x)
            self.y[slot] = float(y)
            self.scale[slot] = 1.0
            self.width[slot] = int(width)
            self.height[slot] = int(height)
            self.flags[slot] = ALIVE | VISIBLE
            self._used += 1
            return slot

        slot = len(self.x)
        self.x.append(float(x))
        self.y.append(float(y))
        self.scale.append(1.0)
        self.width.append(int(width))
        self.height.append(int(height))
        self.flags.append(ALIVE | VISIBLE)
        self._used += 1
        return slot

    def release(self, slot: int) -> None:
        """Give a slot back, so a later object can have it.

        The slot is marked dead first. Anything still holding the number sees
        an object that is not alive rather than whatever moves in next -- and
        handles check that they are alive before reading anything anyway.
        """
        if slot is None or not (0 <= slot < len(self.x)):
            return
        if not self.flags[slot] & ALIVE:
            return
        self.flags[slot] = 0
        self._free.append(slot)
        self._used -= 1

    def clear(self) -> None:
        """Forget every slot."""
        for field in (self.x, self.y, self.scale):
            del field[:]
        for field in (self.width, self.height, self.flags):
            del field[:]
        self._free.clear()
        self._used = 0

    def __repr__(self) -> str:
        return (f"ObjectTable({self._used} objects in {len(self.x)} slots)")


class EngineState:
    """Everything one run of a game knows.

    Made by the application when a run begins and dropped when it ends, so
    that state from one run cannot reach the next. Reached through
    :func:`current`, never built by a game.
    """

    __slots__ = ("objects", "world", "drawings", "clock", "resources",
                 "groups")

    def __init__(self) -> None:
        from trjoludus.scene import Scene
        from trjoludus.ui import Ui

        #: The numbers behind every object, shared with native code.
        self.objects = ObjectTable()
        #: Named objects. Holds the names and images; the numbers are in
        #: :attr:`objects`.
        self.world = Scene()
        #: Drawing lists. Their numbers are still on the drawings themselves:
        #: nothing native reads them yet, and inventing shared storage for a
        #: reader that does not exist would be storage nobody uses.
        self.drawings = Ui()
        #: The clock a run is paced by. Lent by the application while it runs,
        #: so that anything wanting "how long was the last frame" has one
        #: place to ask. ``None`` outside a run.
        self.clock = None
        #: Everything a run has loaded from disk, by kind and by name.
        #:
        #: Keys are ``(kind, name)`` -- ``("image", "player.png")`` today.
        #: The kind is part of the key rather than implied, so that a future
        #: font or sound loaded from the same path as an image is a different
        #: resource rather than the same one, and so counting one kind never
        #: counts another. Nothing here knows what kinds exist;
        #: :func:`resources_of` is how a subsystem asks for its own.
        #:
        #: Decoding a PNG is the most expensive thing a game does that it does
        #: not have to do twice: an animation's frames, and an image switched
        #: back and forth, are the same files over and over. Images are
        #: immutable, so handing the same one out again is not a shortcut with
        #: consequences.
        #:
        #: One resource may appear under more than one name -- the spelling a
        #: game used, and the resolved path -- so that asking again with the
        #: same string costs a dictionary lookup and no filesystem call.
        #: :func:`trjoludus.image.loaded_images` counts images rather than
        #: keys.
        #:
        #: **Never invalidated.** A file that changes on disk during a run
        #: keeps the resource already loaded from it. There is no file
        #: watching, no modification-time check and no eviction: a run is
        #: short, and a game that wants the new picture starts a new run.
        #:
        #: **Released with the run.** Belongs to this state, like everything
        #: else here, so a second run loads afresh rather than inheriting
        #: whatever the first happened to need. Nothing here is process-wide.
        #:
        #: Python owns every one of these. Native code borrows an image's
        #: bytes for the length of one drawing call and never keeps them.
        self.resources: dict = {}
        #: Every collision group name used during this run, in the order they
        #: were first used. A dict as an ordered set.
        #:
        #: Not membership -- that lives on the objects themselves, which is
        #: what makes it go when they do. This is only the *names*, so that a
        #: group nobody has ever mentioned can be told from one that happens
        #: to be empty right now. A game whose zombies are all dead still has
        #: an "enemy" group; a game that typed "enmeys" does not, and hears
        #: about it.
        #:
        #: Never pruned, and released with the run like everything else here.
        self.groups: dict = {}

    def __repr__(self) -> str:
        return (f"EngineState({len(self.world)} objects, "
                f"{len(self.drawings._lists)} drawing lists, "
                f"{len(self.resources)} resources)")


#: The state everything reads. Replaced when a run begins, never mutated into
#: a different one, so anything holding the old one is holding a whole
#: consistent world that simply is not current any more.
#:
#: Built on first use rather than at import: a state owns a scene and a set of
#: drawing lists, and those modules import this one.
_current: "EngineState | None" = None


def current() -> EngineState:
    """The engine state in use right now."""
    global _current
    if _current is None:
        _current = EngineState()
    return _current


def resources_of(kind: str, state=None) -> dict:
    """Everything of one kind a run has loaded, by name.

    Engine-internal. A fresh dictionary each time, so what it holds cannot be
    changed by accident -- the store itself stays keyed by ``(kind, name)``.

    Kinds do not need registering. A subsystem that loads something asks for
    its own kind and sees nothing belonging to anybody else, which is what
    keeps a future font from being counted as an image.
    """
    store = (current() if state is None else state).resources
    return {name: value for (found, name), value in store.items()
            if found == kind}


def begin_run(clock=None) -> EngineState:
    """Lend a run's clock to the state, and return it.

    Engine-internal. The state is *not* replaced here, on purpose: objects and
    drawing lists made before ``run()`` take part in that run, which is
    behaviour games have relied on since Milestone 2. Isolation between runs
    comes from :func:`end_run` instead -- what a run leaves behind is dropped
    when it finishes, so the next one starts empty either way.
    """
    state = current()
    state.clock = clock
    return state


def end_run() -> None:
    """Drop the state a run was using.

    Engine-internal. What follows is a fresh, empty state -- a new world, new
    drawing lists and a new object table -- so nothing a game kept from one
    run can reach the next. Reading the scene afterwards is not an error; it
    shows nothing, which is what it showed before the run started.
    """
    global _current
    _current = EngineState()
