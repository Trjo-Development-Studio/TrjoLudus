"""Waiting, and how fast the game is running.

::

    from trjoludus import time

    time.wait(1)        # pause for a second
    print(time.fps)

**Movement should be measured in time, not in frames.** ``move.x(2)`` moves
twice as far on a machine drawing twice as many frames. Scaling by
:data:`delta` -- how long the last frame took -- covers the same distance per
second on both::

    def on_update(self, dt):
        self.player.move.x(100 * time.delta)   # 100 pixels every second

That works because a position is a number rather than a pixel. At 60 frames a
second each of those steps is 1.67 pixels, and the object keeps the fraction
instead of losing it or rounding it up, so a second later it has gone exactly
100 pixels. Only the renderer rounds, when it turns a position into a pixel.

``dt`` handed to :meth:`~trjoludus.game.Game.on_update` is the same number.
:data:`delta` exists so that code which is not in ``on_update`` -- a helper, a
method on your own class -- can reach it without it being passed down.

**Reading is live; writing is refused.** :data:`delta` and :data:`fps` are
looked up at the moment you read them, so they are never a stale copy, and
assigning to them raises rather than quietly replacing the engine's answer
with a number of your own.

Because they are looked up, reach them through the module. ``from
trjoludus.time import delta`` would take a copy at import time and that copy
would never change again.

This module has no timing of its own. It reads the running game's
:class:`~trjoludus.clock.Clock`, which is the one thing in the engine that
measures time.
"""

from types import ModuleType

from trjoludus.errors import TrjoLudusError

__all__ = ["delta", "fps", "wait"]

#: The names served fresh on every read, and refused on every write.
_LIVE = ("delta", "fps")


def _clock():
    """The running game's clock, or ``None`` when no game is running."""
    from trjoludus.app import current_application

    application = current_application()
    return None if application is None else application.clock


def _check_seconds(value) -> float:
    """Reject anything that is not a length of time.

    ``bool`` is excluded because ``True`` as a duration is a mistake rather
    than an intention -- the same rule sizes and positions follow.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"a number of seconds must be a number, got "
            f"{type(value).__name__}"
        )
    if value < 0:
        raise ValueError(
            f"cannot wait for {value} seconds: time only runs forwards."
        )
    return float(value)


def wait(seconds) -> None:
    """Pause the game for roughly ``seconds``.

    ::

        time.wait(1)      # one second
        time.wait(0.25)   # a quarter of one

    The window stays alive while waiting. Events are still polled and
    delivered, so a close request still reaches
    :meth:`~trjoludus.game.Game.on_event` mid-wait rather than being noticed
    a second later.

    Like every blocking call in TrjoLudus, it stops early if the game asks to
    quit or its last window disappears, so a wait can never outlive the game
    it is waiting in. There is nothing to read afterwards: waiting produces
    time passing, not a value.

    Args:
        seconds: How long to wait. ``0`` returns immediately.

    Raises:
        TypeError: If ``seconds`` is not a number.
        ValueError: If it is negative.
        TrjoLudusError: If called while no game is running. Waiting needs a
            window to keep alive, and outside a game there is none.
    """
    length = _check_seconds(seconds)

    from trjoludus.app import current_application

    application = current_application()
    if application is None:
        raise TrjoLudusError(
            "time.wait() needs a running game: it keeps the window alive "
            "while it waits, and there is no window outside a game. Call it "
            "from on_start, on_update or on_event."
        )
    application.wait_for_seconds(length)


class _Time(ModuleType):
    """The module's own type, so that reading is live and writing is refused.

    A plain module attribute would be a copy taken once. A plain
    ``__getattr__`` would keep reading fresh but let ``time.delta = 5`` shadow
    it for good, which is exactly the mistake worth catching for a value the
    engine measures and a game only reads.
    """

    def __getattr__(self, name: str):
        if name in _LIVE:
            clock = _clock()
            # No game running: a quiet zero rather than an error, so reading
            # the frame rate outside a game is not a crash. Zero is also what
            # a game sees on its first frame, and for the same reason --
            # nothing has been measured yet.
            if clock is None:
                return 0.0
            return getattr(clock, name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    def __setattr__(self, name: str, value) -> None:
        if name in _LIVE:
            raise AttributeError(
                f"time.{name} is read-only: it is what the engine measured, "
                f"not a setting. To change how fast frames come, pass "
                f"max_fps to run()."
            )
        super().__setattr__(name, value)


# Annotated rather than assigned: an assignment would be a copy taken once at
# import, and a copy is exactly what these must not be. Nothing is bound here,
# so reading either name falls through to _Time.__getattr__ every time.

#: Seconds the previous frame took. ``0.0`` on the first frame of a run, and
#: outside a game, because nothing has been measured yet -- so movement scaled
#: by it stands still for one frame rather than jumping by a made-up amount.
#: Clamped by the clock, so a stalled frame cannot teleport a game.
delta: float

#: Frames per second, worked out from the most recent frame. Instantaneous
#: rather than averaged, so it jumps about: a game showing it to a player
#: usually wants to round it, or only update the number it displays a few
#: times a second. ``0.0`` before the first measured frame.
fps: float

# Swapped in last, once everything above has been defined, so that defining
# this module does not go through the guard that protects it.
import sys  # noqa: E402

sys.modules[__name__].__class__ = _Time
del sys
