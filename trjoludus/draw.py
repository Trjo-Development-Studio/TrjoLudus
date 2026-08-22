"""Drawing the user interface.

::

    draw.rect(10, 10, 120, 40, color.blue)
    draw.text(20, 25, "Score: 0", color.white)
    draw.line(0, 60, 200, 60, color.white)

**What is drawn stays drawn.** These are not per-frame paint calls: the engine
remembers them and draws them every frame, the same way it remembers the
objects :mod:`trjoludus.create` makes. Draw a menu once when the game starts
rather than again on every update -- drawing in ``on_update`` would add another
copy each frame. :func:`clear` throws away what has been drawn.

**This is the interface, not the world.** ``draw`` is for scores, menus,
titles and buttons: shapes and text, on top of everything, that can be
clicked and hidden. ``create`` is for the things a game is *about* -- they
have an image, they collide and they animate. Both are kept and redrawn until
something removes them; what differs is what the thing is.

For a whole screen that gets switched on and off, give it a name::

    start_menu = draw.list("start_menu")
    start_menu.rect(20, 20, 200, 80, color.blue)
    start_menu.text(30, 50, "Play", color.white)

    start_menu.hide()
    start_menu.show()

UI is drawn on top of the game's objects. Coordinates are pixels from the
top-left corner of the window, matching everything else.

Images are not drawn here: they are objects in the world, made with
:func:`trjoludus.create.image`, and they carry their own colours.
"""

from trjoludus.ui import DrawList, current_ui

__all__ = ["clear", "line", "list", "rect", "text"]

#: The list plain ``draw.rect(...)`` and friends go into. It is an ordinary
#: list with a reserved name, so the unnamed and named forms behave alike.
DEFAULT_LIST_NAME = "default"

# Keep a reference to the builtin, because `list` is shadowed below.
_builtin_list = list


def _default() -> DrawList:
    ui = current_ui()
    if DEFAULT_LIST_NAME in ui:
        return ui.require(DEFAULT_LIST_NAME)
    return ui.add(DEFAULT_LIST_NAME)


def line(x: int, y: int, end_x: int, end_y: int, colour) -> DrawList:
    """Draw a line from ``(x, y)`` to ``(end_x, end_y)``."""
    return _default().line(x, y, end_x, end_y, colour)


def rect(x: int, y: int, width: int, height: int, colour) -> DrawList:
    """Draw a filled rectangle with its top-left corner at ``(x, y)``."""
    return _default().rect(x, y, width, height, colour)


def text(x: int, y: int, message: str, colour) -> DrawList:
    """Draw text with its top-left corner at ``(x, y)``."""
    return _default().text(x, y, message, colour)


def clear() -> None:
    """Forget everything drawn without a list.

    Named lists are untouched; clear those through the list itself.
    """
    ui = current_ui()
    if DEFAULT_LIST_NAME in ui:
        ui.require(DEFAULT_LIST_NAME).clear()


def list(name: str) -> DrawList:  # noqa: A001 -- the public API spells it this way
    """Make a new named drawing list.

    Args:
        name: What to call it. Must not already be taken.

    Returns:
        The list, ready to be drawn into.

    Raises:
        TypeError: If ``name`` is not a string.
        ValueError: If ``name`` is empty.
        UiError: If a list with that name already exists.
    """
    if not isinstance(name, str):
        raise TypeError(
            f"a drawing list name must be a string, got {type(name).__name__}"
        )
    if not name:
        raise ValueError("a drawing list needs a name; got an empty string")
    return current_ui().add(name)
