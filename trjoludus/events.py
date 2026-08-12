"""Platform-neutral event types.

Backends translate operating-system messages into these types, so nothing above
``trjoludus/platform/`` ever sees an X11 ``ClientMessage`` or a Win32 ``WM_``
constant.

Events are immutable. A backend hands an event to the engine and keeps no
further interest in it, and a game must not be able to alter an event it
receives.

Milestone 1 defines exactly two events. More are added as the milestones that
produce them land.
"""

from dataclasses import dataclass

__all__ = [
    "Event",
    "WindowCloseRequested",
    "WindowResized",
]


@dataclass(frozen=True, slots=True)
class Event:
    """Base class for every TrjoLudus event.

    Exists so that event handlers can be typed as accepting an ``Event``, and
    so that ``isinstance(x, Event)`` is a meaningful check. It carries no data
    of its own.
    """


@dataclass(frozen=True, slots=True)
class WindowCloseRequested(Event):
    """The user asked to close the window, e.g. via the window's close button.

    This is a *request*. The engine does not act on it by itself; a game
    decides whether to shut down, prompt to save, or ignore it entirely.
    """


@dataclass(frozen=True, slots=True)
class WindowResized(Event):
    """The window's drawable area changed size.

    Attributes:
        width: New width of the client area, in pixels.
        height: New height of the client area, in pixels.
    """

    width: int
    height: int
