"""Waiting for keyboard input.

::

    tl.keyboard.wait(tl.input.key)

    if tl.key == "W":
        player.move.y(-50)

:func:`wait` does not hand you a value to store. It waits for a key and
updates :data:`key`, so a game reads the key where it needs it instead of
threading a variable through.

**It waits for input that has not been answered yet.** Every press is consumed
by exactly one :func:`wait`. Press W once and call :func:`wait` twice, and the
second call keeps waiting -- it does not leave ``key`` sitting on ``"W"`` and
return. Press W then A, and two waits leave ``key`` reading ``"W"`` then
``"A"``, because nothing is thrown away.

**What ``key`` actually is.** Python cannot let one module rebind a plain
variable belonging to another, so :data:`key` is a small live value rather than
a string. It compares, prints and formats like the key name -- ``key == "W"``,
``print(key)``, ``f"{key}"`` and ``key in ("W", "A")`` all do what they look
like. It is not a ``str``, though: ``key.lower()`` will not work, and holding
on to it with ``saved = key`` keeps a reference that changes with the next
press. Use ``str(key)`` or :attr:`KeyValue.value` to take a copy.

**Nothing else happens while waiting.** The engine keeps handling window events
so the window stays responsive and a close request still reaches the game, but
no frame is drawn and ``on_update`` is not called again until :func:`wait`
returns.
"""

from trjoludus.errors import TrjoLudusError

__all__ = ["KeyValue", "key", "wait"]


class KeyValue:
    """The key that was pressed most recently.

    Reads as the key name in the places a game needs it. There is one of
    these, :data:`key`, and :func:`wait` is what updates it.
    """

    __slots__ = ("_value",)

    def __init__(self) -> None:
        self._value: str | None = None

    @property
    def value(self) -> str | None:
        """The key name as a plain string, or ``None`` if nothing yet.

        Use this to keep a copy that will not change with the next press.
        """
        return self._value

    def _set(self, value: str | None) -> None:
        self._value = value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, KeyValue):
            return self._value == other._value
        return self._value == other

    def __hash__(self) -> int:
        # Hashes the current name so `key in {"W", "A"}` works. Do not use it
        # as a dictionary key: the hash changes when the next key arrives.
        return hash(self._value)

    def __bool__(self) -> bool:
        return self._value is not None

    def __str__(self) -> str:
        return "" if self._value is None else self._value

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)

    def __repr__(self) -> str:
        return f"<key {self._value!r}>"


#: The key pressed most recently, updated by :func:`wait`.
key = KeyValue()


def wait(what) -> None:
    """Wait for a key press and update :data:`key` with it.

    Args:
        what: :data:`trjoludus.input.key`, the value to update. It is an
            argument rather than implied so that waiting for other kinds of
            input can be added later without the call reading differently.

    Returns:
        Nothing. The result goes into :data:`key`; there is deliberately no
        value to assign, so there is one way to read the key.

    If the game asks to stop while waiting -- because it honoured a close
    request -- the wait ends and :data:`key` becomes ``None`` rather than
    keeping the previous press, so a stale key cannot be acted on during
    shutdown.

    Raises:
        TrjoLudusError: If called while no game is running, or if ``what`` is
            not :data:`trjoludus.input.key`.
    """
    if what is not key:
        raise TrjoLudusError(
            f"keyboard.wait() takes input.key, not {what!r}. It is the only "
            f"kind of input TrjoLudus can wait for so far."
        )

    from trjoludus.app import current_application

    application = current_application()
    if application is None:
        raise TrjoLudusError(
            "keyboard.wait() only works while a game is running. Call it from "
            "on_start or on_update, inside a game started with tl.run()."
        )
    key._set(application._wait_for_key())
