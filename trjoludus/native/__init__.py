"""The boundary between TrjoLudus and native code.

**A game never imports this.** It exists so that a subsystem can be
reimplemented in Rust without a single line of a game changing:
``player.move.x(100 * time.delta)`` is the API whatever is underneath it.

Four layers, and this is the third:

===========================  ====================================
``trjoludus/`` public API    what a game writes
engine and application       the scene, the loop, the input queue
``trjoludus/native/``        which implementation, and loading it
``rust/``                    the implementations themselves
===========================  ====================================

Each subsystem registers itself here and exposes the result as
``<subsystem>.engine``::

    rendering.engine = "auto"     # the default: TrjoLudus chooses
    rendering.engine = "rust"     # insist on the native one
    rendering.engine = "python"   # insist on the Python one

Per subsystem rather than one switch for the engine, because they are not one
decision: a game debugging its physics in Python has no reason to give up a
native renderer.

**Nothing is faked.** A subsystem with no native implementation says so when
asked for one, rather than quietly running the Python version and leaving a
game to wonder why it is still slow.
"""

from trjoludus.native.registry import (
    AUTO,
    CHOICES,
    PYTHON,
    RUST,
    EngineError,
    System,
    register,
    reset,
    system,
    systems,
)

__all__ = [
    "AUTO",
    "CHOICES",
    "EngineError",
    "PYTHON",
    "RUST",
    "System",
    "expose",
    "register",
    "reset",
    "system",
    "systems",
]


class _SystemModule:
    """Gives a subsystem module a checked, live ``engine`` attribute.

    Installed as a module's type by :func:`expose`, the same way
    :mod:`trjoludus.time` gives itself read-only values. Reading is live so
    that ``rendering.engine`` always says what is actually set, and writing
    goes through the check that refuses a value TrjoLudus does not know --
    rather than accepting ``"Rust"`` and silently doing nothing with it.
    """

    #: Set by :func:`expose` on each module that uses this type.
    _trjoludus_system = None

    def __getattr__(self, name: str):
        if name == "engine":
            return self._trjoludus_system.engine
        raise AttributeError(f"module {self.__name__!r} has no attribute "
                             f"{name!r}")

    def __setattr__(self, name: str, value) -> None:
        if name == "engine":
            self._trjoludus_system.engine = value
            return
        super().__setattr__(name, value)


def expose(module_name: str, *, recommends: "str | None",
           python_implementation: "str | None") -> System:
    """Register a subsystem and give its module an ``engine`` attribute.

    Called at the bottom of each subsystem module, once everything else in it
    is defined::

        expose(__name__, recommends=RUST,
               python_implementation="trjoludus.rendering_python")

    Args:
        module_name: ``__name__`` of the calling module. Its last component is
            the subsystem's name, so ``trjoludus.rendering`` registers
            ``"rendering"`` -- one name, taken from where the code lives,
            rather than a second one to keep in step.
        recommends: Which implementation ``"auto"`` prefers -- ``RUST``,
            ``PYTHON``, or ``None`` when nothing implements this yet.
        python_implementation: Where the Python implementation lives, or
            ``None`` if there is not one yet.

    Returns:
        The registered :class:`System`.
    """
    import sys
    from types import ModuleType

    name = module_name.rsplit(".", 1)[-1]
    registered = register(name, recommends=recommends,
                          python_implementation=python_implementation)

    module = sys.modules[module_name]
    # A fresh type per module: the class carries the system, so two modules
    # cannot share one and answer for each other.
    module.__class__ = type(
        f"_{name.capitalize()}Module",
        (_SystemModule, ModuleType),
        {"_trjoludus_system": registered},
    )
    return registered
