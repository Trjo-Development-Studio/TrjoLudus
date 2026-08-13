"""Drawing lists, and the interactive things in them.

A list is prepared once and then switched on and off as a whole::

    start_menu = draw.list("start_menu")
    play_button = start_menu.rect(20, 20, 200, 80, color.blue)
    start_menu.text(30, 50, "Play", color.white)

    start_menu.hide()
    start_menu.show()

**What is drawn is remembered.** A list keeps its contents until they are
cleared or the list is destroyed, so a menu does not have to be rebuilt every
frame. That matches how game objects work: a game says what should exist, and
the engine keeps drawing it.

**Each drawing is a thing you can hold.** Every call returns a
:class:`Drawable`, which can be scaled and asked about the mouse::

    if play_button.mouse.hover():
        play_button.set.scale(1.1)

    if play_button.mouse.clicked():
        start_game()

UI is drawn after the scene, so it sits on top of the game, and lists are
drawn in the order they were created. That same order decides interaction:
where two things overlap, the one drawn last -- the one you can see -- is the
one the mouse finds.
"""

from trjoludus import color as color_module
from trjoludus import font
from trjoludus.errors import TrjoLudusError

__all__ = ["Drawable", "DrawList", "UiError", "current_ui"]


class UiError(TrjoLudusError):
    """Raised when a drawing list or drawing is missing, duplicated, or gone."""


def _whole_number(value, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(
            f"{label} must be a whole number of pixels, got "
            f"{type(value).__name__}"
        )
    return value


def _scale_factor(value, label: str = "a scale") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{label} must be a number, got {type(value).__name__}"
        )
    if value <= 0:
        raise ValueError(
            f"{label} must be greater than zero, got {value}. A scale of 1 is "
            f"the drawing's normal size."
        )
    return float(value)


class _Scaling:
    """``set``/``add``/``remove`` for a drawing's scale.

    Three namespaces rather than one method because the three read
    differently at the call site: setting an exact size, growing, shrinking.
    Only scale lives here -- position keeps ``move``, which already means the
    same thing.
    """

    __slots__ = ("_drawable", "_how")

    def __init__(self, drawable: "Drawable", how: str) -> None:
        self._drawable = drawable
        self._how = how

    def scale(self, amount) -> "Drawable":
        """Set, add to, or subtract from the drawing's scale."""
        drawable = self._drawable
        drawable._live()
        if self._how == "set":
            drawable._scale = _scale_factor(amount)
        elif self._how == "add":
            drawable._scale = _scale_factor(
                drawable._scale + _scale_factor(amount, "an amount to add")
            )
        else:
            drawable._scale = _scale_factor(
                drawable._scale - _scale_factor(amount, "an amount to remove"),
                "the resulting scale",
            )
        return drawable

    def __repr__(self) -> str:
        return f"_Scaling({self._how!r})"


class DrawableMouse:
    """What the mouse is doing to one drawing.

    Reached as :attr:`Drawable.mouse`. Both questions are about *this*
    drawing: they answer ``False`` when it is hidden, when something visible
    covers it, or when the pointer belongs to a different window.
    """

    __slots__ = ("_drawable",)

    def __init__(self, drawable: "Drawable") -> None:
        self._drawable = drawable

    def hover(self) -> bool:
        """Whether the pointer is over this drawing right now.

        ``False`` if the drawing or its list is hidden, or if another visible
        drawing covers the same point -- only the topmost is hovered, so a
        button behind a panel does not light up.
        """
        drawable = self._drawable
        drawable._live()
        if not drawable.showing:
            return False

        application, window = drawable._application_and_window()
        if application is None:
            return False

        state = application.mouse_state(window)
        return current_ui().topmost_at(state.x, state.y, window) is drawable

    def clicked(self) -> bool:
        """Whether a mouse button was pressed on this drawing this frame.

        A click is a moment, not a condition: holding the button down does not
        keep this true. It answers for the frame the press arrived in, and
        answers the same however many times it is asked within that frame.

        Only a press that landed on this drawing counts, and only from this
        drawing's own window.
        """
        drawable = self._drawable
        drawable._live()
        if not drawable.showing:
            return False

        application, window = drawable._application_and_window()
        if application is None:
            return False

        ui = current_ui()
        for click in application.clicks_this_frame(window):
            if ui.topmost_at(click.x, click.y, window) is drawable:
                return True
        return False

    def __repr__(self) -> str:
        return f"DrawableMouse({self._drawable!r})"


class Drawable:
    """One remembered drawing: a line, a rectangle or some text.

    Made by the methods on :class:`DrawList`, never directly. It knows how to
    draw itself into a frame buffer and what area it occupies, and nothing
    about windows or backends.
    """

    __slots__ = ("kind", "args", "colour", "_scale", "_visible", "_list",
                 "_removed", "_mouse", "set", "add", "remove")

    def __init__(self, kind: str, args: tuple, colour: tuple,
                 owner: "DrawList") -> None:
        self.kind = kind
        self.args = args
        self.colour = colour
        self._scale = 1.0
        self._visible = True
        self._list = owner
        self._removed = False
        self._mouse = DrawableMouse(self)
        self.set = _Scaling(self, "set")
        self.add = _Scaling(self, "add")
        self.remove = _Scaling(self, "remove")

    # --- state ------------------------------------------------------------

    @property
    def mouse(self) -> DrawableMouse:
        """Ask what the mouse is doing to this drawing."""
        return self._mouse

    @property
    def scale(self) -> float:
        """How much bigger than normal this drawing is. 1.0 is normal."""
        return self._scale

    @property
    def visible(self) -> bool:
        """Whether this drawing is shown, ignoring its list."""
        return self._visible

    @property
    def showing(self) -> bool:
        """Whether this drawing actually appears: it *and* its list visible."""
        return self._visible and self._list.visible and not self._removed

    @property
    def list(self) -> "DrawList":
        """The list this drawing belongs to."""
        return self._list

    def show(self) -> "Drawable":
        """Draw this again."""
        self._live()
        self._visible = True
        return self

    def hide(self) -> "Drawable":
        """Stop drawing this, keeping it in its list."""
        self._live()
        self._visible = False
        return self

    def _live(self) -> None:
        if self._removed or self._list._destroyed:
            raise UiError(
                f"This drawing is no longer part of {self._list.name!r} -- "
                f"the list was cleared or destroyed. Draw it again if you "
                f"still need it."
            )

    def _application_and_window(self):
        """The running application and the window this drawing appears in."""
        from trjoludus.app import current_application

        application = current_application()
        if application is None:
            return None, None
        return application, self._list.window_or(application)

    # --- geometry ---------------------------------------------------------

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """``(left, top, right, bottom)`` of the area this occupies.

        Scaling grows a drawing from its top-left corner, which is where its
        position already is -- so scaling never moves the corner a game placed.
        """
        scale = self._scale
        if self.kind == "rect":
            x, y, width, height = self.args
            return (x, y, x + round(width * scale), y + round(height * scale))
        if self.kind == "text":
            text, x, y = self.args
            width, height = font.measure(text)
            return (x, y, x + round(width * scale), y + round(height * scale))
        # A line: the box its two ends span.
        x, y, end_x, end_y = self._scaled_line()
        return (min(x, end_x), min(y, end_y), max(x, end_x) + 1,
                max(y, end_y) + 1)

    def _scaled_line(self) -> tuple[int, int, int, int]:
        x, y, end_x, end_y = self.args
        scale = self._scale
        return (x, y,
                x + round((end_x - x) * scale),
                y + round((end_y - y) * scale))

    def contains(self, x: int, y: int) -> bool:
        """Whether a point falls inside this drawing's area."""
        left, top, right, bottom = self.bounds
        return left <= x < right and top <= y < bottom

    # --- drawing ----------------------------------------------------------

    def render(self, framebuffer) -> None:
        """Draw this, at its current scale."""
        if not self._visible:
            return
        scale = self._scale

        if self.kind == "line":
            framebuffer.draw_line(*self._scaled_line(), self.colour)
            return

        if self.kind == "rect":
            x, y, width, height = self.args
            framebuffer.fill_rect(x, y, round(width * scale),
                                  round(height * scale), self.colour)
            return

        text, x, y = self.args
        if scale == 1.0:
            framebuffer.draw_text(text, x, y, self.colour)
            return
        self._render_scaled_text(framebuffer, text, x, y, scale)

    def _render_scaled_text(self, framebuffer, text, x, y, scale) -> None:
        """Draw text larger by turning each font pixel into a block.

        The block is measured from the scaled edges rather than being a fixed
        size, so a fractional scale still tiles without gaps or overlaps.
        """
        pen = 0
        for character in text:
            for column, bits in enumerate(font.columns_for(character)):
                if not bits:
                    continue
                for row in range(font.CHARACTER_HEIGHT):
                    if not bits & (1 << row):
                        continue
                    left = x + round((pen + column) * scale)
                    top = y + round(row * scale)
                    right = x + round((pen + column + 1) * scale)
                    bottom = y + round((row + 1) * scale)
                    framebuffer.fill_rect(left, top, max(1, right - left),
                                          max(1, bottom - top), self.colour)
            pen += font.CHARACTER_WIDTH + font.SPACING

    def __repr__(self) -> str:
        return f"Drawable({self.kind!r}, scale={self._scale}, {self.args!r})"


class DrawList:
    """A named group of drawing that can be shown or hidden together.

    Created through :func:`trjoludus.draw.list`, not directly.
    """

    __slots__ = ("_name", "_drawings", "_visible", "_destroyed", "_window")

    def __init__(self, name: str, window=None) -> None:
        self._name = name
        self._drawings: list[Drawable] = []
        self._visible = True
        self._destroyed = False
        # Which window this list appears in. ``None`` means the one the
        # running game owns, which is the only one a game can have today.
        self._window = window

    @property
    def name(self) -> str:
        """The name this list was created with."""
        return self._name

    @property
    def visible(self) -> bool:
        """Whether the engine draws this list."""
        return self._visible

    def window_or(self, application):
        """The window this list appears in, given a running application."""
        return self._window if self._window is not None else application._window

    def __len__(self) -> int:
        return len(self._drawings)

    def drawings(self) -> tuple[Drawable, ...]:
        """Everything in this list, in draw order."""
        return tuple(self._drawings)

    def _live(self) -> None:
        if self._destroyed:
            raise UiError(
                f"The drawing list {self._name!r} has been destroyed and "
                f"cannot be used any more. Make it again with "
                f'draw.list("{self._name}") if you still need it.'
            )

    def line(self, x: int, y: int, end_x: int, end_y: int,
             colour) -> Drawable:
        """Add a line from ``(x, y)`` to ``(end_x, end_y)``."""
        self._live()
        for label, value in (("x", x), ("y", y),
                             ("end_x", end_x), ("end_y", end_y)):
            _whole_number(value, label)
        return self._add(
            Drawable("line", (x, y, end_x, end_y),
                     color_module.check(colour, "a line colour"), self)
        )

    def rect(self, x: int, y: int, width: int, height: int,
             colour) -> Drawable:
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
        return self._add(
            Drawable("rect", (x, y, width, height),
                     color_module.check(colour, "a rectangle colour"), self)
        )

    def text(self, x: int, y: int, message: str, colour) -> Drawable:
        """Add text with its top-left corner at ``(x, y)``."""
        self._live()
        for label, value in (("x", x), ("y", y)):
            _whole_number(value, label)
        if not isinstance(message, str):
            raise TypeError(
                f"text must be a string, got {type(message).__name__}"
            )
        return self._add(
            Drawable("text", (message, x, y),
                     color_module.check(colour, "a text colour"), self)
        )

    def _add(self, drawing: Drawable) -> Drawable:
        self._drawings.append(drawing)
        return drawing

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
        for drawing in self._drawings:
            drawing._removed = True
        self._drawings.clear()
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
        for drawing in self._drawings:
            drawing.render(framebuffer)

    def __repr__(self) -> str:
        state = "destroyed" if self._destroyed else (
            "visible" if self._visible else "hidden"
        )
        return f"DrawList({self._name!r}, {len(self._drawings)} items, {state})"


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

    def drawings(self) -> tuple[Drawable, ...]:
        """Every drawing everywhere, in the order they are drawn.

        Lists in creation order, and within a list the order things were
        added -- so the last one here is the one on top.
        """
        return tuple(
            drawing
            for drawing_list in self._lists.values()
            for drawing in drawing_list.drawings()
        )

    def topmost_at(self, x: int, y: int, window=None) -> Drawable | None:
        """The drawing the mouse would find at a point, or ``None``.

        Searches back to front, so where several things overlap the one drawn
        last wins -- the one actually visible there. Hidden drawings, hidden
        lists and drawings belonging to another window are skipped rather than
        blocking what is underneath them.
        """
        from trjoludus.app import current_application

        application = current_application()
        for drawing in reversed(self.drawings()):
            if not drawing.showing:
                continue
            if window is not None and application is not None:
                if drawing._list.window_or(application) is not window:
                    continue
            if drawing.contains(x, y):
                return drawing
        return None

    def add(self, name: str, window=None) -> DrawList:
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
        created = DrawList(name, window)
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
        for drawing_list in self._lists.values():
            drawing_list._destroyed = True
        self._lists.clear()

    def render(self, framebuffer) -> None:
        """Draw every visible list, oldest first."""
        for drawing_list in self._lists.values():
            drawing_list.render(framebuffer)


_current = Ui()


def current_ui() -> Ui:
    """The drawing lists the engine draws.

    One per process, cleared when a run finishes, so a second game does not
    inherit the first one's menus.
    """
    return _current
