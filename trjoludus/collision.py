"""Working out what is touching what.

**TrjoLudus detects what happened. The game decides what it means.** Asking
whether two objects overlap is all this does. It moves nothing, stops nothing,
plays nothing and destroys nothing -- what a collision *means* is the game's
to say, and an engine that guessed would be wrong for most games::

    if objects.collide("player", "zombie"):
        zombie.animation.play("attack")

A game reaches this through :mod:`trjoludus.objects`; the name a game writes
is ``objects.collide(...)``.

# Boxes, not shapes

An object's collision bounds are an upright rectangle: where it is, and how
big it is drawn. Nothing is rotated, nothing is round and nothing looks at the
picture's pixels. That is enough for the games this is for, and it is the
cheapest thing that is ever right.

The bounds come from the numbers the object already has -- position, image
size and scale -- read out of :class:`~trjoludus.engine.ObjectTable`, which is
where they already live. There is no collision box to keep in step with the
object, because there is no second copy of anything: moving an object moves
what it collides with, and scaling it scales what it collides with.

# Exact, not rounded

Positions are fractional and stay fractional here. Rounding is a rendering
concern -- it happens where pixels are chosen and nowhere else -- so an object
at ``x = 10.5`` collides from 10.5, not from 10 or 11. Rounding here would
make a slowly moving object's bounds jump a whole pixel at a time while its
position did not.

# Touching is not overlapping

Two rectangles that share an edge do not collide. A 10-wide object at ``x = 0``
ends where one at ``x = 10`` begins, and laying tiles or walls side by side
must not report every seam as a collision. They have to actually overlap.

**Backend.** ``collision.engine`` chooses which implementation runs::

    collision.engine = "auto"     # the default; a game need never set it
    collision.engine = "python"

There is no native implementation, and ``"rust"`` says so rather than
pretending. Whether there is ever a reason for one is a question for a
measurement, not for a plan.
"""

import warnings

from trjoludus.errors import TrjoLudusError, TrjoLudusWarning
from trjoludus.native import PYTHON, expose

__all__ = ["CollisionError", "collide"]

#: What a game has asked for. Served by the module's own type, so that reading
#: it is live and writing something TrjoLudus does not know is refused.
engine: str


class CollisionError(TrjoLudusError):
    """Raised when a collision question cannot be answered as asked."""


def bounds(obj) -> tuple:
    """The rectangle an object occupies: ``(left, top, right, bottom)``.

    Engine-internal. Read straight from the object table, so it is the same
    position and size everything else uses -- there is nothing here to keep in
    step with the object.

    The size is the image's size with :attr:`scale` applied, exactly as
    :attr:`trjoludus.scene.GameObject.size` reports it, so what a game is told
    an object's size is and what it collides with are the same rectangle.
    """
    table, slot = obj._table, obj._slot
    left = table.x[slot]
    top = table.y[slot]
    scale = table.scale[slot]
    return (left, top,
            left + table.width[slot] * scale,
            top + table.height[slot] * scale)


def overlap(first, second) -> bool:
    """Whether two objects' rectangles overlap.

    Engine-internal, and the whole of the collision test. Sharing an edge is
    not overlapping -- see this module's docstring -- so every comparison is
    strict. An object with no width or height covers nothing and therefore
    touches nothing, which falls out of that rather than being a special case.
    """
    a_left, a_top, a_right, a_bottom = bounds(first)
    b_left, b_top, b_right, b_bottom = bounds(second)
    return (a_left < b_right and b_left < a_right
            and a_top < b_bottom and b_top < a_bottom)


def _find(name: str):
    """The object called ``name``, or ``None`` with a warning.

    A name that is not there is a mistake worth hearing about, and not worth
    stopping a game for: a misspelling, or an object destroyed earlier than
    the code expected. Returning ``False`` from the collision and saying so is
    more use than a traceback in the middle of a frame.
    """
    from trjoludus.scene import current_scene

    scene = current_scene()
    try:
        return scene.require(name)
    except Exception:
        warnings.warn(
            f"collide() was asked about {name!r}, and there is no game object "
            f"by that name -- so the answer is False. "
            f"{scene._missing_message(name)}",
            # Three frames up is the game: warn -> _find -> collide -> the
            # line someone wrote. `objects.collide` is this very function
            # re-exported, so it adds no frame of its own.
            TrjoLudusWarning, stacklevel=3,
        )
        return None


def collide(name_a: str, name_b: str) -> bool:
    """Whether the two named objects are overlapping right now.

    ::

        if objects.collide("player", "zombie"):
            zombie.animation.play("attack")

    This answers a question and does nothing else. It will not move either
    object, take away health, play an animation or destroy anything -- what a
    collision means is yours to write, and it is different in every game.

    An object collides with the rectangle it is drawn in: where it is, and how
    big its picture is once its scale is applied. Move it or scale it and what
    it collides with follows, because they are the same numbers.

    Objects that merely touch are not overlapping. An object 10 wide at
    ``x = 0`` ends exactly where one at ``x = 10`` starts, and walls laid side
    by side must not report every seam as a collision.

    An object that cannot be seen can still be collided with, which is what
    invisible walls and boundaries are made of. An object that has been
    destroyed cannot.

    Args:
        name_a: The name of one object.
        name_b: The name of the other.

    Returns:
        ``True`` if the two overlap, ``False`` if they do not -- and ``False``,
        with a warning naming it, if either object does not exist.

    Raises:
        CollisionError: If both names are the same. An object is always
            touching itself, so the question has no useful answer.
        TypeError: If either name is not a string.
    """
    if not isinstance(name_a, str) or not isinstance(name_b, str):
        wrong = name_a if not isinstance(name_a, str) else name_b
        raise TypeError(
            f"a game object name must be a string, got "
            f"{type(wrong).__name__}"
        )

    # Asked before anything is looked up, because it is wrong whether or not
    # the object exists. Every object is in the scene under one name, so two
    # equal names are one object -- and an object always overlaps itself,
    # which makes the answer meaningless rather than true.
    if name_a == name_b:
        raise CollisionError(
            f"collide({name_a!r}, {name_a!r}) asks whether {name_a!r} is "
            f"touching itself, which it always is. Give the names of two "
            f"different objects."
        )

    first = _find(name_a)
    second = _find(name_b)
    if first is None or second is None:
        return False

    # A destroyed object is out of the scene, so it is normally not found at
    # all. This is what makes that a rule rather than a side effect: nothing
    # that is not alive takes part, whether or not anyone still has a handle
    # on it. Being invisible is not being destroyed -- an object nobody can
    # see is still somewhere, which is what invisible walls are made of.
    from trjoludus import engine as engine_state

    for obj in (first, second):
        if obj.removed or not obj._table.flags[obj._slot] & engine_state.ALIVE:
            return False

    return overlap(first, second)


expose(__name__, recommends=PYTHON,
       python_implementation="trjoludus.collision")
