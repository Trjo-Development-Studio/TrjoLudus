"""Drawing lists: named groups of UI drawing that can be shown or hidden.

A list is prepared once and then switched on and off as a whole::

    start_menu = draw.list("start_menu")
    start_menu.rect(20, 20, 200, 80, color.blue)
    start_menu.text(30, 50, "Play", color.white)

    start_menu.hide()
    start_menu.show()

**What is drawn is remembered.** A list keeps its contents until they are
cleared or the list is destroyed, so a menu does not have to be rebuilt every
frame. That matches how game objects work: a game says what should exist, and
the engine keeps drawing it.

UI is drawn after the scene, so it sits on top of the game rather than behind
it, and lists are drawn in the order they were created.
"""

from trjoludus import color as color_module
from trjoludus.errors import TrjoLudusError

__all__ = ["DrawList", "UiError", "current_ui"]


class UiError(TrjoLudusError):
    """Raised when a drawing list is missing, duplicated, or misused."""


class _Command:
    """One remembered drawing operation.

    Deliberately dumb: it holds what to draw and knows how to draw itself into
    a frame buffer. Nothing here knows about windows or backends.
    """

    __slots__ = ("kind", "args", "colour")

    def __init__(self, kind: str, args: tuple, colour: tuple) -> None:
        self.kind = kind
        self.args = args
        self.colour = colour

    def render(self, framebuffer) -> None:
        if self.kind == "line":
            framebuffer.draw_line(*self.args, self.colour)
        elif self.kind == "rect":
            framebuffer.fill_rect(*self.args, self.colour)
        elif self.kind == "text":
            text, x, y = self.args
            framebuffer.draw_text(text, x, y, self.colour)

    def __repr__(self) -> str:
        return f"_Command({self.kind!r}, {self.args!r}, {self.colour!r})"


def _whole_number(value, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(
            f"{label} must be a whole number of pixels, got "
            f"{type(value).__name__}"
        )
    return value


class DrawList:
    """A named group of drawing that can be shown or hidden together.

    Created through :func:`trjoludus.draw.list`, not directly.
    """

    __slots__ = ("_name", "_commands", "_visible", "_destroyed")

    def __init__(self, name: str) -> None:
        self._name = name
        self._commands: list[_Command] = []
        self._visible = True
        self._destroyed = False

    @property
    def name(self) -> str:
        """The name this list was created with."""
        return self._name

    @property
    def visible(self) -> bool:
        """Whether the engine draws this list."""
        return self._visible

    def __len__(self) -> int:
        return len(self._commands)

    def _live(self) -> None:
        if self._destroyed:
            raise UiError(
                f"The drawing list {self._name!r} has been destroyed and "
                f"cannot be used any more. Make it again with "
                f'draw.list("{self._name}") if you still need it.'
            )

    def line(self, x: int, y: int, end_x: int, end_y: int, colour) -> "DrawList":
        """Add a line from ``(x, y)`` to ``(end_x, end_y)``."""
        self._live()
        for label, value in (("x", x), ("y", y),
                             ("end_x", end_x), ("end_y", end_y)):
            _whole_number(value, label)
        self._commands.append(
            _Command("line", (x, y, end_x, end_y),
                     color_module.check(colour, "a line colour"))
        )
        return self

    def rect(self, x: int, y: int, width: int, height: int,
             colour) -> "DrawList":
        """Add a filled rectangle with its top-left corner at ``(x, y)``."""
        self._live()
        for label, value in (("x", x), ("y", y),
                             ("width", width), ("height", height)):
            _whole_number(value, label)
        if width < 0 or height < 0:
            raise ValueError(
                f"a rectangle cannot have a negative size, got "
                f"{width}x{height}"
            )
        self._commands.append(
            _Command("rect", (x, y, width, height),
                     color_module.check(colour, "a rectangle colour"))
        )
        return self

    def text(self, x: int, y: int, message: str, colour) -> "DrawList":
        """Add text with its top-left corner at ``(x, y)``."""
        self._live()
        for label, value in (("x", x), ("y", y)):
            _whole_number(value, label)
        if not isinstance(message, str):
            raise TypeError(
                f"text must be a string, got {type(message).__name__}"
            )
        self._commands.append(
            _Command("text", (message, x, y),
                     color_module.check(colour, "a text colour"))
        )
        return self

    def show(self) -> "DrawList":
        """Draw this list again."""
        self._live()
        self._visible = True
        return self

    def hide(self) -> "DrawList":
        """Stop drawing this list, keeping its contents."""
        self._live()
        self._visible = False
        return self

    def clear(self) -> "DrawList":
        """Forget everything in this list, keeping the list itself."""
        self._live()
        self._commands.clear()
        return self

    def destroy(self) -> None:
        """Remove this list for good and free its name."""
        self._live()
        current_ui().remove(self._name)
        self._destroyed = True

    def render(self, framebuffer) -> None:
        """Draw this list's contents, if it is visible."""
        if not self._visible or self._destroyed:
            return
        for command in self._commands:
            command.render(framebuffer)

    def __repr__(self) -> str:
        state = "destroyed" if self._destroyed else (
            "visible" if self._visible else "hidden"
        )
        return f"DrawList({self._name!r}, {len(self._commands)} items, {state})"


class Ui:
    """Every drawing list that currently exists, in creation order."""

    def __init__(self) -> None:
        self._lists: dict[str, DrawList] = {}

    def __len__(self) -> int:
        return len(self._lists)

    def __contains__(self, name: object) -> bool:
        return name in self._lists

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._lists)

    def lists(self) -> tuple[DrawList, ...]:
        """Every list, in the order they were created."""
        return tuple(self._lists.values())

    def add(self, name: str) -> DrawList:
        """Create a list.

        Raises:
            UiError: If the name is taken. Replacing silently would lose
                whatever the first list held, with nothing to show for it.
        """
        if name in self._lists:
            raise UiError(
                f"There is already a drawing list named {name!r}. "
                f"Every list needs its own name -- pick a different one, or "
                f"clear the existing list instead of making a second."
            )
        created = DrawList(name)
        self._lists[name] = created
        return created

    def require(self, name: str) -> DrawList:
        """Return an existing list.

        Raises:
            UiError: If no list has that name.
        """
        try:
            return self._lists[name]
        except KeyError:
            if not self._lists:
                raise UiError(
                    f"There is no drawing list named {name!r}: none have been "
                    f'made yet. Make one with draw.list("{name}").'
                ) from None
            existing = ", ".join(repr(n) for n in self._lists)
            raise UiError(
                f"There is no drawing list named {name!r}. "
                f"Existing lists: {existing}."
            ) from None

    def remove(self, name: str) -> None:
        self._lists.pop(name, None)

    def clear(self) -> None:
        """Forget every list."""
        for drawing in self._lists.values():
            drawing._destroyed = True
        self._lists.clear()

    def render(self, framebuffer) -> None:
        """Draw every visible list, oldest first."""
        for drawing in self._lists.values():
            drawing.render(framebuffer)


_current = Ui()


def current_ui() -> Ui:
    """The drawing lists the engine draws.

    One per process, cleared when a run finishes, so a second game does not
    inherit the first one's menus.
    """
    return _current
