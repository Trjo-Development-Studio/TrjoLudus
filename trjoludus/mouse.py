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

**:func:`pressed` and :data:`button` answer different questions.**

``mouse.pressed("LEFT")`` asks *is the left button down right now*. It follows
the physical button: true from the moment it goes down until it comes up, true
on every frame in between, and false again afterwards. Nothing consumes it, so
two calls in the same frame give the same answer.

``mouse.button`` says *which button the last mouse input that was read was*.
It is set by :func:`wait` (and by :func:`trjoludus.input.wait` when a click is
what arrived), and it does not change until the next one is read. It is
``None`` until something has been read, and it stays at its last value long
after that button came back up.

So they disagree exactly when you would expect them to::

    mouse.wait(input.mouse)     # player clicks the left button and releases

    mouse.button                # "LEFT"  -- what was read
    mouse.pressed("LEFT")       # False   -- it is not held any more

Use :func:`pressed` for "while the button is down" -- dragging, holding to
charge a shot. Use :data:`button` after a wait, to ask which button ended it.
For "was this drawing clicked this frame", neither is the tool: ask the
drawing, with ``button.mouse.clicked()``.

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
        #: Which button the most recently read mouse input was. Set when a
        #: wait hands a press out, and left alone until the next one -- so it
        #: still names a button long after that button came back up.
        #: ``None`` until a press has been read.
        self.button: str | None = None

    @property
    def position(self) -> tuple[int, int]:
        """``(x, y)`` of the pointer in this window."""
        return (self.x, self.y)

    def pressed(self, name: str) -> bool:
        """Whether a button is held down in this window right now.

        Current state, not a record of an event: it becomes true when the
        button goes down and false when it comes up, and reading it does not
        use it up. :attr:`button` is the other question -- which button the
        last input that was *read* was.
        """
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

    True for as long as the button is physically down, on every frame in
    between, and reading it does not consume anything. This is the question to
    ask while something is being held; :data:`button` is the question to ask
    after a :func:`wait` about which button ended it.

    Args:
        name: ``"LEFT"``, ``"RIGHT"`` or ``"MIDDLE"``.

    Raises:
        TypeError: If ``name`` is not a string.
        ValueError: If it is not a button TrjoLudus knows.
    """
    return active_state().pressed(_check_button(name))


def wait(what=None) -> "str | None":
    """Wait for a mouse button press and return which one it was.

    ::

        clicked = mouse.wait()

        if clicked == "LEFT":
            print("clicked at", mouse.x, mouse.y)

    Each press answers exactly one call, in the order
    the presses happened, so calling twice waits twice rather than reporting
    the same click again.

    Only the mouse ends this wait. Moving the pointer does not, and neither
    does a key press -- a key waiting to be read stays in the queue for
    whoever asks for it. Afterwards :data:`x` and :data:`y` report where the
    click happened, not wherever the pointer has since drifted to.

    Args:
        what: Nothing. Accepted so that ``mouse.wait(input.mouse)``, the way
            this used to be written, keeps working.

    Returns:
        The button name -- ``"LEFT"``, ``"RIGHT"`` or ``"MIDDLE"``. ``None`` if
        the game asked to stop while waiting, or its last window disappeared.

        :data:`button` is updated too, as a mirror for games written before
        this returned anything.

    Raises:
        TrjoLudusError: If called while no game is running, or if ``what`` is
            something other than :data:`trjoludus.input.mouse`.
    """
    if what is not None and what is not any_input:
        raise TrjoLudusError(
            f"mouse.wait() takes no arguments, and got {what!r}. Write "
            f"'clicked = mouse.wait()' -- it returns the button."
        )

    from trjoludus.app import current_application

    application = current_application()
    if application is None:
        raise TrjoLudusError(
            "mouse.wait() only works while a game is running. Call it from "
            "on_start or on_update, inside a game started with tl.run()."
        )
    taken = application.wait_for_input(kind="mouse")
    return None if taken is None else taken.value
