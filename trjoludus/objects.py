"""Asking questions about the objects in a game.

One question so far::

    from trjoludus import objects

    if objects.collide("player", "zombie"):
        zombie.animation.play("attack")

**TrjoLudus answers; the game decides.** Nothing here moves an object, plays
an animation, changes health or destroys anything. It says what is true right
now, and what that means is the game's to write.
"""

from trjoludus.collision import collide

__all__ = ["collide"]
