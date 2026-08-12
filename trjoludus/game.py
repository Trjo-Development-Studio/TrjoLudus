"""The base class games derive from.

TrjoLudus owns the game loop; a game supplies callbacks. :class:`Game` is
therefore a set of hooks plus one control method, :meth:`quit`. It holds no
window, no backend and no loop of its own -- those belong to
:class:`~trjoludus.app.Application`.

Every callback has a do-nothing default, so a game overrides only what it
needs::

    class Pong(tl.Game):
        def on_update(self, dt):
            ...
"""

from trjoludus.events import Event

__all__ = ["Game"]


class Game:
    """Base class for a TrjoLudus game.

    Subclass it and override the callbacks you care about. The engine calls
    them in this order::

        on_start()
        loop:
            on_event(event)   for each event that arrived
            on_update(dt)
        on_stop()
    """

    #: Backing store for :attr:`quit_requested`. A class attribute rather than
    #: an ``__init__`` assignment so that a subclass defining its own
    #: ``__init__`` cannot break :meth:`quit` by forgetting ``super()``.
    _quit_requested: bool = False

    @property
    def quit_requested(self) -> bool:
        """Whether :meth:`quit` has been called.

        Read-only: a game asks to stop by calling :meth:`quit`, and the
        application only observes the answer. There is deliberately no setter,
        so the request has exactly one entry point.
        """
        return self._quit_requested

    def on_start(self) -> None:
        """Called once, after the window exists and before the first frame.

        The place to set up game state. Anything created here is still torn
        down by :meth:`on_stop` if a later frame raises.
        """

    def on_event(self, event: Event) -> None:
        """Called for each event that arrived, in the order it arrived.

        Events are platform-neutral: the same
        :class:`~trjoludus.events.WindowCloseRequested` arrives whether the
        window is running on X11 or Win32.

        The engine does not act on any event by itself. In particular, closing
        the window is a *request*, and a game that wants to honour it must say
        so::

            def on_event(self, event):
                if isinstance(event, tl.WindowCloseRequested):
                    self.quit()

        A game that never calls :meth:`quit` runs until something else stops
        it, which is intentional -- it leaves room for "save before quitting?"
        prompts.
        """

    def on_update(self, dt: float) -> None:
        """Called once per frame with the time since the previous frame.

        Args:
            dt: Seconds elapsed, clamped so that a stalled frame cannot make
                the simulation jump. ``0.0`` on the first frame.
        """

    def on_stop(self) -> None:
        """Called once, after the loop ends and before the window closes.

        Also called when a callback raises, provided :meth:`on_start` itself
        completed -- so a game that allocated something in :meth:`on_start`
        can always release it here.
        """

    def quit(self) -> None:
        """Ask the application to stop.

        This only *requests* a stop. The window stays open and the backend
        stays alive until the engine unwinds; cleanup is the application's
        job, not the game's.

        The current frame finishes first: any events already dispatched are
        still delivered, but :meth:`on_update` is not called again. Calling it
        more than once, or before the loop starts, is harmless -- the request
        is a flag, not a queue.

        Sets :attr:`quit_requested`, which is how the application observes it.
        """
        self._quit_requested = True
