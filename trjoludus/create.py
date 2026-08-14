"""How a game brings things into the world.

::

    tl.create.image(100, 100, "player.png", "player")

**What is created stays.** This is not a per-frame paint call: the engine keeps
the object and draws it every frame until it is removed. Calling it once, when
the game starts, is the normal thing to do -- calling it every frame would try
to create a second object with the same name and fail.

The name says so. ``create`` is for things that become part of the scene;
``draw`` is reserved for immediate, per-frame drawing such as UI, which does
not exist yet.
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
            f"a game object name must be a string, got {type(name).__name__}"
        )
    if not name:
        raise ValueError("a game object needs a name; got an empty string")
    # Positions may be fractional; the scene keeps them exactly and the
    # renderer rounds when it draws. One check, in one place.
    for label, value in (("x", x), ("y", y)):
        _check_pixels(label, value)

    loaded = load_image(path)
    current_scene().add(SceneObject(name, loaded, x, y))
    return GameObject(name)
