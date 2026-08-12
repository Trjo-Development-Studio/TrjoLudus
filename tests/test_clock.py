"""Tests for frame timing.

Timing is tested against an injected fake clock rather than real time, so the
assertions are exact and the suite stays instant. A couple of tests at the end
exercise the real ``time.perf_counter``/``time.sleep`` defaults.
"""

import unittest

from trjoludus.clock import DEFAULT_MAX_DELTA, DEFAULT_MAX_FPS, Clock


class FakeTime:
    """A controllable stand-in for ``time.perf_counter`` and ``time.sleep``."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        """Simulate work taking time, without sleeping."""
        self.now += seconds


def make_clock(fake: FakeTime, **kwargs) -> Clock:
    kwargs.setdefault("max_fps", None)
    return Clock(time_source=fake.time, sleep_function=fake.sleep, **kwargs)


class TestConstruction(unittest.TestCase):
    def test_defaults(self):
        clock = Clock()
        self.assertEqual(clock.max_fps, DEFAULT_MAX_FPS)
        self.assertEqual(clock.max_delta, DEFAULT_MAX_DELTA)

    def test_rejects_zero_or_negative_max_fps(self):
        for bad in (0, -1, -0.5):
            with self.subTest(max_fps=bad), self.assertRaises(ValueError):
                Clock(max_fps=bad)

    def test_rejects_zero_or_negative_max_delta(self):
        for bad in (0, -0.1):
            with self.subTest(max_delta=bad), self.assertRaises(ValueError):
                Clock(max_delta=bad)

    def test_allows_uncapped(self):
        self.assertIsNone(Clock(max_fps=None).max_fps)

    def test_starts_at_zero(self):
        clock = Clock()
        self.assertEqual(clock.delta, 0.0)
        self.assertEqual(clock.elapsed, 0.0)
        self.assertEqual(clock.frame_count, 0)
        self.assertEqual(clock.fps, 0.0)


class TestDeltaMeasurement(unittest.TestCase):
    def test_first_tick_returns_zero(self):
        """There is no previous frame to measure against."""
        fake = FakeTime(start=123.456)
        clock = make_clock(fake)
        self.assertEqual(clock.tick(), 0.0)
        self.assertEqual(clock.frame_count, 1)

    def test_measures_time_between_ticks(self):
        fake = FakeTime()
        clock = make_clock(fake)
        clock.tick()

        fake.advance(0.1)
        self.assertAlmostEqual(clock.tick(), 0.1)

        fake.advance(0.05)
        self.assertAlmostEqual(clock.tick(), 0.05)

    def test_delta_property_matches_last_tick(self):
        fake = FakeTime()
        clock = make_clock(fake)
        clock.tick()
        fake.advance(0.02)
        returned = clock.tick()
        self.assertAlmostEqual(clock.delta, returned)

    def test_zero_length_frame(self):
        fake = FakeTime()
        clock = make_clock(fake)
        clock.tick()
        self.assertEqual(clock.tick(), 0.0)


class TestClamping(unittest.TestCase):
    def test_long_frame_is_clamped(self):
        """A blocked loop must not report a huge delta and teleport the game."""
        fake = FakeTime()
        clock = make_clock(fake, max_delta=0.25)
        clock.tick()

        fake.advance(5.0)  # e.g. window drag, or a debugger breakpoint
        self.assertAlmostEqual(clock.tick(), 0.25)

    def test_clamp_boundary_is_inclusive(self):
        fake = FakeTime()
        clock = make_clock(fake, max_delta=0.25)
        clock.tick()
        fake.advance(0.25)
        self.assertAlmostEqual(clock.tick(), 0.25)

    def test_clock_recovers_after_a_clamped_frame(self):
        fake = FakeTime()
        clock = make_clock(fake, max_delta=0.25)
        clock.tick()
        fake.advance(5.0)
        clock.tick()

        fake.advance(0.016)
        self.assertAlmostEqual(clock.tick(), 0.016)

    def test_backwards_time_reports_zero(self):
        """Guard against a non-monotonic time source; never report negative."""
        fake = FakeTime(start=10.0)
        clock = make_clock(fake)
        clock.tick()
        fake.now = 9.0
        self.assertEqual(clock.tick(), 0.0)


class TestPacing(unittest.TestCase):
    def test_sleeps_to_hit_target_frame_rate(self):
        fake = FakeTime()
        clock = make_clock(fake, max_fps=100)  # 10 ms per frame
        clock.tick()

        fake.advance(0.002)  # frame's work took 2 ms
        delta = clock.tick()

        self.assertEqual(len(fake.sleeps), 1)
        self.assertAlmostEqual(fake.sleeps[0], 0.008)
        self.assertAlmostEqual(delta, 0.01)

    def test_delta_includes_sleep(self):
        """Delta describes real elapsed time, not just time spent working."""
        fake = FakeTime()
        clock = make_clock(fake, max_fps=50)  # 20 ms per frame
        clock.tick()
        fake.advance(0.001)
        self.assertAlmostEqual(clock.tick(), 0.02)

    def test_does_not_sleep_when_frame_ran_over(self):
        fake = FakeTime()
        clock = make_clock(fake, max_fps=100)
        clock.tick()

        fake.advance(0.05)  # 50 ms of work against a 10 ms budget
        delta = clock.tick()

        self.assertEqual(fake.sleeps, [])
        self.assertAlmostEqual(delta, 0.05)

    def test_never_sleeps_when_uncapped(self):
        fake = FakeTime()
        clock = make_clock(fake, max_fps=None)
        for _ in range(5):
            clock.tick()
            fake.advance(0.0001)
        self.assertEqual(fake.sleeps, [])

    def test_first_tick_does_not_sleep(self):
        fake = FakeTime()
        clock = make_clock(fake, max_fps=60)
        clock.tick()
        self.assertEqual(fake.sleeps, [])

    def test_steady_state_holds_the_frame_rate(self):
        fake = FakeTime()
        clock = make_clock(fake, max_fps=60)
        clock.tick()
        for _ in range(10):
            fake.advance(0.001)
            clock.tick()
        self.assertAlmostEqual(clock.elapsed, 10 * (1 / 60))


class TestCounters(unittest.TestCase):
    def test_frame_count_increments_every_tick(self):
        fake = FakeTime()
        clock = make_clock(fake)
        for expected in range(1, 6):
            clock.tick()
            self.assertEqual(clock.frame_count, expected)

    def test_elapsed_sums_reported_deltas(self):
        fake = FakeTime()
        clock = make_clock(fake)
        clock.tick()
        for _ in range(4):
            fake.advance(0.1)
            clock.tick()
        self.assertAlmostEqual(clock.elapsed, 0.4)

    def test_elapsed_excludes_time_removed_by_clamping(self):
        """Elapsed tracks what the game saw, not wall-clock time."""
        fake = FakeTime()
        clock = make_clock(fake, max_delta=0.25)
        clock.tick()
        fake.advance(5.0)
        clock.tick()
        self.assertAlmostEqual(clock.elapsed, 0.25)

    def test_fps_reflects_last_delta(self):
        fake = FakeTime()
        clock = make_clock(fake)
        clock.tick()
        fake.advance(0.02)
        clock.tick()
        self.assertAlmostEqual(clock.fps, 50.0)

    def test_fps_is_zero_before_a_measured_frame(self):
        fake = FakeTime()
        clock = make_clock(fake)
        clock.tick()
        self.assertEqual(clock.fps, 0.0)


class TestReset(unittest.TestCase):
    def test_reset_clears_counters(self):
        fake = FakeTime()
        clock = make_clock(fake)
        clock.tick()
        fake.advance(0.1)
        clock.tick()

        clock.reset()

        self.assertEqual(clock.delta, 0.0)
        self.assertEqual(clock.elapsed, 0.0)
        self.assertEqual(clock.frame_count, 0)

    def test_first_tick_after_reset_returns_zero(self):
        fake = FakeTime()
        clock = make_clock(fake)
        clock.tick()
        fake.advance(0.1)
        clock.tick()

        clock.reset()
        fake.advance(10.0)  # a long gap must not leak into the next delta
        self.assertEqual(clock.tick(), 0.0)

    def test_reset_keeps_configuration(self):
        clock = Clock(max_fps=30, max_delta=0.5)
        clock.reset()
        self.assertEqual(clock.max_fps, 30)
        self.assertEqual(clock.max_delta, 0.5)


class TestRealClock(unittest.TestCase):
    """Sanity checks against the real time source and sleep function."""

    def test_uncapped_clock_produces_sane_deltas(self):
        clock = Clock(max_fps=None)
        clock.tick()
        for _ in range(3):
            delta = clock.tick()
            self.assertGreaterEqual(delta, 0.0)
            self.assertLessEqual(delta, clock.max_delta)

    def test_capped_clock_actually_paces(self):
        clock = Clock(max_fps=200)  # 5 ms per frame
        clock.tick()
        delta = clock.tick()
        self.assertGreater(delta, 0.0)
        self.assertLessEqual(delta, clock.max_delta)


if __name__ == "__main__":
    unittest.main()
