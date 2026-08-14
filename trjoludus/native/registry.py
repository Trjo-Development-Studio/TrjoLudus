"""Which implementation each subsystem uses, and how that is decided.

One :class:`System` per subsystem. A system knows three things: whether it is
one of the ones meant to run natively, whether a Python implementation of it
exists, and what a game has asked for. From those it can say which
implementation to use, or explain clearly why it cannot.

Nothing here loads or runs anything. Deciding and doing are separate: this
module decides, :mod:`trjoludus.native.library` finds out what is available,
and the subsystems themselves do the work.
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


class EngineError(TrjoLudusError):
    """Raised when a backend cannot be used the way a game asked for it."""


class System:
    """One subsystem of the engine, and which implementation it uses.

    Games do not build these. Each subsystem module registers one and exposes
    it as ``<module>.engine``, so a game writes ``rendering.engine = "rust"``
    and never sees this class.

    Args:
        name: The subsystem's name, as a game would say it.
        always_native: Whether ``"auto"`` should prefer the native
            implementation once one exists. True for the systems where the
            work is per-pixel or per-entity and Python is the bottleneck;
            false for the ones where it is not, which stay on Python until
            there is a reason not to.
        python_implementation: Where the Python implementation lives, or
            ``None`` if it has not been written. A system with neither
            implementation can be configured but not yet resolved.
    """

    __slots__ = ("_name", "_always_native", "_python_implementation",
                 "_engine")

    def __init__(self, name: str, *, always_native: bool,
                 python_implementation: "str | None") -> None:
        self._name = name
        self._always_native = always_native
        self._python_implementation = python_implementation
        self._engine = AUTO

    @property
    def name(self) -> str:
        """The subsystem's name."""
        return self._name

    @property
    def always_native(self) -> bool:
        """Whether ``"auto"`` prefers the native implementation for this."""
        return self._always_native

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

    def available(self) -> bool:
        """Whether a native implementation of this system can be used now.

        The library saying it implements something is necessary but not
        sufficient: a subsystem also gets to say whether it can actually
        start. A library missing half a subsystem's functions would otherwise
        be discovered on the first frame rather than here.
        """
        from trjoludus.native import library

        if not library.implements(self._name):
            return False
        if self._name == "rendering":
            from trjoludus.native import renderer

            return renderer.available()
        return True

    def resolve(self) -> str:
        """Which implementation to use: ``"rust"`` or ``"python"``.

        Raises:
            EngineError: If a game asked for an implementation that is not
                there. An explicit choice is never quietly replaced with the
                other one -- a game that says ``"rust"`` and gets Python has
                been told nothing, and will wonder why it is slow.
        """
        # Asked for Python: the answer cannot depend on what is available, so
        # nothing native is looked for. A game that chose the Python renderer
        # loads no library and no ctypes at all, which is what makes "python"
        # a real fallback rather than a preference.
        if self._engine == PYTHON:
            if self._python_implementation is not None:
                return PYTHON
            raise EngineError(
                f"{self._name}.engine is {PYTHON!r}, but {self._name} has no "
                f"Python implementation: nothing implements it yet in either "
                f"language."
            )

        native = self.available()

        if self._engine == RUST:
            if native:
                return RUST
            raise EngineError(
                f"{self._name}.engine is {RUST!r}, but there is no native "
                f"implementation of {self._name} available. "
                f"{self._unavailable_reason()} "
                f"Use {AUTO!r} to let TrjoLudus pick whichever is there."
            )

        # "auto": the native one when this is a system meant to run natively
        # and one is there; otherwise whatever exists.
        if native and self._always_native:
            return RUST
        if self._python_implementation is not None:
            return PYTHON
        if native:
            return RUST
        raise EngineError(
            f"{self._name} has no implementation yet, in either language. "
            f"It is registered so that its backend can be chosen once one "
            f"exists."
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
                f"always_native={self._always_native})")


#: Every registered subsystem, by name, in the order they were registered.
_SYSTEMS: dict[str, System] = {}


def register(name: str, *, always_native: bool,
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
    created = System(name, always_native=always_native,
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
