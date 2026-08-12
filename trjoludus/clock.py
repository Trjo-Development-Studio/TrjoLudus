"""Frame timing.

:class:`Clock` measures the time between frames and, optionally, paces the loop
to a target frame rate. It is pure Python and contains no operating-system
code: ``time.perf_counter`` is a monotonic clock on both Linux and Windows, and
``time.sleep`` on Python 3.11+ uses high-resolution timers on both.

Two behaviours are deliberate and worth understanding:

**Delta time is clamped.** If a frame takes far longer than usual -- the user
dragged the window (which blocks the loop entirely on Windows), the process was
suspended, or a debugger stopped at a breakpoint -- the next delta would
otherwise be enormous, and a game doing ``x += speed * dt`` would teleport.
Clamping trades a brief slow-motion effect for never losing control of the
simulation.

**The first tick returns 0.0.** There is no previous frame to measure against,
so the first call only establishes a baseline.
"""

from collections.abc import Callable
from time import perf_counter, sleep

__all__ = ["Clock"]

#: Longest delta, in seconds, that :class:`Clock` will report by default.
#: Roughly four frames per second: slow enough to be visible, fast enough that
#: the simulation stays stable.
DEFAULT_MAX_DELTA = 0.25

#: Default frame-rate cap. Milestone 1 has no renderer and therefore no vsync,
#: so an unpaced loop would spin a CPU core at 100% doing nothing.
DEFAULT_MAX_FPS = 60.0


class Clock:
    """Measures frame deltas and paces the loop to a target frame rate.

    Args:
        max_fps: Target frame rate, or ``None`` to run unpaced. The clock
            sleeps at the start of :meth:`tick` for however long is needed to
            keep frames this far apart.
        max_delta: Longest delta, in seconds, that :meth:`tick` will report.
        time_source: Callable returning a monotonically increasing time in
            seconds. Injectable so timing can be tested deterministically.
        sleep_function: Callable that sleeps for a given number of seconds.
            Injectable for the same reason.

    Raises:
        ValueError: If ``max_fps`` or ``max_delta`` is not positive.
    """

    def __init__(
        self,
        *,
        max_fps: float | None = DEFAULT_MAX_FPS,
        max_delta: float = DEFAULT_MAX_DELTA,
        time_source: Callable[[], float] = perf_counter,
        sleep_function: Callable[[float], None] = sleep,
    ) -> None:
        if max_fps is not None and max_fps <= 0:
            raise ValueError(f"max_fps must be positive or None, got {max_fps!r}")
        if max_delta <= 0:
            raise ValueError(f"max_delta must be positive, got {max_delta!r}")

        self._max_fps = max_fps
        self._frame_period = None if max_fps is None else 1.0 / max_fps
        self._max_delta = max_delta
        self._time = time_source
        self._sleep = sleep_function

        self._last: float | None = None
        self._delta = 0.0
        self._elapsed = 0.0
        self._frames = 0

    @property
    def max_fps(self) -> float | None:
        """Target frame rate, or ``None`` if the clock is unpaced."""
        return self._max_fps

    @property
    def max_delta(self) -> float:
        """Longest delta, in seconds, that :meth:`tick` will report."""
        return self._max_delta

    @property
    def delta(self) -> float:
        """Delta returned by the most recent :meth:`tick`, in seconds."""
        return self._delta

    @property
    def elapsed(self) -> float:
        """Total simulated time, in seconds.

        This is the sum of the deltas actually reported, so it excludes time
        removed by clamping. It tracks what the game has seen, not wall-clock
        time.
        """
        return self._elapsed

    @property
    def frame_count(self) -> int:
        """Number of times :meth:`tick` has been called since the last reset."""
        return self._frames

    @property
    def fps(self) -> float:
        """Frame rate implied by the most recent delta.

        Instantaneous and therefore jittery; it is not a smoothed average.
        Returns ``0.0`` before the first measured frame.
        """
        return 1.0 / self._delta if self._delta > 0.0 else 0.0

    def tick(self) -> float:
        """Advance one frame and return the delta, in seconds.

        Sleeps first, if pacing is enabled and the frame finished early, then
        measures. The returned delta therefore includes any time spent asleep,
        because it describes real elapsed time between frames.

        Returns:
            Seconds since the previous tick, clamped to :attr:`max_delta`.
            Always ``0.0`` on the first call after construction or
            :meth:`reset`.
        """
        now = self._time()

        if self._last is None:
            self._last = now
            self._delta = 0.0
            self._frames += 1
            return 0.0

        if self._frame_period is not None:
            remaining = (self._last + self._frame_period) - now
            if remaining > 0.0:
                self._sleep(remaining)
                now = self._time()

        delta = now - self._last
        self._last = now

        # Guard against a non-monotonic time source before clamping.
        delta = min(max(delta, 0.0), self._max_delta)

        self._delta = delta
        self._elapsed += delta
        self._frames += 1
        return delta

    def reset(self) -> None:
        """Return the clock to its just-constructed state.

        The next :meth:`tick` re-establishes the baseline and returns ``0.0``.
        Counters and elapsed time are zeroed; configuration is untouched.
        """
        self._last = None
        self._delta = 0.0
        self._elapsed = 0.0
        self._frames = 0
