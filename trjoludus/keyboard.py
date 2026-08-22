"""Reading the keyboard.

Three questions, and they are different questions::

    if keyboard.pressed("D"):          # held right now
        player.move.x(200 * time.delta)

    if keyboard.just_pressed("SPACE"): # went down this frame
        player.jump()

    pressed_key = keyboard.wait()      # stop until something is pressed

:func:`pressed` is for anything continuous -- walking, steering, holding a
button down. :func:`just_pressed` is for anything that should happen once per
press -- jumping, firing, confirming a menu. :func:`wait` is for a game that
has nothing to do until a key arrives, such as a title screen.

Nothing is consumed by asking the first two, and neither takes a press away
from :func:`wait`.

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

    if keyboard.pressed("W"):
        player.move.y(-100 * time.delta)

:func:`pressed` asks whether a key is down *right now*. It is
state, not input: it stays true for as long as the key is held, reading it
does not use anything up, and it can be asked about as many keys as a game
likes, as often as it likes. :func:`wait` is the other thing -- it blocks
until a key arrives and hands that press out exactly once.

The two do not interfere. A press read by :func:`wait` still marks the key as
held, and asking whether a key is held never takes a press away from a wait.
"""

import warnings

from trjoludus.errors import TrjoLudusError
from trjoludus.events import KEY_NAMES

__all__ = ["KeyboardState", "KeyValue", "button", "just_pressed", "key",
           "pressed", "wait"]


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

    __slots__ = ("held", "went_down")

    def __init__(self) -> None:
        #: The keys currently down. A set, so several keys held at once is
        #: the ordinary case rather than something special.
        self.held: set[str] = set()
        #: The keys that went down since the frame began, which is what
        #: :func:`just_pressed` answers from. Emptied at the top of each
        #: frame, exactly as the frame's clicks are -- a press belongs to the
        #: frame it arrived in.
        self.went_down: set[str] = set()

    def pressed(self, name: str) -> bool:
        """Whether one key is held down in this window."""
        return name in self.held

    def just_pressed(self, name: str) -> bool:
        """Whether one key went down during this frame, in this window."""
        return name in self.went_down

    def key_down(self, name: str) -> None:
        """Engine-internal: record a key going down.

        A key already held is not going down again. Auto-repeat is asked not
        to send those, but a server that ignores that would otherwise make a
        held key look newly pressed on every frame -- which is the one thing
        :meth:`just_pressed` exists not to do.
        """
        if name not in self.held:
            self.went_down.add(name)
        self.held.add(name)

    def key_up(self, name: str) -> None:
        """Engine-internal: record a key coming up."""
        self.held.discard(name)

    def begin_frame(self) -> None:
        """Engine-internal: nothing has newly gone down yet this frame."""
        self.went_down.clear()

    def forget_everything(self) -> None:
        """Engine-internal: nothing can still be held, or newly held.

        Used when a window goes away. A key held as the window disappeared
        would otherwise stay held for good -- there is no release coming for
        a window that no longer exists.
        """
        self.held.clear()
        self.went_down.clear()

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


def pressed(name: str) -> bool:
    """Whether a key is held down right now.

    ::

        if keyboard.pressed("D"):
            player.move.x(200 * time.delta)

    True from the moment the key goes down until it comes back up, on every
    frame in between. This is *not* "was it pressed this frame" --
    :func:`just_pressed` is that. Holding D means ``pressed("D")`` is true the
    whole time, which is what continuous movement is made of.

    Nothing is consumed by asking, so two calls in the same frame give the
    same answer and any number of keys can be asked about as often as a game
    likes.

    Args:
        name: A key name, e.g. ``"W"`` or ``"ESCAPE"``. Uppercase.

    Raises:
        TypeError: If ``name`` is not a string.
        ValueError: If it is not a key TrjoLudus knows.
    """
    return active_state().pressed(_check_key(name))


def just_pressed(name: str) -> bool:
    """Whether a key went down during this frame.

    ::

        if keyboard.just_pressed("SPACE"):
            player.jump()

    True for the one frame in which the key went from up to down, and false on
    every frame after that however long it is held. This is the question
    behind jumping, firing, confirming a menu and toggling something -- the
    things that should happen once per press rather than continuously.

    Its opposite number is :func:`pressed`, which stays true while the key is
    down. Neither consumes anything, and neither takes a press away from
    :func:`wait`.

    A key held across a frame boundary does not go down again, so this stays
    false until it has actually been let go and pressed once more.

    Args:
        name: A key name, e.g. ``"SPACE"``. Uppercase.

    Raises:
        TypeError: If ``name`` is not a string.
        ValueError: If it is not a key TrjoLudus knows.
    """
    return active_state().just_pressed(_check_key(name))


class KeyboardButtons:
    """The old ``keyboard.button`` spelling of :func:`pressed`.

    Kept so that games written before the keyboard and the mouse were given
    the same shape keep working. ``keyboard.pressed("W")`` is the one to
    write: it matches ``mouse.pressed("LEFT")``, which was never nested.

    There is no second implementation here -- these call the module functions.
    """

    __slots__ = ()

    def pressed(self, name: str) -> bool:
        """See :func:`trjoludus.keyboard.pressed`."""
        return pressed(name)

    def just_pressed(self, name: str) -> bool:
        """See :func:`trjoludus.keyboard.just_pressed`."""
        return just_pressed(name)

    def released(self, name: str) -> bool:
        """Deprecated. Meant "not held", which is not what it sounded like.

        Every engine a game developer has met uses *released* for the moment a
        key comes up -- an edge, like :func:`just_pressed` is for going down.
        This was never that: it answered true for a key nobody had ever
        touched. Code written to detect a key coming up would have fired
        continuously, for every key, for ever.

        Write ``not keyboard.pressed("W")`` for what this actually did. The
        name is being kept free for a real release edge.

        .. deprecated::
            Warns, and will be removed. There is no replacement because
            ``not pressed(...)`` was always the honest spelling.
        """
        warnings.warn(
            "keyboard.button.released(name) means 'not held', which is not "
            "what the name suggests -- it is true for a key nobody has "
            "touched, not only for one just let go of. Write "
            "'not keyboard.pressed(name)' instead. The name is reserved for a "
            "real key-release edge later.",
            DeprecationWarning, stacklevel=2,
        )
        return not pressed(name)

    def __repr__(self) -> str:
        return repr(active_state())


#: The old spelling of :func:`pressed`. See :class:`KeyboardButtons`.
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


def wait(what=None) -> "str | None":
    """Wait for a key press and return which key it was.

    ::

        pressed_key = keyboard.wait()

        if pressed_key == "W":
            player.move.y(-20)

    Nothing else happens while waiting. The engine keeps handling window
    events so the window stays responsive and a close request still reaches
    the game, but no frame is drawn and ``on_update`` is not called again
    until this returns.

    Args:
        what: Nothing. Accepted so that ``keyboard.wait(input.key)``, the way
            this used to be written, keeps working. There was only ever one
            legal value, which is why it is not needed.

    Returns:
        The key name, as an ordinary string -- ``"W"``, ``"ESCAPE"``. ``None``
        if the game asked to stop while waiting, or its last window
        disappeared, so a stale key cannot be acted on during shutdown.

        :data:`key` is updated too, for games written before this returned
        anything. It is a mirror now, not the only way to read the answer.

    Raises:
        TrjoLudusError: If called while no game is running, or if ``what`` is
            something other than :data:`trjoludus.input.key`.
    """
    if what is not None and what is not key:
        raise TrjoLudusError(
            f"keyboard.wait() takes no arguments, and got {what!r}. Write "
            f"'pressed_key = keyboard.wait()' -- it returns the key."
        )

    from trjoludus.app import current_application

    application = current_application()
    if application is None:
        raise TrjoLudusError(
            "keyboard.wait() only works while a game is running. Call it from "
            "on_start or on_update, inside a game started with tl.run()."
        )
    taken = application.wait_for_input(kind="key")
    return None if taken is None else taken.value
