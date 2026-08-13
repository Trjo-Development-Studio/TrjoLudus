"""Where the pointer is, and what it is doing.

::

    if mouse.pressed("LEFT"):
        player.x = mouse.x

    mouse.wait(input.mouse)
    print(mouse.button)     # LEFT

**Position and buttons are two different things.** Where the pointer is, and
whether a button is held, are *state*: read them whenever you like and you get
the current answer. A button going down is an *input*: it happens once, and
:func:`wait` hands each one out exactly once, the same way
:func:`trjoludus.keyboard.wait` does with keys.

That split is why moving the mouse does not end a :func:`wait`. Movement is
continuous -- waiting on it would return the instant anyone nudged the mouse,
which is never what "wait for input" means.

:func:`wait` answers only to the mouse. A key press does not end it, and is
not thrown away either: it waits in the queue for
:func:`trjoludus.keyboard.wait` or :func:`trjoludus.input.wait`.

**Every pointer belongs to a window.** A position only means anything relative
to some window's drawable area, so the state lives per window rather than once
for the whole program -- see :class:`MouseState`. The names in this module
read the window the running game owns, which is the only one a game can have
today. When several windows are possible, ``some_window.mouse`` will be the
same :class:`MouseState` object, and nothing here has to change.

Coordinates are pixels from the top-left corner of that window's drawable
area, matching everything else in TrjoLudus.
"""

from trjoludus.errors import TrjoLudusError
from trjoludus.events import MOUSE_BUTTONS

__all__ = ["MouseState", "button", "position", "pressed", "wait", "x", "y"]


class _AnyMouseInput:
    """The value :data:`trjoludus.input.mouse` refers to."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "input.mouse"


#: Passed to :func:`wait` to mean "any mouse button". An argument rather than
#: implied, so waiting for one particular button can be added later without
#: the call reading differently.
any_input = _AnyMouseInput()


class MouseState:
    """The pointer, as one window sees it.

    A position is only meaningful against a particular window's drawable area,
    so there is one of these per window rather than one for the program. Today
    a game has a single window and reads it through the :mod:`trjoludus.mouse`
    names; the object is what a future ``window.mouse`` would hand back.
    """

    __slots__ = ("x", "y", "held", "button")

    def __init__(self) -> None:
        self.x = 0
        self.y = 0
        self.held: set[str] = set()
        #: The button most recently reported by :func:`wait`.
        self.button: str | None = None

    @property
    def position(self) -> tuple[int, int]:
        """``(x, y)`` of the pointer in this window."""
        return (self.x, self.y)

    def pressed(self, name: str) -> bool:
        """Whether a button is held down in this window."""
        return name in self.held

    def moved(self, x: int, y: int) -> None:
        """Engine-internal: record a new pointer position."""
        self.x = x
        self.y = y

    def button_down(self, name: str, x: int, y: int) -> None:
        """Engine-internal: record a button going down."""
        self.held.add(name)
        self.moved(x, y)

    def button_up(self, name: str, x: int, y: int) -> None:
        """Engine-internal: record a button coming up."""
        self.held.discard(name)
        self.moved(x, y)

    def __repr__(self) -> str:
        held = ", ".join(sorted(self.held)) or "nothing held"
        return f"MouseState(at=({self.x}, {self.y}), {held})"


#: Answers when no game is running, so reading the mouse outside a game is a
#: quiet zero rather than an error. It is never written to by a game.
_idle = MouseState()


def _reset() -> None:
    """Engine-internal: clear the idle state.

    A running game's state belongs to its window and is dropped with the run,
    so this only matters for reading the mouse outside a game.
    """
    _idle.__init__()


def active_state() -> MouseState:
    """The :class:`MouseState` the module-level names read.

    The running game's window, or an untouched state when nothing is running.
    """
    from trjoludus.app import current_application

    application = current_application()
    if application is None:
        return _idle
    return application.mouse_state()


def __getattr__(name: str):
    """Serve :data:`x`, :data:`y`, :data:`position` and :data:`button`.

    They are looked up rather than stored so that reading ``mouse.x`` always
    gives the current answer, from whichever window the game owns. Nothing has
    to be refreshed, and there is no copy of the position to fall out of date.
    """
    if name in ("x", "y", "position", "button"):
        return getattr(active_state(), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _check_button(name: str) -> str:
    if not isinstance(name, str):
        raise TypeError(
            f"a mouse button must be named with a string, got "
            f"{type(name).__name__}"
        )
    if name not in MOUSE_BUTTONS:
        known = ", ".join(sorted(MOUSE_BUTTONS))
        raise ValueError(
            f"{name!r} is not a mouse button TrjoLudus knows. "
            f"The buttons are: {known}."
        )
    return name


def pressed(name: str) -> bool:
    """Whether a mouse button is held down right now.

    Args:
        name: ``"LEFT"``, ``"RIGHT"`` or ``"MIDDLE"``.

    Raises:
        TypeError: If ``name`` is not a string.
        ValueError: If it is not a button TrjoLudus knows.
    """
    return active_state().pressed(_check_button(name))


def wait(what) -> None:
    """Wait for a mouse button press and record which one it was.

    Like :func:`trjoludus.keyboard.wait`, this hands you nothing to store: it
    updates :data:`button`. Each press answers exactly one call, in the order
    the presses happened, so calling twice waits twice rather than reporting
    the same click again.

    Only the mouse ends this wait. Moving the pointer does not, and neither
    does a key press -- a key waiting to be read stays in the queue for
    whoever asks for it. Afterwards :data:`x` and :data:`y` report where the
    click happened, not wherever the pointer has since drifted to.

    Args:
        what: :data:`trjoludus.input.mouse`. Nothing else is accepted yet.

    Returns:
        Nothing. The result goes into :data:`button`.

    If the game asks to stop while waiting, or its last window disappears, the
    wait ends and :data:`button` becomes ``None`` rather than keeping the
    previous click.

    Raises:
        TrjoLudusError: If called while no game is running, or if ``what`` is
            not :data:`trjoludus.input.mouse`.
    """
    if what is not any_input:
        raise TrjoLudusError(
            f"mouse.wait() takes input.mouse, not {what!r}. It is the only "
            f"kind of mouse input TrjoLudus can wait for so far."
        )

    from trjoludus.app import current_application

    application = current_application()
    if application is None:
        raise TrjoLudusError(
            "mouse.wait() only works while a game is running. Call it from "
            "on_start or on_update, inside a game started with tl.run()."
        )
    application.wait_for_input(kind="mouse")
