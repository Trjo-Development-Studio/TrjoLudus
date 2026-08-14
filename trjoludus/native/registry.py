"""Which implementation each subsystem uses, and how that is decided.

Three separate questions, kept separate on purpose:

**Recommendation** -- which implementation TrjoLudus thinks a subsystem should
normally use. A fixed property of the subsystem: rendering and image both
recommend the native one, because that is where the work is. Subsystems with
nothing implemented yet recommend nothing.

**Availability** -- which implementations can actually be used here and now.
*Both* are checked. Python is not assumed: a subsystem's Python implementation
is a module that has to be there, and an installation that shipped without one
is as real as one that shipped without a native library.

**Selection** -- what a game gets, from what it asked for, the recommendation
and what is available.

Collapsing any two of those into one is how a backend switch ends up meaning
something different in each subsystem. One :class:`System` per subsystem
answers all three, and every subsystem answers them the same way.

Nothing here loads or runs anything. Deciding and doing are separate: this
module decides, :mod:`trjoludus.native.library` finds out what is available
natively, and the subsystems themselves do the work.
"""

from trjoludus.errors import TrjoLudusError

__all__ = [
    "AUTO",
    "EngineError",
    "PYTHON",
    "RUST",
    "System",
    "register",
    "system",
    "systems",
]

#: Let TrjoLudus choose. The default for every system, and what a game that
#: never mentions ``.engine`` uses.
AUTO = "auto"

#: Ask for the native implementation, and fail loudly if there is not one.
RUST = "rust"

#: Ask for the Python implementation.
PYTHON = "python"

#: Every value ``.engine`` accepts.
CHOICES = (AUTO, RUST, PYTHON)


def _module_present(name: str) -> bool:
    """Whether a module can be reached, without importing it if it is not.

    Checked rather than assumed, and checked *now* rather than remembered: an
    implementation is available if it is there this time it is asked about.
    ``sys.modules`` first, because by the time anything resolves a backend the
    implementation modules are imported, and that makes the common answer a
    dictionary lookup rather than a walk of the import path.
    """
    import sys

    if name in sys.modules:
        return True
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):   # pragma: no cover -- odd packaging
        return False


class EngineError(TrjoLudusError):
    """Raised when a backend cannot be used the way a game asked for it."""


class System:
    """One subsystem of the engine, and which implementation it uses.

    Games do not build these. Each subsystem module registers one and exposes
    it as ``<module>.engine``, so a game writes ``rendering.engine = "rust"``
    and never sees this class.

    Args:
        name: The subsystem's name, as a game would say it.
        recommends: Which implementation ``"auto"`` should prefer --
            :data:`RUST`, :data:`PYTHON`, or ``None`` when nothing implements
            this subsystem yet. A recommendation is only made for a subsystem
            that exists; one is not invented for a system that may one day be
            written natively.
        python_implementation: The module the Python implementation lives in,
            or ``None`` if it has not been written.
    """

    __slots__ = ("_name", "_recommends", "_python_implementation",
                 "_engine", "_python_check", "_native_check")

    def __init__(self, name: str, *, recommends: "str | None",
                 python_implementation: "str | None") -> None:
        if recommends not in (RUST, PYTHON, None):
            raise ValueError(
                f"a recommendation must be {RUST!r}, {PYTHON!r} or None, "
                f"got {recommends!r}"
            )
        self._name = name
        self._recommends = recommends
        self._python_implementation = python_implementation
        self._engine = AUTO
        # Seams, one per language. Tests need to ask what happens when an
        # implementation is missing, and the honest way to arrange that is to
        # say so -- not to remove a module from a running interpreter, nor to
        # delete a library from under a process that has loaded it.
        self._python_check = None
        self._native_check = None

    @property
    def name(self) -> str:
        """The subsystem's name."""
        return self._name

    @property
    def recommends(self) -> "str | None":
        """Which implementation ``"auto"`` prefers, or ``None`` if neither.

        What TrjoLudus thinks should normally be used -- not what is
        available, and not what a game asked for.
        """
        return self._recommends

    @property
    def python_implementation(self) -> "str | None":
        """Where the Python implementation lives, or ``None`` if unwritten."""
        return self._python_implementation

    @property
    def engine(self) -> str:
        """What a game has asked for: ``"auto"``, ``"rust"`` or ``"python"``.

        ``"auto"`` until something sets it, and a game never has to.
        """
        return self._engine

    @engine.setter
    def engine(self, value: str) -> None:
        self._engine = self._check(value)

    def _check(self, value) -> str:
        if not isinstance(value, str):
            raise TypeError(
                f"{self._name}.engine must be a string, got "
                f"{type(value).__name__}"
            )
        if value not in CHOICES:
            raise ValueError(
                f"{value!r} is not a backend TrjoLudus knows. "
                f"{self._name}.engine takes {AUTO!r} (let TrjoLudus choose), "
                f"{RUST!r} (the native implementation) or {PYTHON!r}."
            )
        # Changing which implementation a subsystem uses part-way through a
        # game would leave the half of it that had already started on the old
        # one. Refusing is better than a game that is half switched.
        from trjoludus.app import current_application

        if current_application() is not None and value != self._engine:
            raise EngineError(
                f"{self._name}.engine cannot be changed while a game is "
                f"running: the subsystem has already started on "
                f"{self._engine!r}. Set it before run()."
            )
        return value

    def native_available(self) -> bool:
        """Whether the native implementation can be used now.

        Asked again every time rather than remembered: a library can be
        replaced or removed between one question and the next, and an answer
        cached from before that would be a wrong answer with a good memory.

        The library saying it implements something is necessary but not
        sufficient: a subsystem also gets to say whether it can actually
        start. A library missing half a subsystem's functions would otherwise
        be discovered on the first frame rather than here.
        """
        if self._native_check is not None:
            return bool(self._native_check())

        from trjoludus.native import library

        if not library.implements(self._name):
            return False
        if self._name == "rendering":
            from trjoludus.native import renderer

            return renderer.available()
        if self._name == "image":
            from trjoludus.native import imaging

            return imaging.available()
        return True

    def python_available(self) -> bool:
        """Whether the Python implementation can be used now.

        A real question, not an assumption. A subsystem with nothing written
        in Python has no Python implementation to fall back to, and neither
        has an installation whose module is missing -- so this asks, the same
        way :meth:`native_available` asks about the library.
        """
        if self._python_check is not None:
            return bool(self._python_check())
        if self._python_implementation is None:
            return False
        return _module_present(self._python_implementation)

    def available(self, backend: str) -> bool:
        """Whether one named backend can be used now.

        Raises:
            ValueError: If ``backend`` is not :data:`RUST` or :data:`PYTHON`.
        """
        if backend == RUST:
            return self.native_available()
        if backend == PYTHON:
            return self.python_available()
        raise ValueError(
            f"{backend!r} is not a backend; ask about {RUST!r} or {PYTHON!r}"
        )

    def resolve(self) -> str:
        """Which implementation to use: ``"rust"`` or ``"python"``.

        The whole rule, in one place, the same for every subsystem::

            asked for "python"  -> Python if available, else an error
            asked for "rust"    -> native if available, else an error
            asked for "auto"    -> what is recommended, if available;
                                   otherwise the other one, if available;
                                   otherwise an error

        An explicit choice is never quietly replaced by the other one. A game
        that says ``"rust"`` and silently gets Python has been told nothing
        and will wonder why it is slow; a game that says ``"python"`` to
        compare implementations and silently gets the native one is comparing
        it with itself.

        ``"auto"`` is where falling back is the point rather than a failure --
        it is the setting that means "you choose".

        Raises:
            EngineError: If what was asked for cannot be given.
        """
        requested = self._engine

        if requested == PYTHON:
            # Nothing native is looked at: the answer cannot depend on it, and
            # a game that chose Python loads no library and no ctypes at all.
            if self.python_available():
                return PYTHON
            raise EngineError(self._cannot(PYTHON))

        if requested == RUST:
            if self.native_available():
                return RUST
            raise EngineError(self._cannot(RUST))

        # "auto": what is recommended, then whatever else there is.
        order = (RUST, PYTHON) if self._recommends == RUST else (PYTHON, RUST)
        for backend in order:
            if self.available(backend):
                return backend

        raise EngineError(
            f"{self._name}.engine is {AUTO!r}, but there is no implementation "
            f"of {self._name} to use: {self._why_not(PYTHON)} "
            f"{self._why_not(RUST)}"
        )

    def _cannot(self, backend: str) -> str:
        """Why an explicit request could not be honoured."""
        return (
            f"{self._name}.engine is {backend!r}, but "
            f"{self._why_not(backend)} "
            f"Use {AUTO!r} to let TrjoLudus pick whichever is there."
        )

    def _why_not(self, backend: str) -> str:
        """One sentence about why a backend is not available."""
        if backend == RUST:
            if self.native_available():   # pragma: no cover -- only on error
                return "the native implementation is available."
            return (
                f"there is no native implementation of {self._name} "
                f"available. {self._unavailable_reason()}"
            )
        if self.python_available():       # pragma: no cover -- only on error
            return "the Python implementation is available."
        if self._python_implementation is None:
            return (
                f"there is no Python implementation of {self._name}: nothing "
                f"implements it yet in either language."
            )
        return (
            f"the Python implementation of {self._name} "
            f"({self._python_implementation}) could not be found in this "
            f"installation."
        )

    def _unavailable_reason(self) -> str:
        from trjoludus.native import library

        if not library.loaded():
            return (
                "The native library is not built or could not be loaded; see "
                "rust/README.md for how to build it."
            )
        return "The native library is loaded but does not implement it yet."

    def __repr__(self) -> str:
        return (f"System({self._name!r}, engine={self._engine!r}, "
                f"recommends={self._recommends!r})")


#: Every registered subsystem, by name, in the order they were registered.
_SYSTEMS: dict[str, System] = {}


def register(name: str, *, recommends: "str | None",
             python_implementation: "str | None") -> System:
    """Add a subsystem to the registry and return it.

    Called once by each subsystem module as it is imported.

    Raises:
        EngineError: If the name is already registered. Two systems sharing a
            name would mean one of them silently answering for the other.
    """
    if name in _SYSTEMS:
        raise EngineError(
            f"there is already a subsystem called {name!r}."
        )
    created = System(name, recommends=recommends,
                     python_implementation=python_implementation)
    _SYSTEMS[name] = created
    return created


def system(name: str) -> System:
    """The subsystem with this name.

    Raises:
        EngineError: If there is no such subsystem.
    """
    try:
        return _SYSTEMS[name]
    except KeyError:
        known = ", ".join(repr(other) for other in _SYSTEMS)
        raise EngineError(
            f"TrjoLudus has no subsystem called {name!r}. It has: {known}."
        ) from None


def systems() -> tuple[System, ...]:
    """Every registered subsystem, in registration order."""
    return tuple(_SYSTEMS.values())


def reset() -> None:
    """Engine-internal: put every subsystem back to ``"auto"``.

    For tests. A game's choice lasts for the life of the process, because it
    is a statement about how the program should run rather than about one
    game.
    """
    for registered in _SYSTEMS.values():
        registered._engine = AUTO
        registered._python_check = None
        registered._native_check = None
