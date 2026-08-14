"""Moving things according to rules rather than instructions.

**Not implemented yet, in either language.** Registered now so
that the backend choice exists before the code does.

Physics integrates every body every frame, which is exactly the
shape of work that belongs in a native implementation.

**Backend.** ``physics.engine`` chooses which implementation runs::

    physics.engine = "auto"     # the default; a game need never set it
    physics.engine = "rust"
    physics.engine = "python"

See :mod:`trjoludus.native` for what those mean and when they take effect.
"""

from trjoludus.native import expose

__all__ = ["engine"]

#: What a game has asked for. Served by the module's own type, so that reading
#: it is live and writing something TrjoLudus does not know is refused.
engine: str

expose(__name__, recommends=None,
       python_implementation=None)
