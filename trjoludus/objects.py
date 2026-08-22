"""Finding the objects in a game, and asking what they are touching.

::

    from trjoludus import objects

    player = objects.find("player")

    for enemy in objects.colliding(player, group="enemy"):
        enemy.animation.play("attack")

Everything here takes an object either way round -- its name, or the handle
the library gave you -- and everything that hands objects back hands back
handles, so a result can go straight into the next call.

**TrjoLudus answers; the game decides.** Nothing here moves an object, plays
an animation, changes health or destroys anything. It says what is true right
now, and what that means is the game's to write.
"""

from trjoludus.collision import collide, colliding

__all__ = ["all", "collide", "colliding", "exists", "find"]

# `all` is defined below and shadows the builtin inside this module.
_builtin_all = all


def all() -> tuple:  # noqa: A001 -- the public API spells it this way
    """Every object in the game right now, oldest first.

    ::

        for thing in objects.all():
            print(thing.name, thing.position)

    Returns:
        A tuple of :class:`~trjoludus.GameObject` handles, in the order the
        objects were created -- which is the order they are drawn in, and the
        same order :func:`colliding` answers in.

        Destroyed objects are not in it. The tuple is a snapshot: destroying
        something afterwards does not change the tuple you are holding, and
        the handles in it will say so through their ``alive``.
    """
    from trjoludus.scene import GameObject, current_scene

    return tuple(GameObject(found.name) for found in current_scene().objects())


def find(name):
    """The object with this name, or ``None`` if there is not one.

    ::

        player = objects.find("player")

        if player:
            player.move.x(5)

    The gentle way to look something up. ``GameObject("player")`` raises when
    the name is unknown, which is what you want when its absence is a bug;
    this answers ``None``, which is what you want when it is a question.

    Args:
        name: The name to look for. A handle is accepted too, and is looked up
            afresh -- so this is also how to ask whether the object a handle
            points at is still there.

    Returns:
        A :class:`~trjoludus.GameObject`, or ``None``.

    Raises:
        TypeError: If ``name`` is neither a string nor a handle.
    """
    from trjoludus.scene import GameObject, SceneError, name_of

    try:
        return GameObject(name_of(name))
    except SceneError:
        return None


def exists(name) -> bool:
    """Whether there is an object with this name right now.

    ::

        if not objects.exists("boss"):
            spawn_boss()

    Args:
        name: The name to look for, or a handle.

    Raises:
        TypeError: If ``name`` is neither a string nor a handle.
    """
    return find(name) is not None
