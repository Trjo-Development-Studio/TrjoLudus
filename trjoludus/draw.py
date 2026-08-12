"""How a game puts things on screen.

::

    tl.draw.image(100, 100, "player.png", "player")

**This creates something that stays.** It is not a per-frame paint call: the
engine keeps the object and draws it every frame until it is removed. Calling
it once, when the game starts, is the normal thing to do -- calling it every
frame would try to create a second object with the same name and fail.

That is worth stating plainly because ``draw`` reads like an instruction to
paint right now, which is how most 2D libraries use the word.
"""

from trjoludus.image import load_image
from trjoludus.scene import SceneObject, current_scene

__all__ = ["image", "remove"]


def image(x: int, y: int, path, name: str):
    """Create a named image object at ``(x, y)``.

    Args:
        x: Pixels from the left edge of the window to the image's left edge.
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
    from trjoludus.scene import GameObject

    if not isinstance(name, str):
        raise TypeError(
            f"a game object name must be a string, got {type(name).__name__}"
        )
    if not name:
        raise ValueError("a game object needs a name; got an empty string")
    for label, value in (("x", x), ("y", y)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(
                f"{label} must be a whole number of pixels, got "
                f"{type(value).__name__}"
            )

    loaded = load_image(path)
    current_scene().add(SceneObject(name, loaded, x, y))
    return GameObject(name)


def remove(name: str) -> None:
    """Remove a named object so it is no longer drawn.

    Raises:
        SceneError: If no object has that name.
    """
    current_scene().remove(name)
