"""How a game brings things into the world.

::

    player = create.image(100, 100, "player.png", "player")

**What is created stays.** This is not a per-frame paint call: the engine
keeps the object and draws it every frame until it is destroyed. Calling it
once, when the game starts, is the normal thing to do -- calling it every
frame would try to create a second object with the same name and fail.

# create and draw

Both keep what they are given, and neither is a per-frame paint call. What
separates them is *what the thing is*, not how long it lasts:

======================  ==================================================
:mod:`trjoludus.create`  things in the world -- they collide, they animate,
                         they have an image, they are what a game is about
:mod:`trjoludus.draw`    the interface on top -- scores, menus, buttons;
                         shapes and text that can be clicked and hidden
======================  ==================================================

So a player, an enemy and a wall are created; a health bar, a title and a
menu are drawn. Both are remembered and redrawn every frame until something
removes them, and the interface is drawn over the world.

A game object comes back as a :class:`~trjoludus.GameObject`, which is the
handle everything else takes::

    player = create.image(100, 100, "player.png", "player")
    player.x = 250
    objects.colliding(player)
"""

from trjoludus.image import load_image
from trjoludus.scene import SceneObject, current_scene

__all__ = ["image"]


def image(x, y, path, name: str):
    """Create a named image object at ``(x, y)``.

    Args:
        x: Pixels from the left edge of the window to the image's left edge.
            May be fractional; the renderer rounds when it draws.
        y: Pixels from the top edge of the window to the image's top edge.
        path: Path to a PNG file.
        name: What to call this object. Must be unique.

    Returns:
        A :class:`~trjoludus.scene.GameObject` handle on the new object, so it
        can be used immediately without looking it up again.

    Raises:
        ImageError: If the image cannot be loaded.
        SceneError: If ``name`` is already taken.
        TypeError: If ``x``, ``y`` or ``name`` has the wrong type.
    """
    from trjoludus.scene import GameObject, _check_pixels

    if not isinstance(name, str):
        raise TypeError(
            f"a game object name must be a string, got "
            f"{type(name).__name__}. The order is "
            f"create.image(x, y, path, name), so the name comes last."
        )
    if not name:
        raise ValueError("a game object needs a name; got an empty string")
    # Positions may be fractional; the scene keeps them exactly and the
    # renderer rounds when it draws. One check, in one place.
    #
    # A string where a position belongs is almost always the path, given
    # first, so the message says what the order is rather than only what the
    # type should have been.
    for label, value in (("x", x), ("y", y)):
        if isinstance(value, str):
            raise TypeError(
                f"{label} must be a number of pixels, got the string "
                f"{value!r}. The order is create.image(x, y, path, name) -- "
                f"the position comes first, then the picture, then what to "
                f"call it."
            )
        _check_pixels(label, value)

    loaded = load_image(path)
    current_scene().add(SceneObject(name, loaded, x, y))
    return GameObject(name)
