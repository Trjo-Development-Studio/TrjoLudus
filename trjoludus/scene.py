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

from math import isfinite

from trjoludus import engine
from trjoludus.animation import DEFAULT_FPS, Animator
from trjoludus.image import load_image
from trjoludus.errors import TrjoLudusError

__all__ = [
    "AnimationControl",
    "GameObject",
    "Movement",
    "Placement",
    "Sizing",
    "Scene",
    "SceneError",
    "SceneObject",
    "current_scene",
]


class SceneError(TrjoLudusError):
    """Raised when a named object is missing, duplicated, or invalid."""


def _whole_if_it_can(value: float):
    """A whole number as an ``int``, anything else unchanged.

    Positions are stored as doubles so that native code can read a contiguous
    run of them. Handing every one back as a float would change what a game
    sees when it prints a position, which is a visible difference for a
    storage decision nobody asked about.
    """
    return int(value) if value.is_integer() else value


class SceneObject:
    """One drawable thing the engine owns.

    Games do not build these directly; :func:`trjoludus.create.image` creates
    them and :class:`GameObject` reaches them.
    """

    __slots__ = ("name", "_image", "removed", "animator", "_table", "_slot",
                 "_groups", "_layer", "_mask")

    def __init__(self, name: str, image, x: int, y: int, table=None) -> None:
        self.name = name
        # The numbers live in the engine's object table, not here. That is
        # what makes "the position" one thing rather than one per system --
        # anything native reads the very doubles these properties write.
        self._table = engine.current().objects if table is None else table
        self._slot = self._table.claim(x, y, image.width, image.height)
        self._image = image
        #: Set when the object leaves the scene. Handles check it so that
        #: using one afterwards is an error rather than a silent no-op.
        self.removed = False
        #: The animations this object knows and the one it is playing. Lives
        #: here rather than on a handle, so every handle sees the same thing.
        self.animator = Animator(self)
        #: Which collision groups this object is in, in the order it joined
        #: them. A dict used as an ordered set: membership is a lookup, and
        #: the order is the one a game put them in rather than one a hash
        #: chose.
        #:
        #: **It lives here, on the object.** Not in a registry keyed by name
        #: or by table slot, because either would outlive the object it
        #: described -- a destroyed object's membership would have to be
        #: cleaned up by hand, and a slot handed to the next object would
        #: arrive already in somebody else's group. Here there is nothing to
        #: clean up: the membership goes when the object does.
        self._groups: dict = {}
        #: Which collision layer this object is on, as a single bit, and which
        #: layers it will collide with, as a bitmask. Two integers rather than
        #: two lists: "is this layer in that mask" is then one ``&``, and a
        #: game with a hundred objects asks that question thousands of times a
        #: frame.
        #:
        #: The defaults let everything collide with everything, which is what
        #: collision did before layers existed. Filtering is something a game
        #: opts into by narrowing a mask; putting an object on a different
        #: layer on its own changes nothing.
        #:
        #: Here, on the object, for the same reason the groups are: it goes
        #: when the object does, so nothing can leak into a reused slot or a
        #: recreated name.
        self._layer = FIRST_LAYER
        self._mask = EVERY_LAYER

    # --- the numbers, which live in the table ----------------------------

    @property
    def x(self):
        """Distance in pixels from the left edge. May be fractional.

        The table stores doubles, because that is what a native pass wants to
        read. A position that happens to be whole still reads as a whole
        number, so a game showing ``f"x {player.x}"`` sees ``100`` rather than
        ``100.0`` -- the storage changed underneath, and what a game sees did
        not.
        """
        return _whole_if_it_can(self._table.x[self._slot])

    @x.setter
    def x(self, value) -> None:
        self._table.x[self._slot] = float(value)

    @property
    def y(self):
        """Distance in pixels from the top edge. May be fractional."""
        return _whole_if_it_can(self._table.y[self._slot])

    @y.setter
    def y(self, value) -> None:
        self._table.y[self._slot] = float(value)

    @property
    def scale(self) -> float:
        """How much bigger than its image the object is drawn."""
        return self._table.scale[self._slot]

    @scale.setter
    def scale(self, value) -> None:
        self._table.scale[self._slot] = float(value)

    @property
    def visible(self) -> bool:
        """Whether the engine draws this object."""
        return bool(self._table.flags[self._slot] & engine.VISIBLE)

    @visible.setter
    def visible(self, value) -> None:
        flags = self._table.flags[self._slot]
        if value:
            self._table.flags[self._slot] = flags | engine.VISIBLE
        else:
            self._table.flags[self._slot] = flags & ~engine.VISIBLE

    @property
    def image(self):
        """The picture this object is drawn with."""
        return self._image

    @image.setter
    def image(self, value) -> None:
        # The size goes into the table too: what an object covers is
        # something a native pass has to be able to work out on its own.
        self._image = value
        self._table.width[self._slot] = value.width
        self._table.height[self._slot] = value.height

    def _release(self) -> None:
        """Give the table slot back. Called when the object leaves a scene."""
        self._table.release(self._slot)

    def __repr__(self) -> str:
        return (
            f"SceneObject({self.name!r}, at=({self.x}, {self.y}), "
            f"size={self._image.size}, scale={self.scale})"
        )


#: How many collision layers there are. Thirty-two is far more categories
#: than a game made this way will use, and it keeps a layer a small number
#: rather than something to look up.
LAYERS = 32

#: The layer every object starts on.
FIRST_LAYER = 1 << 0

#: A mask with every layer in it: what an object collides with until a game
#: says otherwise. This is what makes layers opt-in -- with these defaults the
#: rule below is always satisfied, so collision behaves exactly as it did
#: before layers existed.
EVERY_LAYER = (1 << LAYERS) - 1


def _check_layer(value, what: str = "a collision layer") -> int:
    """One layer number, 1 to :data:`LAYERS`, as the bit that stands for it.

    Layers are numbered from one because that is how anyone counts them --
    "layer 1" and "layer 2", not "bit 0" and "bit 1". The bit is an
    implementation detail and stays one.
    """
    # bool first: True is an int, and a layer of True would quietly be layer 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{what} must be a whole number from 1 to {LAYERS}, got "
            f"{type(value).__name__}"
        )
    if not 1 <= value <= LAYERS:
        raise ValueError(
            f"{what} must be from 1 to {LAYERS}, got {value}. "
            + ("Layers are numbered from 1." if value < 1 else
               f"TrjoLudus has {LAYERS} layers, which is more than a game "
               f"normally needs.")
        )
    return 1 << (value - 1)


def _check_mask(value) -> int:
    """A collection of layer numbers, as one bitmask.

    A single number is allowed, because collides-with-one-layer is the common
    case and ``mask = 2`` should not have to be written ``mask = (2,)``.
    """
    if isinstance(value, bool) or isinstance(value, int):
        return _check_layer(value, "a collision mask")
    # A string is a collection, so "12" would quietly become layers "1" and
    # "2" and then fail with a message about characters. Refused here, where
    # the message can say what was actually wrong.
    if isinstance(value, (str, bytes)):
        raise TypeError(
            f"a collision mask must be a layer number or a collection of "
            f"them, got {type(value).__name__} {value!r}"
        )
    try:
        layers = tuple(value)
    except TypeError:
        raise TypeError(
            f"a collision mask must be a layer number or a collection of "
            f"them, got {type(value).__name__}"
        ) from None

    mask = 0
    for layer in layers:
        mask |= _check_layer(layer, "a collision mask")
    return mask


def _layers_of(mask: int) -> tuple:
    """The layer numbers in a mask, smallest first."""
    return tuple(number for number in range(1, LAYERS + 1)
                 if mask & (1 << (number - 1)))


def name_of(who, what: str = "a game object") -> str:
    """The name of an object, given either its name or a handle on it.

    Engine-internal, and the one place this is decided. Anything public that
    takes an object by name takes a :class:`GameObject` too, because the
    library hands those out -- ``create.image(...)`` returns one and
    ``objects.colliding(...)`` returns several -- and a result that cannot be
    passed back into the thing that produced it is a result with a chore
    attached.

    A handle is asked for its name rather than followed to its object, so
    everything downstream works on names exactly as it always has.

    Raises:
        TypeError: If it is neither a string nor a handle.
    """
    if isinstance(who, str):
        return who
    if isinstance(who, GameObject):
        return who.name
    raise TypeError(
        f"{what} must be a name or a game object, got {type(who).__name__}"
    )


def _check_group(name: str) -> str:
    """A usable group name, or a clear complaint.

    Deliberately barely a rule: a group name is a label a game chose, and
    inventing a naming scheme for it would be a rule to remember for no
    benefit. What is refused is a name that cannot identify anything --
    nothing, or nothing but spaces.
    """
    if not isinstance(name, str):
        raise TypeError(
            f"a collision group name must be a string, got "
            f"{type(name).__name__}"
        )
    if not name.strip():
        raise ValueError(
            "a collision group needs a name; got "
            + ("an empty string" if not name else f"{name!r}, which is blank")
        )
    return name


def _remember_group(name: str) -> None:
    """Note that a group name has been used at some point in this run.

    So that a group nobody has ever mentioned can be told from one that is
    simply empty at the moment. A game whose zombies are all dead has a real
    ``"enemy"`` group with nothing in it, and must not be nagged about it;
    a game that asked about ``"enmeys"`` has made a typo, and should hear so.

    Never pruned. A name that was real once stays real for the run, which is
    what makes the distinction hold as objects come and go.
    """
    from trjoludus import engine

    engine.current().groups[name] = None


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
        removed._release()

    def advance_animations(self, seconds: float) -> None:
        """Move every playing animation on by one frame's worth of time.

        Driven by the loop rather than by each object, so animation is paced
        by the same clock as everything else and a game does not have to
        remember to tick anything.
        """
        for obj in self._objects.values():
            obj.animator.advance(seconds)

    def clear(self) -> None:
        """Forget every object."""
        for obj in self._objects.values():
            obj.removed = True
            obj._release()
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


def current_scene() -> Scene:
    """The scene new objects go into and the engine draws.

    The scene belongs to the engine state, which a run replaces -- so a second
    :func:`trjoludus.run` does not inherit the first game's objects, and
    anything created before a run still takes part in it.
    """
    return engine.current().world


def _check_pixels(label: str, value):
    """Reject anything that is not a number of pixels.

    Fractions are allowed and kept. A speed of 100 pixels a second is 1.67
    pixels in a frame at 60 per second, and an object that could only hold
    whole pixels would either lose that fraction every frame or round it up
    every frame -- crawling in one case, drifting in the other. The position
    keeps what it is given and the renderer rounds when it draws.

    ``bool`` is excluded because ``True`` as a distance is a mistake, not an
    intention. Infinities and NaN are excluded because they cannot be rounded
    to a pixel, and failing here says so far more clearly than failing later
    inside the renderer.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{label} must be a number of pixels, got "
            f"{type(value).__name__}"
        )
    if not isfinite(value):
        raise ValueError(
            f"{label} must be a real distance, got {value}. There is no "
            f"pixel that far away."
        )
    return value


def _check_scale(value, label: str = "a scale") -> float:
    """Reject anything that is not a usable scale.

    The same rule drawings use: a positive number, and ``bool`` excluded
    because ``True`` as a size is a mistake rather than an intention. Zero and
    negatives are refused instead of quietly drawing nothing, which would look
    like the engine losing the object.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{label} must be a number, got {type(value).__name__}"
        )
    if value <= 0:
        raise ValueError(
            f"{label} must be greater than zero, got {value}. A scale of 1 is "
            f"the image's own size."
        )
    return float(value)


class Placement:
    """Puts one object at an exact place.

    Reached as :attr:`GameObject.set`. Each value can be called or assigned,
    and the two are the same operation written two ways::

        player.set.x(200)    # exactly 200 pixels from the left
        player.set.x = 200   # the same thing

        player.set.scale(1.25)
        player.set.scale = 1.25

    The same spelling drawings use, so one way of saying "put this here"
    works on everything that has a position. Assigning :attr:`GameObject.x`
    does the same thing and stays supported; ``set`` is the spelling that
    reads the same next to ``move``.
    """

    __slots__ = ("_owner",)

    #: What ``set.name = value`` accepts. Assignment routes to the method of
    #: the same name, so the two forms cannot drift apart -- there is one
    #: implementation of each, not two.
    _ASSIGNABLE = ("x", "y", "scale", "image")

    def __init__(self, owner: "GameObject") -> None:
        self._owner = owner

    def __setattr__(self, name: str, value) -> None:
        if name in self._ASSIGNABLE:
            getattr(self, name)(value)
            return
        object.__setattr__(self, name, value)

    def x(self, pixels: int) -> None:
        """Put the object's left edge exactly ``pixels`` from the left.

        Fractions are kept exactly. Only the renderer rounds, so movement
        measured in seconds does not lose a fraction of a pixel per frame.

        Raises:
            TypeError: If ``pixels`` is not a number.
            SceneError: If the object has been removed.
        """
        self._owner._live().x = _check_pixels("x", pixels)

    def y(self, pixels: int) -> None:
        """Put the object's top edge exactly ``pixels`` from the top.

        Fractions are kept exactly, as with :meth:`x`.

        Raises:
            TypeError: If ``pixels`` is not a number.
            SceneError: If the object has been removed.
        """
        self._owner._live().y = _check_pixels("y", pixels)

    def scale(self, amount) -> None:
        """Draw the object at ``amount`` times its image's size.

        1 is the image's own size. It grows from the top-left corner, which is
        where the object's position already is, so scaling never moves what a
        game placed.

        Raises:
            TypeError: If ``amount`` is not a number.
            ValueError: If it is not greater than zero.
            SceneError: If the object has been removed.
        """
        self._owner._live().scale = _check_scale(amount)

    def image(self, path) -> None:
        """Draw this object with a different picture from now on.

        If an animation is playing it stops, because the two cannot both
        decide what is drawn -- the picture asked for here wins, and a warning
        says so. Position and scale are untouched.

        Args:
            path: Path to a PNG file.

        Raises:
            ImageError: If the file is missing or is not a PNG this decoder
                supports.
            SceneError: If the object has been removed.
        """
        obj = self._owner._live()
        loaded = load_image(path)
        obj.animator.replaced_by_hand()
        obj.image = loaded

    def __repr__(self) -> str:
        return f"Placement({self._owner.name!r})"


class Sizing:
    """Grows or shrinks one object relative to how big it is now.

    Reached as :attr:`GameObject.add` and :attr:`GameObject.remove`::

        player.add.scale(0.25)
        player.remove.scale(0.25)

    Only scale is here. Relative position is ``move``, and relative anything
    else would be a spelling without a meaning.
    """

    __slots__ = ("_owner", "_how", "_sign")

    def __init__(self, owner: "GameObject", how: str) -> None:
        self._owner = owner
        self._how = how
        self._sign = 1 if how == "add" else -1

    def scale(self, amount) -> None:
        """Grow or shrink by ``amount``, relative to the current scale.

        Raises:
            TypeError: If ``amount`` is not a number.
            ValueError: If ``amount``, or the scale it would produce, is not
                greater than zero.
            SceneError: If the object has been removed.
        """
        obj = self._owner._live()
        change = _check_scale(amount, f"an amount to {self._how}")
        obj.scale = _check_scale(obj.scale + self._sign * change,
                                 "the resulting scale")

    def __repr__(self) -> str:
        return f"Sizing({self._owner.name!r}, {self._how!r})"


class AnimationControl:
    """A game's way of reaching one object's animations.

    Reached as :attr:`GameObject.animation`::

        player.animation.add("walk", ["walk_1.png", "walk_2.png"])
        player.animation.play("walk", fps=12)

    Every call goes through the handle first, so using an animation on an
    object that has been destroyed says so rather than quietly working on
    something nobody draws. The animations themselves live on the scene's
    record, which is why any handle naming the object reaches the same ones.
    """

    __slots__ = ("_owner",)

    def __init__(self, owner: "GameObject") -> None:
        self._owner = owner

    def _animator(self):
        return self._owner._live().animator

    def add(self, name: str, frames) -> None:
        """Teach this object an animation. See :meth:`Animator.add`."""
        self._animator().add(name, frames)

    def play(self, name: str, fps=DEFAULT_FPS, loop: bool = True) -> None:
        """Start an animation. See :meth:`Animator.play`."""
        self._animator().play(name, fps, loop)

    def pause(self, name: str) -> None:
        """Freeze an animation where it is."""
        self._animator().pause(name)

    def resume(self, name: str) -> None:
        """Carry on from where :meth:`pause` stopped."""
        self._animator().resume(name)

    def stop(self, name: str = None) -> None:
        """Stop an animation, keeping the frame it reached.

        ::

            zombie.animation.stop()          # whatever is playing
            zombie.animation.stop("walk")    # that one, if it is playing

        Only one animation plays at a time, so naming it is optional -- the
        object already knows which one it is on. Naming it is still useful
        when a game wants to stop something *only* if it is the thing running,
        and hear about it when it is not.

        Stopping when nothing is playing does nothing and says nothing: it is
        the state the game asked for.
        """
        animator = self._animator()
        if name is None:
            if animator.current is None or not animator.is_playing:
                return
            name = animator.current
        animator.stop(name)

    def frames(self, name: str) -> int:
        """How many frames an animation has."""
        return self._animator().frames(name)

    @property
    def current(self):
        """The animation being played, paused on, or stopped on."""
        return self._animator().current

    @property
    def is_playing(self) -> bool:
        """Whether an animation is advancing right now."""
        return self._animator().is_playing

    @property
    def finished(self) -> bool:
        """Whether a non-looping animation has played all the way through."""
        return self._animator().finished

    @property
    def frame(self) -> int:
        """Which frame is showing, counting from 1. ``0`` before anything."""
        return self._animator().frame

    @property
    def names(self) -> tuple:
        """Every animation this object knows."""
        return self._animator().names

    def __repr__(self) -> str:
        return f"AnimationControl({self._owner.name!r})"


class Movement:
    """Moves one object relative to where it currently is.

    Reached as :attr:`GameObject.move`::

        player.move.x(50)    # 50 pixels right
        player.move.x(-50)   # 50 pixels left
        player.move.y(50)    # 50 pixels down
        player.move.y(-50)   # 50 pixels up

    Every call is relative, so they add up: two ``move.x(50)`` calls move the
    object 100 pixels in total. To put an object at an exact place, use
    ``set.x()`` and ``set.y()``, or assign to :attr:`GameObject.x`.

    Nothing is clamped. An object may be moved partly or wholly outside the
    window; there is no world boundary, and inventing one here would surprise
    a game that meant to move something off screen.
    """

    __slots__ = ("_owner",)

    def __init__(self, owner: "GameObject") -> None:
        self._owner = owner

    def x(self, pixels) -> None:
        """Move right by ``pixels``, or left if negative.

        Fractions add up exactly::

            player.move.x(100 * time.delta)   # 100 pixels every second

        Nothing is lost between frames and nothing is rounded up, because the
        position keeps the fraction and only drawing rounds.

        Raises:
            TypeError: If ``pixels`` is not a number.
            SceneError: If the object has been removed.
        """
        obj = self._owner._live()
        obj.x += _check_pixels("a movement distance", pixels)

    def y(self, pixels) -> None:
        """Move down by ``pixels``, or up if negative.

        Fractions add up exactly, as with :meth:`x`.

        Raises:
            TypeError: If ``pixels`` is not a number.
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
    def set(self) -> Placement:
        """Put this object at an exact position::

            player.set.x(200)
        """
        return Placement(self)

    @property
    def animation(self) -> AnimationControl:
        """The animations this object knows::

            player.animation.play("walk", fps=12)
        """
        return AnimationControl(self)

    @property
    def add(self) -> Sizing:
        """Grow this object: ``player.add.scale(0.25)``."""
        return Sizing(self, "add")

    @property
    def remove(self) -> Sizing:
        """Shrink this object: ``player.remove.scale(0.25)``."""
        return Sizing(self, "remove")

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
    def layer(self) -> int:
        """Which collision layer this object is on. ``1`` by default.

        A layer is a number from 1 to 32, and it says what an object *is* --
        a player, an enemy, a wall. What it will collide *with* is
        :attr:`mask`::

            player.layer = 1
            zombie.layer = 2

        Setting a layer on its own changes nothing about what collides,
        because every object starts willing to collide with every layer.
        Filtering starts when a mask is narrowed.
        """
        return _layers_of(self._live()._layer)[0]

    @layer.setter
    def layer(self, value: int) -> None:
        self._live()._layer = _check_layer(value)

    @property
    def mask(self) -> tuple[int, ...]:
        """Which layers this object will collide with. Every layer by default.

        Give it one layer or several::

            player.mask = 2            # only ever touches layer 2
            bullet.mask = (2, 3)       # touches layers 2 and 3

        Reads back as a tuple of layer numbers, smallest first, so asking is
        plain Python::

            if 2 in player.mask:
                ...

        **Both objects have to agree.** Two objects collide only when each
        one's mask contains the other's layer -- see
        :func:`trjoludus.objects.collide`. A mask is permission, and
        permission that only one side gave is not agreement.

        An empty mask means this object collides with nothing, which is a
        useful thing to be able to say and not an error.
        """
        return _layers_of(self._live()._mask)

    @mask.setter
    def mask(self, value) -> None:
        self._live()._mask = _check_mask(value)

    def group(self, name: str) -> "GameObject":
        """Put this object in a collision group.

        A group is a label, nothing more::

            zombie.group("enemy")
            zombie.group("undead")

        An object can be in as many as it likes, and joining one never takes
        it out of another. Joining a group it is already in changes nothing
        and is not a mistake -- a game that labels its objects in ``on_update``
        should not have to check first.

        Groups are what :func:`trjoludus.objects.colliding` filters on::

            for enemy in objects.colliding("player", group="enemy"):
                ...

        Returns:
            This handle, so joining several reads as one line::

                zombie.group("enemy").group("undead")

        Raises:
            TypeError: If ``name`` is not a string.
            ValueError: If ``name`` is empty or only spaces.
        """
        obj = self._live()
        obj._groups[_check_group(name)] = None
        _remember_group(name)
        return self

    def ungroup(self, name: str) -> "GameObject":
        """Take this object out of a collision group.

        The others it is in are untouched. Leaving a group it was never in
        changes nothing and is not a mistake, for the same reason joining
        twice is not.

        Returns:
            This handle.

        Raises:
            TypeError: If ``name`` is not a string.
            ValueError: If ``name`` is empty or only spaces.
        """
        obj = self._live()
        obj._groups.pop(_check_group(name), None)
        return self

    @property
    def groups(self) -> tuple[str, ...]:
        """Every group this object is in, in the order it joined them.

        Which is also how to ask whether it is in one::

            if "enemy" in zombie.groups:
                ...
        """
        return tuple(self._live()._groups)

    @property
    def alive(self) -> bool:
        """Whether this object is still in the game.

        ``False`` once :meth:`destroy` has been called, on every handle to it
        and not only the one that did it::

            if player.alive:
                player.move.x(5)

        Asking is always safe -- it is the one thing a handle answers after
        its object is gone, which is what makes it worth asking.

        A destroyed object stays destroyed. Creating something else with the
        same name, or one that happens to be given the same storage, does not
        bring it back: this asks about *this* object, not about the name.
        """
        return not self._object.removed

    def __bool__(self) -> bool:
        """Whether this object is still in the game. Same as :attr:`alive`.

        So that the plain Python spelling tells the truth::

            if player:
                player.move.x(5)

        A handle that answered ``True`` after its object was destroyed would
        promise something the very next line would refuse.
        """
        return self.alive

    @property
    def name(self) -> str:
        """The name this object was created with."""
        return self._object.name

    @property
    def x(self):
        """Distance in pixels from the left edge of the window.

        Assigning sets an absolute position; :attr:`move` changes it by a
        relative amount. Either may be fractional, and the exact value is
        what comes back -- this *is* the precise position, not a rounded view
        of one. The renderer rounds when it draws, and nowhere else.
        """
        return self._live().x

    @x.setter
    def x(self, value: int) -> None:
        self._live().x = _check_pixels("x", value)

    @property
    def y(self):
        """Distance in pixels from the top edge of the window.

        May be fractional, as :attr:`x` may.
        """
        return self._live().y

    @y.setter
    def y(self, value: int) -> None:
        self._live().y = _check_pixels("y", value)

    @property
    def position(self) -> tuple:
        """``(x, y)`` of the image's top-left corner, exactly as set."""
        obj = self._live()
        return (obj.x, obj.y)

    @property
    def scale(self) -> float:
        """How much bigger than its image this is drawn. 1.0 is normal.

        Set it outright, or change it by a relative amount::

            player.scale = 2.0        # twice the size of its image
            player.add.scale(0.5)     # and then half again as big

        Raises:
            TypeError: If the value is not a number.
            ValueError: If it is zero or negative.
        """
        return self._live().scale

    @scale.setter
    def scale(self, value) -> None:
        self._live().scale = _check_scale(value)

    @property
    def size(self) -> tuple[int, int]:
        """``(width, height)`` the object is drawn at, in pixels.

        This is the image's size once :attr:`scale` has been applied, because
        it answers "how big is this on screen" -- which is the question a game
        asks. At the default scale of 1 it is the image's own size.
        """
        obj = self._live()
        width, height = obj.image.size
        if obj.scale == 1.0:
            return (width, height)
        return (round(width * obj.scale), round(height * obj.scale))

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
