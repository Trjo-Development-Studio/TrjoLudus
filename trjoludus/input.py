"""What :func:`trjoludus.keyboard.wait` can wait for.

::

    tl.keyboard.wait(tl.input.key)

Right now there is one thing to wait for: :data:`key`, the next key press.
Mouse input would be added here as ``input.mouse``, which is why
:func:`~trjoludus.keyboard.wait` takes an argument at all.

**On the name.** ``from trjoludus import input`` shadows Python's built-in
``input()`` in that file. Reaching it as ``tl.input.key`` avoids that.
"""

from trjoludus.keyboard import key

__all__ = ["key"]
