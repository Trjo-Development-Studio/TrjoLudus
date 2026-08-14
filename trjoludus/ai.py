"""Deciding what things that are not the player do.

**Not implemented yet, in either language.** Registered now so
that the backend choice exists before the code does.

Whatever shape it takes, it runs for many agents every frame, so
``"auto"`` will prefer a native implementation once there is one.

**Backend.** ``ai.engine`` chooses which implementation runs::

    ai.engine = "auto"     # the default; a game need never set it
    ai.engine = "rust"
    ai.engine = "python"

See :mod:`trjoludus.native` for what those mean and when they take effect.
"""

from trjoludus.native import expose

__all__ = ["engine"]

#: What a game has asked for. Served by the module's own type, so that reading
#: it is live and writing something TrjoLudus does not know is refused.
engine: str

expose(__name__, recommends=None,
       python_implementation=None)
