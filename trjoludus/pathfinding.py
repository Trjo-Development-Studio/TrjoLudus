"""Working out how to get from one place to another.

**Not implemented yet, in either language.** Registered now so
that the backend choice exists before the code does.

Searching a grid or a graph is the kind of tight loop that is
slow in Python and fast in Rust, so it is an always-native
system.

**Backend.** ``pathfinding.engine`` chooses which implementation runs::

    pathfinding.engine = "auto"     # the default; a game need never set it
    pathfinding.engine = "rust"
    pathfinding.engine = "python"

See :mod:`trjoludus.native` for what those mean and when they take effect.
"""

from trjoludus.native import expose

__all__ = ["engine"]

#: What a game has asked for. Served by the module's own type, so that reading
#: it is live and writing something TrjoLudus does not know is refused.
engine: str

expose(__name__, recommends=None,
       python_implementation=None)
