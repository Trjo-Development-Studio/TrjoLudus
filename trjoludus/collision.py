"""Working out what is touching what.

**TrjoLudus detects what happened. The game decides what it means.** Asking
whether two objects overlap is all this does. It moves nothing, stops nothing,
plays nothing and destroys nothing -- what a collision *means* is the game's
to say, and an engine that guessed would be wrong for most games::

    if objects.collide("player", "zombie"):
        zombie.animation.play("attack")

Two questions, and the second is the first asked of everything at once::

    objects.collide("player", "zombie")   # are these two touching?
    objects.colliding("player")           # what is this one touching?

A game reaches both through :mod:`trjoludus.objects`.

# What an answer is made of

:func:`colliding` hands back :class:`~trjoludus.scene.GameObject` handles --
the same thing ``create.image(...)`` returns and the same thing a game already
holds. There is no new way to refer to an object here, because there does not
need to be one: what comes back can be used straight away, which is the point
of asking::

    for enemy in objects.colliding("player"):
        enemy.animation.play("attack")

A name is one attribute away when a name is what you want
(``enemy.name``), which is the cheaper direction to travel: getting from a
name to something you can use would mean looking it up again.

They come back in the order the objects were created -- the scene's own order,
which is also the order they are drawn in. The same scene answers the same way
every time, so a loop over the result is never at the mercy of how a set
happened to hash.

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

__all__ = ["CollisionError", "collide", "colliding"]

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


def _participates(obj) -> bool:
    """Whether an object takes part in collision at all.

    Aliveness, and nothing else. Being invisible is not being destroyed -- an
    object nobody can see is still somewhere, which is what invisible walls
    are made of -- so what is drawn has no say here.

    Shared by both questions on purpose: one rule about who takes part, asked
    the same way whether a game names two objects or one.
    """
    from trjoludus import engine as engine_state

    if obj.removed:
        return False
    return bool(obj._table.flags[obj._slot] & engine_state.ALIVE)


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
    # on it.
    if not _participates(first) or not _participates(second):
        return False

    return overlap(first, second)


def _overlapping(subject):
    """Every live object overlapping ``subject``, except ``subject`` itself.

    Engine-internal, and the only part of answering :func:`colliding` that
    knows *how* the objects are found. It walks the scene, which is honest
    about what it costs and is fast enough for the number of objects a game
    made this way has. Something cleverer -- a grid, a tree, a native pass --
    would replace this function and nothing else, which is why it is a
    function.

    Yields in the scene's own order, which is creation order.
    """
    from trjoludus.scene import current_scene

    for other in current_scene().objects():
        # Identity, not name: the object asked about is excluded because it is
        # that object, not because it is spelled that way.
        if other is subject:
            continue
        if not _participates(other):
            continue
        if overlap(subject, other):
            yield other


def colliding(name: str) -> tuple:
    """Every object overlapping the named one, right now.

    ::

        for enemy in objects.colliding("player"):
            enemy.animation.play("attack")

    Like :func:`collide`, this answers and does nothing else. Nothing is
    moved, damaged, destroyed or played; what to do about what is touching
    the player is yours to write.

    What comes back are :class:`~trjoludus.scene.GameObject` handles -- the
    same thing ``create.image(...)`` gives you -- so they can be used straight
    away. Ask one for its ``name`` when a name is what you want::

        names = [enemy.name for enemy in objects.colliding("player")]
        if "zombie" in names:
            ...

    They arrive in the order the objects were created, which is the order they
    are drawn in, and it is the same order every time for the same scene.

    The object asked about is never in its own result: it overlaps itself
    always, which would make it noise in every loop. That is the same rule
    :func:`collide` states by refusing, said in the way a list can say it.

    Nothing is remembered between calls. Move something and ask again and the
    answer has moved with it, because the answer is worked out from where
    things are now.

    Args:
        name: The name of the object to ask about.

    Returns:
        A tuple of handles, empty if nothing is touching it -- and empty, with
        a warning naming it, if there is no such object.

    Raises:
        TypeError: If ``name`` is not a string.
    """
    from trjoludus.scene import GameObject

    if not isinstance(name, str):
        raise TypeError(
            f"a game object name must be a string, got {type(name).__name__}"
        )

    subject = _find(name)
    if subject is None or not _participates(subject):
        return ()

    # One handle per object, because the scene holds one object per name and
    # each is walked once. Built here rather than kept anywhere: a handle is a
    # way of reaching an object, not a record of what was touching what.
    return tuple(GameObject(found.name) for found in _overlapping(subject))


expose(__name__, recommends=PYTHON,
       python_implementation="trjoludus.collision")
