"""What :func:`trjoludus.keyboard.wait` can wait for.

::

    tl.keyboard.wait(tl.input.key)

There are two things to wait for: :data:`key`, the next key press, and
:data:`mouse`, the next mouse button. Each goes with its own waiting
function -- ``keyboard.wait(input.key)`` and ``mouse.wait(input.mouse)`` --
which is why those calls take an argument at all.

:func:`wait` takes either, and :data:`type` says which arrived.

**On the name.** ``from trjoludus import input`` shadows Python's built-in
``input()`` in that file. Reaching it as ``tl.input.key`` avoids that.
"""

from trjoludus.errors import TrjoLudusError
from trjoludus.keyboard import key
from trjoludus.mouse import any_input as mouse

__all__ = ["key", "mouse", "type", "wait"]

#: What the last :func:`wait` received, or ``None`` before the first one.
#: Compare it against :data:`key` or :data:`mouse`.
_last_type = None


def __getattr__(name: str):
    """Serve :data:`type`, which changes with every :func:`wait`."""
    if name == "type":
        return _last_type
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def wait() -> None:
    """Wait for the next input of any kind.

    Where :func:`trjoludus.keyboard.wait` answers only to keys and
    :func:`trjoludus.mouse.wait` only to the mouse, this takes whichever
    arrives first -- and if both are already waiting, the one that arrived
    first, because they share one queue in arrival order.

    Afterwards :data:`type` says which it was, and the value is wherever that
    kind of input normally goes::

        input.wait()

        if input.type == input.key:
            print(key)
        elif input.type == input.mouse:
            print(mouse.button)

    Each item is taken exactly once, by whichever wait answers it.

    Returns:
        Nothing. What arrived goes into :data:`type` and the matching value.

    If the game asks to stop while waiting, or its last window disappears, the
    wait ends and :data:`type` becomes ``None``.

    Raises:
        TrjoLudusError: If called while no game is running.
    """
    global _last_type

    from trjoludus.app import current_application

    application = current_application()
    if application is None:
        raise TrjoLudusError(
            "input.wait() only works while a game is running. Call it from "
            "on_start or on_update, inside a game started with tl.run()."
        )

    taken = application.wait_for_input()
    if taken is None:
        _last_type = None
    else:
        _last_type = key if taken.kind == "key" else mouse
