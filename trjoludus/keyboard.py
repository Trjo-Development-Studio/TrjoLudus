"""Waiting for keyboard input.

::

    tl.keyboard.wait(tl.input.key)

    if tl.key == "W":
        player.move.y(-50)

:func:`wait` does not hand you a value to store. It waits for a key and
updates :data:`key`, so a game reads the key where it needs it instead of
threading a variable through.

**Only the keyboard ends this wait.** A mouse click does not, and is not
thrown away either -- it stays queued for :func:`trjoludus.mouse.wait` or
:func:`trjoludus.input.wait`.

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

**Holding a key is a different question from pressing one.**

::

    if keyboard.button.pressed("W"):
        player.move.y(-100 * time.delta)

:meth:`KeyboardButtons.pressed` asks whether a key is down *right now*. It is
state, not input: it stays true for as long as the key is held, reading it
does not use anything up, and it can be asked about as many keys as a game
likes, as often as it likes. :func:`wait` is the other thing -- it blocks
until a key arrives and hands that press out exactly once.

The two do not interfere. A press read by :func:`wait` still marks the key as
held, and asking whether a key is held never takes a press away from a wait.
"""

from trjoludus.errors import TrjoLudusError
from trjoludus.events import KEY_NAMES

__all__ = ["KeyboardState", "KeyValue", "button", "key", "wait"]


def _check_key(name: str) -> str:
    """Reject anything that is not a key TrjoLudus can name.

    A misspelled name would otherwise answer "not held" forever, which looks
    exactly like a key that is simply not being pressed -- the worst kind of
    bug to find.
    """
    if not isinstance(name, str):
        raise TypeError(
            f"a key must be named with a string, got {type(name).__name__}"
        )
    if name not in KEY_NAMES:
        upper = name.upper()
        if upper in KEY_NAMES:
            raise ValueError(
                f"{name!r} is not a key name TrjoLudus knows, but "
                f"{upper!r} is. Key names are uppercase."
            )
        raise ValueError(
            f"{name!r} is not a key TrjoLudus knows. Letters and digits are "
            f"their own character, and the rest are spelled out: "
            f"ESCAPE, ENTER, SPACE, UP, DOWN, LEFT, RIGHT."
        )
    return name


class KeyboardState:
    """Which keys are held down, as one window sees them.

    There is one of these per window, for the same reason the pointer has one:
    a key is held *in* a window, and a window that is not focused is not
    receiving the key. A game has a single window today and reads it through
    :data:`button`; several windows would each have their own without the
    input system changing shape.
    """

    __slots__ = ("held",)

    def __init__(self) -> None:
        #: The keys currently down. A set, so several keys held at once is
        #: the ordinary case rather than something special.
        self.held: set[str] = set()

    def pressed(self, name: str) -> bool:
        """Whether one key is held down in this window."""
        return name in self.held

    def key_down(self, name: str) -> None:
        """Engine-internal: record a key going down."""
        self.held.add(name)

    def key_up(self, name: str) -> None:
        """Engine-internal: record a key coming up."""
        self.held.discard(name)

    def forget_everything(self) -> None:
        """Engine-internal: nothing can still be held.

        Used when a window goes away. A key held as the window disappeared
        would otherwise stay held for good -- there is no release coming for
        a window that no longer exists.
        """
        self.held.clear()

    def __repr__(self) -> str:
        held = ", ".join(sorted(self.held)) or "nothing held"
        return f"KeyboardState({held})"


#: Answers when no game is running, so reading the keyboard outside a game is
#: a quiet "nothing is held" rather than an error. Never written to.
_idle = KeyboardState()


def active_state() -> KeyboardState:
    """The :class:`KeyboardState` :data:`button` reads.

    The running game's window, or an untouched state when nothing is running.
    """
    from trjoludus.app import current_application

    application = current_application()
    if application is None:
        return _idle
    return application.keyboard_state()


class KeyboardButtons:
    """Which keys are down right now.

    Reached as ``keyboard.button``::

        if keyboard.button.pressed("W"):
            player.move.y(-100 * time.delta)

    Both questions are about the present moment. Nothing is consumed by
    asking, so two calls in the same frame give the same answer, and any
    number of keys can be asked about every frame -- the state is kept up to
    date as key events arrive rather than worked out on demand.
    """

    __slots__ = ()

    def pressed(self, name: str) -> bool:
        """Whether a key is held down right now.

        True from the moment the key goes down until it comes back up, on
        every frame in between. This is *not* "was it pressed this frame":
        holding W means ``pressed("W")`` is true the whole time.

        Args:
            name: A key name, e.g. ``"W"`` or ``"ESCAPE"``. Uppercase.

        Raises:
            TypeError: If ``name`` is not a string.
            ValueError: If it is not a key TrjoLudus knows.
        """
        return active_state().pressed(_check_key(name))

    def released(self, name: str) -> bool:
        """Whether a key is *not* being held right now.

        Exactly the opposite of :meth:`pressed`, and current state in the same
        way: it is true for a key nobody has touched, not only for one just
        let go of. It exists so that "while this is not held" reads as plainly
        as its opposite.

        Raises:
            TypeError: If ``name`` is not a string.
            ValueError: If it is not a key TrjoLudus knows.
        """
        return not active_state().pressed(_check_key(name))

    def __repr__(self) -> str:
        return repr(active_state())


#: Which keys are held down. See :class:`KeyboardButtons`.
button = KeyboardButtons()


def _reset() -> None:
    """Engine-internal: forget the keyboard state kept for no running game."""
    _idle.forget_everything()


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

    If the game asks to stop while waiting, or its last window disappears, the
    wait ends and :data:`key` becomes ``None`` rather than keeping the
    previous press, so a stale key cannot be acted on during shutdown.

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
    application.wait_for_input(kind="key")
