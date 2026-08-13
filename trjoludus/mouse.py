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

Coordinates are pixels from the top-left corner of the window's drawable area,
matching everything else in TrjoLudus. The pointer can be outside the window,
in which case the position is simply the last place it was seen.
"""

from trjoludus.errors import TrjoLudusError
from trjoludus.events import MOUSE_BUTTONS

__all__ = ["button", "position", "pressed", "wait", "x", "y"]


class _AnyMouseInput:
    """The value :data:`trjoludus.input.mouse` refers to."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "input.mouse"


#: Passed to :func:`wait` to mean "any mouse button". An argument rather than
#: implied, so waiting for one particular button can be added later without
#: the call reading differently.
any_input = _AnyMouseInput()


class _State:
    """What the engine knows about the pointer right now."""

    __slots__ = ("x", "y", "held", "button")

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.x = 0
        self.y = 0
        self.held: set[str] = set()
        #: The button most recently reported by :func:`wait`.
        self.button: str | None = None


_state = _State()


def _moved(x: int, y: int) -> None:
    """Engine-internal: record a new pointer position."""
    _state.x = x
    _state.y = y


def _button_down(name: str, x: int, y: int) -> None:
    """Engine-internal: record a button going down."""
    _state.held.add(name)
    _moved(x, y)


def _button_up(name: str, x: int, y: int) -> None:
    """Engine-internal: record a button coming up."""
    _state.held.discard(name)
    _moved(x, y)


def _reset() -> None:
    """Engine-internal: forget everything, between runs."""
    _state.reset()


def __getattr__(name: str):
    """Serve :data:`x`, :data:`y`, :data:`position` and :data:`button`.

    They are looked up rather than stored so that reading ``mouse.x`` always
    gives the current answer. Nothing has to be refreshed, and there is no
    copy of the position to fall out of date.
    """
    if name == "x":
        return _state.x
    if name == "y":
        return _state.y
    if name == "position":
        return (_state.x, _state.y)
    if name == "button":
        return _state.button
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def pressed(name: str) -> bool:
    """Whether a mouse button is held down right now.

    Args:
        name: ``"LEFT"``, ``"RIGHT"`` or ``"MIDDLE"``.

    Raises:
        TypeError: If ``name`` is not a string.
        ValueError: If it is not a button TrjoLudus knows.
    """
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
    return name in _state.held


def wait(what) -> None:
    """Wait for a mouse button press and record which one it was.

    Like :func:`trjoludus.keyboard.wait`, this hands you nothing to store: it
    updates :data:`button`. Each press answers exactly one call, in the order
    the presses happened, so calling twice waits twice rather than reporting
    the same click again.

    Moving the pointer does not end the wait -- only a button going down does.
    Afterwards :data:`x` and :data:`y` report where that click happened, not
    wherever the pointer has since drifted to.

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
    click = application._wait_for_mouse()
    if click is None:
        _state.button = None
        return
    name, x, y = click
    _state.button = name
    # Report where the click happened. Several events can arrive in one batch,
    # so the pointer may already have moved on; the click's own position is
    # what a game acting on it means.
    _moved(x, y)
