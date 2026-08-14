"""Working out what is touching what.

**Not implemented yet, in either language.** This module exists so
that collision has a registered backend before it has code, which
is what lets the implementation arrive without the API around it
being redesigned.

Collision is per-pair and per-frame, so it is one of the systems
``"auto"`` will run natively once there is a native one.

**Backend.** ``collision.engine`` chooses which implementation runs::

    collision.engine = "auto"     # the default; a game need never set it
    collision.engine = "rust"
    collision.engine = "python"

See :mod:`trjoludus.native` for what those mean and when they take effect.
"""

from trjoludus.native import expose

__all__ = ["engine"]

#: What a game has asked for. Served by the module's own type, so that reading
#: it is live and writing something TrjoLudus does not know is refused.
engine: str

expose(__name__, recommends=None,
       python_implementation=None)
