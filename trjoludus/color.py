"""Colours, as plain red-green-blue values.

::

    draw.rect(10, 10, 100, 40, color.blue)
    draw.text(20, 20, "Score", color.white)

A colour is a ``(red, green, blue)`` tuple with each part from 0 to 255, so a
game is never obliged to use the named ones::

    draw.rect(0, 0, 50, 50, (128, 40, 200))

The names below are ordinary tuples, not a special type, which is why both
spellings work everywhere a colour is accepted.
"""

__all__ = [
    "black",
    "blue",
    "cyan",
    "gray",
    "green",
    "grey",
    "magenta",
    "red",
    "white",
    "yellow",
]

#: Nothing lit.
black = (0, 0, 0)

#: Not quite full brightness -- easier on the eye than pure 255 white.
white = (250, 250, 250)

red = (250, 0, 0)
green = (0, 250, 0)
blue = (0, 0, 250)
yellow = (250, 250, 0)
cyan = (0, 250, 250)
magenta = (250, 0, 250)
gray = (128, 128, 128)

#: Same colour, other spelling.
grey = gray


def check(value, what: str = "a colour"):
    """Return ``value`` as a validated ``(red, green, blue)`` tuple.

    Raises:
        TypeError: If it is not three numbers.
        ValueError: If any part falls outside 0-255.
    """
    try:
        red_, green_, blue_ = value
    except (TypeError, ValueError):
        raise TypeError(
            f"{what} must be a (red, green, blue) tuple such as color.blue or "
            f"(0, 0, 250); got {value!r}"
        ) from None

    parts = (red_, green_, blue_)
    for part in parts:
        if not isinstance(part, int) or isinstance(part, bool):
            raise TypeError(
                f"{what} must be made of whole numbers, got {value!r}"
            )
        if not 0 <= part <= 255:
            raise ValueError(
                f"{what} has a part outside 0-255: {value!r}"
            )
    return parts
