"""What :func:`trjoludus.keyboard.wait` can wait for.

::

    tl.keyboard.wait(tl.input.key)

There are two things to wait for: :data:`key`, the next key press, and
:data:`mouse`, the next mouse button. Each goes with its own waiting
function -- ``keyboard.wait(input.key)`` and ``mouse.wait(input.mouse)`` --
which is why those calls take an argument at all.

**On the name.** ``from trjoludus import input`` shadows Python's built-in
``input()`` in that file. Reaching it as ``tl.input.key`` avoids that.
"""

from trjoludus.keyboard import key
from trjoludus.mouse import any_input as mouse

__all__ = ["key", "mouse"]
