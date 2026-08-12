"""Named game objects and the scene that holds them.

A game says what should exist; the engine keeps track of it and draws it::

    tl.create.image(100, 100, "player.png", "player")
    player = tl.GameObject("player")

**Coordinates.** The origin is the top-left corner of the window, x increases
to the right, y increases downward, and the unit is one pixel. A position is
the top-left corner of the image, not its centre. This matches what both X11
and Win32 use natively, so nothing has to be transformed on the way to the
screen. Camera and world coordinates are a later concern.

**Two classes for one idea, on purpose.** :class:`SceneObject` is the record
the engine owns and draws. :class:`GameObject` is the handle a game holds. The
split means a handle carries no state of its own, so anything a game does
through it acts on what the engine is actually drawing, and a future
``player.move.x(50)`` has an obvious place to live.
"""

from trjoludus.errors import TrjoLudusError

__all__ = [
    "GameObject",
    "Movement",
    "Scene",
    "SceneError",
    "SceneObject",
    "current_scene",
]


class SceneError(TrjoLudusError):
    """Raised when a named object is missing, duplicated, or invalid."""


class SceneObject:
    """One drawable thing the engine owns.

    Games do not build these directly; :func:`trjoludus.create.image` creates
    them and :class:`GameObject` reaches them.
    """

    __slots__ = ("name", "image", "x", "y", "visible", "removed")

    def __init__(self, name: str, image, x: int, y: int) -> None:
        self.name = name
        self.image = image
        self.x = x
        self.y = y
        self.visible = True
        #: Set when the object leaves the scene. Handles check it so that
        #: using one afterwards is an error rather than a silent no-op.
        self.removed = False

    def __repr__(self) -> str:
        return (
            f"SceneObject({self.name!r}, at=({self.x}, {self.y}), "
            f"size={self.image.size})"
        )


class Scene:
    """The named objects that currently exist.

    Insertion order is draw order: an object added later is drawn over one
    added earlier.
    """

    def __init__(self) -> None:
        self._objects: dict[str, SceneObject] = {}

    def __len__(self) -> int:
        return len(self._objects)

    def __contains__(self, name: object) -> bool:
        return name in self._objects

    @property
    def names(self) -> tuple[str, ...]:
        """Every registered name, in the order the objects were added."""
        return tuple(self._objects)

    def objects(self) -> tuple[SceneObject, ...]:
        """Every object, in draw order."""
        return tuple(self._objects.values())

    def add(self, obj: SceneObject) -> SceneObject:
        """Register an object under its name.

        Raises:
            SceneError: If the name is already taken. Replacing silently would
                make a mistyped or repeated name look like it worked while one
                of the objects quietly vanished.
        """
        if obj.name in self._objects:
            raise SceneError(
                f"There is already a game object named {obj.name!r}. "
                f"Every object needs its own name -- pick a different one, or "
                f"remove the existing object first."
            )
        self._objects[obj.name] = obj
        return obj

    def require(self, name: str) -> SceneObject:
        """Return the object registered under ``name``.

        Raises:
            SceneError: If nothing is registered under that name.
        """
        try:
            return self._objects[name]
        except KeyError:
            raise SceneError(self._missing_message(name)) from None

    def remove(self, name: str) -> None:
        """Remove an object.

        Raises:
            SceneError: If nothing is registered under that name.
        """
        removed = self._objects.pop(name, None)
        if removed is None:
            raise SceneError(self._missing_message(name))
        removed.removed = True

    def clear(self) -> None:
        """Forget every object."""
        for obj in self._objects.values():
            obj.removed = True
        self._objects.clear()

    def _missing_message(self, name: str) -> str:
        if not self._objects:
            return (
                f"There is no game object named {name!r}: nothing has been "
                f"created yet. Create it first, for example with "
                f"create.image(x, y, \"picture.png\", {name!r})."
            )
        existing = ", ".join(repr(n) for n in self._objects)
        return (
            f"There is no game object named {name!r}. "
            f"Existing objects: {existing}."
        )


_current = Scene()


def current_scene() -> Scene:
    """The scene new objects go into and the engine draws.

    There is one scene per process. An application clears it when a run
    finishes, so a second :func:`trjoludus.run` does not inherit the first
    game's objects; anything created before a run still takes part in it.
    """
    return _current


def _check_pixels(label: str, value) -> int:
    """Reject anything that is not a whole number of pixels.

    Positions index into the frame buffer, so a float would fail much later
    with a message about slice indices. Catching it here says what is actually
    wrong. ``bool`` is excluded because ``True`` as a distance is a mistake,
    not an intention.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(
            f"{label} must be a whole number of pixels, got "
            f"{type(value).__name__}"
        )
    return value


class Movement:
    """Moves one object relative to where it currently is.

    Reached as :attr:`GameObject.move`::

        player.move.x(50)    # 50 pixels right
        player.move.x(-50)   # 50 pixels left
        player.move.y(50)    # 50 pixels down
        player.move.y(-50)   # 50 pixels up

    Every call is relative, so they add up: two ``move.x(50)`` calls move the
    object 100 pixels in total. To put an object at an exact place, assign to
    :attr:`GameObject.x` or :attr:`GameObject.y` instead.

    Nothing is clamped. An object may be moved partly or wholly outside the
    window; there is no world boundary, and inventing one here would surprise
    a game that meant to move something off screen.
    """

    __slots__ = ("_owner",)

    def __init__(self, owner: "GameObject") -> None:
        self._owner = owner

    def x(self, pixels: int) -> None:
        """Move right by ``pixels``, or left if negative.

        Raises:
            TypeError: If ``pixels`` is not a whole number.
            SceneError: If the object has been removed.
        """
        obj = self._owner._live()
        obj.x += _check_pixels("a movement distance", pixels)

    def y(self, pixels: int) -> None:
        """Move down by ``pixels``, or up if negative.

        Raises:
            TypeError: If ``pixels`` is not a whole number.
            SceneError: If the object has been removed.
        """
        obj = self._owner._live()
        obj.y += _check_pixels("a movement distance", pixels)

    def __repr__(self) -> str:
        return f"Movement({self._owner.name!r})"


class GameObject:
    """A game's handle on a named object.

    Looks up an object that already exists -- it does not create one. Objects
    come into being through :func:`trjoludus.create.image`::

        tl.create.image(100, 100, "player.png", "player")
        player = tl.GameObject("player")

    Position can be set outright or changed by a relative amount::

        player.x = 250       # put it at x = 250
        player.move.x(50)    # and then 50 pixels further right

    Args:
        name: The name the object was created with.

    Raises:
        SceneError: If no object has that name. The message lists the names
            that do exist.
    """

    __slots__ = ("_object", "_move")

    def __init__(self, name: str) -> None:
        if not isinstance(name, str):
            raise TypeError(
                f"a game object name must be a string, got "
                f"{type(name).__name__}"
            )
        self._object = current_scene().require(name)
        self._move = Movement(self)

    def _live(self) -> SceneObject:
        """Return the scene object, or explain that it is gone.

        A handle outlives the object it points at -- something can be removed
        while a game still holds a reference to it. Letting that keep working
        would move an object nobody draws, which looks like the engine
        ignoring the game.
        """
        if self._object.removed:
            raise SceneError(
                f"The game object {self._object.name!r} has been destroyed and "
                f"cannot be used any more. If you need it again, create it "
                f"with create.image(...); destroying is permanent."
            )
        return self._object

    @property
    def move(self) -> Movement:
        """Relative movement: ``player.move.x(50)``."""
        return self._move

    def destroy(self) -> None:
        """Remove this object from the game for good.

        It stops being drawn, its name becomes free again, and
        ``GameObject(name)`` no longer finds it. Every handle to it -- not
        just this one -- stops working, so nothing can go on moving something
        that is gone.

        Raises:
            SceneError: If the object has already been destroyed. Destroying
                twice is a mistake worth hearing about: the second call cannot
                mean anything, and staying silent would hide the same
                confusion in code that runs it in a loop.
        """
        obj = self._live()
        current_scene().remove(obj.name)

    @property
    def name(self) -> str:
        """The name this object was created with."""
        return self._object.name

    @property
    def x(self) -> int:
        """Distance in pixels from the left edge of the window.

        Assigning sets an absolute position; :attr:`move` changes it by a
        relative amount.
        """
        return self._live().x

    @x.setter
    def x(self, value: int) -> None:
        self._live().x = _check_pixels("x", value)

    @property
    def y(self) -> int:
        """Distance in pixels from the top edge of the window.

        Assigning sets an absolute position; :attr:`move` changes it by a
        relative amount.
        """
        return self._live().y

    @y.setter
    def y(self, value: int) -> None:
        self._live().y = _check_pixels("y", value)

    @property
    def position(self) -> tuple[int, int]:
        """``(x, y)`` of the image's top-left corner."""
        obj = self._live()
        return (obj.x, obj.y)

    @property
    def size(self) -> tuple[int, int]:
        """``(width, height)`` of the object's image, in pixels."""
        return self._live().image.size

    @property
    def visible(self) -> bool:
        """Whether the engine draws this object."""
        return self._live().visible

    @visible.setter
    def visible(self, value: bool) -> None:
        self._live().visible = bool(value)

    def __eq__(self, other: object) -> bool:
        """Two handles are equal when they refer to the same object."""
        if isinstance(other, GameObject):
            return self._object is other._object
        return NotImplemented

    def __hash__(self) -> int:
        return hash(id(self._object))

    def __repr__(self) -> str:
        return f"GameObject({self.name!r})"
