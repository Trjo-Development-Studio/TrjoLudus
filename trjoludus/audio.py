"""Making sound.

**Not implemented yet, in either language.** Registered now so
that the backend choice exists before the code does.

Not an always-native system: mixing is real work, but the
operating system does most of it, and there is no reason to
assume the answer before there is something to measure.

**Backend.** ``audio.engine`` chooses which implementation runs::

    audio.engine = "auto"     # the default; a game need never set it
    audio.engine = "rust"
    audio.engine = "python"

See :mod:`trjoludus.native` for what those mean and when they take effect.
"""

from trjoludus.native import expose

__all__ = ["engine"]

#: What a game has asked for. Served by the module's own type, so that reading
#: it is live and writing something TrjoLudus does not know is refused.
engine: str

expose(__name__, recommends=None,
       python_implementation=None)
