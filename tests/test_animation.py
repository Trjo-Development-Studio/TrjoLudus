"""Tests for animation: definition, playback, timing and warnings.

Timing is driven by handing the scene exact numbers of seconds rather than by
running a real clock, so "four frames at 10 fps takes 0.4 seconds" is checked
exactly instead of raced. The tests that go through a real run use the null
backend and script their own way out.

Frames are real PNGs written to a temporary folder, each a different solid
colour, so "which frame is showing" can be answered by looking at the pixels
rather than by trusting a counter.
"""

import struct
import tempfile
import unittest
import warnings
import zlib
from pathlib import Path

from trjoludus import Game, GameObject, create
from trjoludus.animation import DEFAULT_FPS, AnimationError
from trjoludus.app import Application
from trjoludus.errors import TrjoLudusWarning
from trjoludus.platform.null import NullBackend
from trjoludus.rendering_python import DEFAULT_CLEAR_COLOUR, Framebuffer
from trjoludus.scene import SceneError, current_scene
from trjoludus.ui import current_ui

RED = (250, 0, 0)
GREEN = (0, 250, 0)
BLUE = (0, 0, 250)
YELLOW = (250, 250, 0)
COLOURS = [RED, GREEN, BLUE, YELLOW]


def write_png(path, colour, size=4):
    """A small solid-colour PNG, so a frame can be told apart on screen."""
    red, green, blue = colour
    rows = b"".join(b"\x00" + bytes([red, green, blue, 255]) * size
                    for _ in range(size))

    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b""))
    return str(path)


class AnimationTestCase(unittest.TestCase):
    """One object called "player", with four differently-coloured frames."""

    @classmethod
    def setUpClass(cls):
        cls._folder = tempfile.TemporaryDirectory()
        folder = Path(cls._folder.name)
        cls.walk = [write_png(folder / f"walk_{n}.png", COLOURS[n - 1])
                    for n in range(1, 5)]
        cls.idle = write_png(folder / "idle.png", (100, 100, 100))
        cls.missing = str(folder / "nowhere.png")
        cls.not_a_png = str(folder / "notes.txt")
        Path(cls.not_a_png).write_text("this is not a png")

    @classmethod
    def tearDownClass(cls):
        cls._folder.cleanup()

    def setUp(self):
        current_scene().clear()
        current_ui().clear()
        self.addCleanup(current_scene().clear)
        self.addCleanup(current_ui().clear)
        self.player = create.image(0, 0, self.walk[0], "player")

    def quietly(self, call, *args, **kwargs):
        """Run something that warns, keeping it out of the test report."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TrjoLudusWarning)
            return call(*args, **kwargs)

    def define_walk(self):
        self.player.animation.add("walk", self.walk)

    def tick(self, seconds):
        """Give the scene exactly this many seconds of animation."""
        current_scene().advance_animations(seconds)

    def showing(self):
        """The colour the object is currently drawn in."""
        buffer = Framebuffer(20, 20)
        buffer.clear()
        obj = current_scene().require("player")
        buffer.draw_image(obj.image, obj.x, obj.y, obj.scale)
        blue, green, red, _ = buffer.pixels[0:4]
        return (red, green, blue)


class TestDefining(AnimationTestCase):
    def test_an_animation_can_be_added(self):
        self.define_walk()
        self.assertEqual(self.player.animation.names, ("walk",))
        self.assertEqual(self.player.animation.frames("walk"), 4)

    def test_one_frame_is_a_valid_animation(self):
        self.player.animation.add("idle", [self.idle])
        self.assertEqual(self.player.animation.frames("idle"), 1)

    def test_several_animations_on_one_object(self):
        self.define_walk()
        self.player.animation.add("idle", [self.idle])
        self.assertEqual(self.player.animation.names, ("walk", "idle"))

    def test_a_duplicate_name_is_refused(self):
        self.define_walk()
        with self.assertRaises(AnimationError) as caught:
            self.player.animation.add("walk", self.walk)
        message = str(caught.exception)
        self.assertIn("already has an animation called 'walk'", message)

    def test_an_empty_animation_is_refused(self):
        with self.assertRaises(AnimationError) as caught:
            self.player.animation.add("walk", [])
        self.assertIn("no frames", str(caught.exception))

    def test_a_missing_image_says_to_check_the_file(self):
        with self.assertRaises(AnimationError) as caught:
            self.player.animation.add("walk", [self.walk[0], self.missing])
        message = str(caught.exception)
        self.assertIn("frame 2", message)
        self.assertIn("Check that the file exists", message)
        self.assertIn("nowhere.png", message)

    def test_a_file_that_is_not_an_image_is_refused(self):
        with self.assertRaises(AnimationError) as caught:
            self.player.animation.add("walk", [self.not_a_png])
        self.assertIn("could not be loaded", str(caught.exception))

    def test_a_failed_definition_leaves_nothing_behind(self):
        with self.assertRaises(AnimationError):
            self.player.animation.add("walk", [self.missing])
        self.assertEqual(self.player.animation.names, ())
        self.player.animation.add("walk", self.walk)   # the name is still free

    def test_a_name_must_be_a_string(self):
        with self.assertRaises(TypeError):
            self.player.animation.add(7, self.walk)

    def test_an_empty_name_is_refused(self):
        with self.assertRaises(ValueError):
            self.player.animation.add("", self.walk)

    def test_one_path_is_not_a_list_of_frames(self):
        with self.assertRaises(TypeError) as caught:
            self.player.animation.add("walk", self.walk[0])
        self.assertIn("list of image paths", str(caught.exception))

    def test_playing_something_that_does_not_exist(self):
        self.define_walk()
        with self.assertRaises(AnimationError) as caught:
            self.player.animation.play("run")
        self.assertIn("no animation called 'run'", str(caught.exception))
        self.assertIn("walk", str(caught.exception))

    def test_the_error_helps_when_there_are_none_at_all(self):
        with self.assertRaises(AnimationError) as caught:
            self.player.animation.play("walk")
        self.assertIn("no animations at all", str(caught.exception))


class TestFrameProgression(AnimationTestCase):
    def setUp(self):
        super().setUp()
        self.define_walk()

    def test_playing_shows_the_first_frame_at_once(self):
        self.player.animation.play("walk", fps=10)
        self.assertEqual(self.player.animation.frame, 1)
        self.assertEqual(self.showing(), RED)

    def test_frames_advance_with_time(self):
        self.player.animation.play("walk", fps=10)
        seen = [self.showing()]
        for _ in range(3):
            self.tick(0.1)
            seen.append(self.showing())
        self.assertEqual(seen, [RED, GREEN, BLUE, YELLOW])

    def test_time_below_the_frame_length_changes_nothing(self):
        self.player.animation.play("walk", fps=10)
        self.tick(0.05)
        self.assertEqual(self.player.animation.frame, 1)
        self.tick(0.05)
        self.assertEqual(self.player.animation.frame, 2)

    def test_fractions_of_a_frame_add_up(self):
        """Ten frames' worth of thirds must land exactly on frame four."""
        self.player.animation.play("walk", fps=10)
        for _ in range(9):
            self.tick(1 / 30)
        self.assertEqual(self.player.animation.frame, 4)

    def test_fps_sets_the_speed(self):
        self.player.animation.play("walk", fps=20)
        self.tick(0.05)
        self.assertEqual(self.player.animation.frame, 2)
        self.tick(0.05)
        self.assertEqual(self.player.animation.frame, 3)

    def test_the_default_is_ten_frames_a_second(self):
        self.player.animation.play("walk")
        self.assertEqual(DEFAULT_FPS, 10.0)
        self.tick(0.099)
        self.assertEqual(self.player.animation.frame, 1)
        self.tick(0.002)
        self.assertEqual(self.player.animation.frame, 2)

    def test_a_long_frame_advances_several(self):
        """A stall must not make the animation play in slow motion."""
        self.player.animation.play("walk", fps=10)
        self.tick(0.25)
        self.assertEqual(self.player.animation.frame, 3)

    def test_fps_is_checked(self):
        for bad in (0, -5):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.player.animation.play("walk", fps=bad)
        for bad in ("fast", None, True):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    self.player.animation.play("walk", fps=bad)

    def test_loop_must_be_a_bool(self):
        with self.assertRaises(TypeError):
            self.player.animation.play("walk", loop="yes")


class TestLooping(AnimationTestCase):
    def setUp(self):
        super().setUp()
        self.define_walk()

    def test_it_starts_again_at_the_end(self):
        self.player.animation.play("walk", fps=10, loop=True)
        for _ in range(4):
            self.tick(0.1)
        self.assertEqual(self.player.animation.frame, 1)
        self.assertEqual(self.showing(), RED)

    def test_it_keeps_going(self):
        self.player.animation.play("walk", fps=10, loop=True)
        for _ in range(20):
            self.tick(0.1)
        self.assertTrue(self.player.animation.is_playing)
        self.assertFalse(self.player.animation.finished)

    def test_a_looping_animation_is_never_finished(self):
        self.player.animation.play("walk", fps=10, loop=True)
        for _ in range(9):
            self.tick(0.1)
            self.assertFalse(self.player.animation.finished)


class TestPlayingOnce(AnimationTestCase):
    def setUp(self):
        super().setUp()
        self.define_walk()

    def test_it_stops_on_the_last_frame(self):
        self.player.animation.play("walk", fps=10, loop=False)
        for _ in range(6):
            self.tick(0.1)
        self.assertEqual(self.player.animation.frame, 4)
        self.assertEqual(self.showing(), YELLOW)

    def test_it_reports_finished(self):
        self.player.animation.play("walk", fps=10, loop=False)
        self.assertFalse(self.player.animation.finished)
        for _ in range(4):
            self.tick(0.1)
        self.assertTrue(self.player.animation.finished)
        self.assertFalse(self.player.animation.is_playing)

    def test_it_stays_on_the_last_frame_however_long_it_runs(self):
        self.player.animation.play("walk", fps=10, loop=False)
        for _ in range(50):
            self.tick(0.1)
        self.assertEqual(self.player.animation.frame, 4)
        self.assertEqual(self.showing(), YELLOW)

    def test_playing_again_afterwards_starts_from_the_first_frame(self):
        self.player.animation.play("walk", fps=10, loop=False)
        for _ in range(6):
            self.tick(0.1)
        self.player.animation.play("walk", fps=10, loop=False)
        self.assertEqual(self.player.animation.frame, 1)
        self.assertEqual(self.showing(), RED)
        self.assertTrue(self.player.animation.is_playing)
        self.assertFalse(self.player.animation.finished)

    def test_current_still_names_it_after_it_finishes(self):
        self.player.animation.play("walk", fps=10, loop=False)
        for _ in range(6):
            self.tick(0.1)
        self.assertEqual(self.player.animation.current, "walk")

    def test_a_single_frame_animation_finishes(self):
        self.player.animation.add("idle", [self.idle])
        self.player.animation.play("idle", loop=False)
        self.tick(0.2)
        self.assertTrue(self.player.animation.finished)
        self.assertEqual(self.player.animation.frame, 1)

    def test_a_single_frame_animation_can_loop_forever(self):
        self.player.animation.add("idle", [self.idle])
        self.player.animation.play("idle", loop=True)
        for _ in range(10):
            self.tick(0.2)
        self.assertTrue(self.player.animation.is_playing)
        self.assertEqual(self.player.animation.frame, 1)


class TestPlayDoesNotRestart(AnimationTestCase):
    def setUp(self):
        super().setUp()
        self.define_walk()

    def test_playing_again_does_not_go_back_to_frame_one(self):
        self.player.animation.play("walk", fps=10)
        self.tick(0.1)
        self.quietly(self.player.animation.play, "walk", fps=10)
        self.assertEqual(self.player.animation.frame, 2)

    def test_the_animation_keeps_progressing_while_replayed(self):
        """The pattern of a game playing every frame while a key is held."""
        self.player.animation.play("walk", fps=10)
        seen = []
        for _ in range(4):
            self.quietly(self.player.animation.play, "walk", fps=10)
            self.tick(0.1)
            seen.append(self.player.animation.frame)
        self.assertEqual(seen, [2, 3, 4, 1])

    def test_new_settings_are_ignored_entirely(self):
        self.player.animation.play("walk", fps=10, loop=True)
        self.quietly(self.player.animation.play, "walk", fps=100, loop=False)
        self.tick(0.05)
        self.assertEqual(self.player.animation.frame, 1,
                         "the new fps was used")
        for _ in range(6):
            self.tick(0.1)
        self.assertFalse(self.player.animation.finished,
                         "the new loop setting was used")

    def test_stopping_first_is_how_settings_change(self):
        self.player.animation.play("walk", fps=10)
        self.player.animation.stop("walk")
        self.player.animation.play("walk", fps=20)
        self.tick(0.05)
        self.assertEqual(self.player.animation.frame, 2)

    def test_it_warns_the_first_time(self):
        self.player.animation.play("walk")
        with self.assertWarns(TrjoLudusWarning) as caught:
            self.player.animation.play("walk")
        message = str(caught.warning)
        self.assertIn("already playing", message)
        self.assertIn("stop it first", message)

    def test_it_does_not_warn_every_frame(self):
        self.player.animation.play("walk")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(60):
                self.player.animation.play("walk")
                self.tick(1 / 60)
        self.assertEqual(len(caught), 1, "the warning was raised every frame")

    def test_it_warns_again_after_playback_changes(self):
        self.player.animation.play("walk")
        self.quietly(self.player.animation.play, "walk")
        self.player.animation.stop("walk")
        self.player.animation.play("walk")
        with self.assertWarns(TrjoLudusWarning):
            self.player.animation.play("walk")

    def test_playing_a_different_animation_switches(self):
        self.player.animation.add("idle", [self.idle])
        self.player.animation.play("walk", fps=10)
        self.tick(0.1)
        self.player.animation.play("idle")
        self.assertEqual(self.player.animation.current, "idle")
        self.assertEqual(self.player.animation.frame, 1)


class TestPauseResumeStop(AnimationTestCase):
    def setUp(self):
        super().setUp()
        self.define_walk()

    def test_pause_freezes_the_frame(self):
        self.player.animation.play("walk", fps=10)
        self.tick(0.1)
        self.player.animation.pause("walk")
        for _ in range(5):
            self.tick(0.1)
        self.assertEqual(self.player.animation.frame, 2)
        self.assertEqual(self.showing(), GREEN)
        self.assertFalse(self.player.animation.is_playing)

    def test_resume_carries_on_from_there(self):
        self.player.animation.play("walk", fps=10)
        self.tick(0.1)
        self.player.animation.pause("walk")
        self.tick(0.5)
        self.player.animation.resume("walk")
        self.assertTrue(self.player.animation.is_playing)
        self.tick(0.1)
        self.assertEqual(self.player.animation.frame, 3)

    def test_stop_keeps_the_current_frame(self):
        self.player.animation.play("walk", fps=10)
        self.tick(0.2)
        self.player.animation.stop("walk")
        self.assertEqual(self.player.animation.frame, 3)
        self.assertEqual(self.showing(), BLUE)
        self.assertFalse(self.player.animation.is_playing)

    def test_a_stopped_animation_does_not_advance(self):
        self.player.animation.play("walk", fps=10)
        self.player.animation.stop("walk")
        for _ in range(10):
            self.tick(0.1)
        self.assertEqual(self.player.animation.frame, 1)

    def test_playing_after_stopping_starts_over(self):
        self.player.animation.play("walk", fps=10)
        self.tick(0.2)
        self.player.animation.stop("walk")
        self.player.animation.play("walk", fps=10)
        self.assertEqual(self.player.animation.frame, 1)

    def test_stopping_something_not_playing_warns(self):
        with self.assertWarns(TrjoLudusWarning) as caught:
            self.player.animation.stop("walk")
        self.assertIn("nothing to stop", str(caught.warning))

    def test_stopping_does_not_crash_the_game(self):
        self.quietly(self.player.animation.stop, "walk")
        self.player.animation.play("walk")     # still perfectly usable
        self.assertTrue(self.player.animation.is_playing)

    def test_stopping_one_does_not_stop_another(self):
        self.player.animation.add("idle", [self.idle])
        self.player.animation.play("walk", fps=10)
        self.quietly(self.player.animation.stop, "idle")
        self.assertTrue(self.player.animation.is_playing)
        self.assertEqual(self.player.animation.current, "walk")
        self.tick(0.1)
        self.assertEqual(self.player.animation.frame, 2)

    def test_stopping_the_wrong_one_says_which_is_playing(self):
        self.player.animation.add("idle", [self.idle])
        self.player.animation.play("walk")
        with self.assertWarns(TrjoLudusWarning) as caught:
            self.player.animation.stop("idle")
        self.assertIn("'walk' is.", str(caught.warning))

    def test_pausing_something_not_playing_warns(self):
        with self.assertWarns(TrjoLudusWarning):
            self.player.animation.pause("walk")

    def test_resuming_something_not_paused_warns(self):
        with self.assertWarns(TrjoLudusWarning) as caught:
            self.player.animation.resume("walk")
        self.assertIn("nothing to resume", str(caught.warning))

    def test_these_warnings_do_not_repeat_either(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(30):
                self.player.animation.stop("walk")
        self.assertEqual(len(caught), 1)

    def test_pause_and_resume_of_an_unknown_animation_still_raise(self):
        for call in (self.player.animation.pause,
                     self.player.animation.resume,
                     self.player.animation.stop):
            with self.subTest(call=call.__name__):
                with self.assertRaises(AnimationError):
                    call("nothing")


class TestReadableState(AnimationTestCase):
    def test_nothing_is_playing_to_begin_with(self):
        self.assertIsNone(self.player.animation.current)
        self.assertFalse(self.player.animation.is_playing)
        self.assertFalse(self.player.animation.finished)
        self.assertEqual(self.player.animation.frame, 0)

    def test_current_names_what_is_playing(self):
        self.define_walk()
        self.player.animation.play("walk")
        self.assertEqual(self.player.animation.current, "walk")
        self.assertTrue(self.player.animation.is_playing)

    def test_current_survives_a_pause(self):
        self.define_walk()
        self.player.animation.play("walk")
        self.player.animation.pause("walk")
        self.assertEqual(self.player.animation.current, "walk")
        self.assertFalse(self.player.animation.is_playing)

    def test_state_is_read_only(self):
        for name in ("current", "is_playing", "finished", "frame"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(self.player.animation, name, "nonsense")


class TestSetImage(AnimationTestCase):
    def setUp(self):
        super().setUp()
        self.define_walk()

    def test_it_changes_the_picture(self):
        self.player.set.image(self.idle)
        self.assertEqual(self.showing(), (100, 100, 100))

    def test_it_stops_a_running_animation(self):
        self.player.animation.play("walk", fps=10)
        self.quietly(self.player.set.image, self.idle)
        self.assertFalse(self.player.animation.is_playing)

    def test_the_image_change_actually_happens(self):
        self.player.animation.play("walk", fps=10)
        self.quietly(self.player.set.image, self.idle)
        self.assertEqual(self.showing(), (100, 100, 100))
        self.tick(0.5)
        self.assertEqual(self.showing(), (100, 100, 100),
                         "the animation went on overwriting the image")

    def test_it_warns_rather_than_raising(self):
        self.player.animation.play("walk")
        with self.assertWarns(TrjoLudusWarning) as caught:
            self.player.set.image(self.idle)
        message = str(caught.warning)
        self.assertIn("set.image() stopped the animation 'walk'", message)
        self.assertIn("Play it again", message)

    def test_it_does_not_warn_when_nothing_was_playing(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.player.set.image(self.idle)
        self.assertEqual(caught, [])

    def test_it_does_not_warn_every_frame(self):
        self.player.animation.play("walk")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(30):
                self.player.set.image(self.idle)
        self.assertEqual(len(caught), 1)

    def test_the_animation_can_be_played_again_afterwards(self):
        self.player.animation.play("walk", fps=10)
        self.quietly(self.player.set.image, self.idle)
        self.player.animation.play("walk", fps=10)
        self.assertEqual(self.showing(), RED)
        self.assertTrue(self.player.animation.is_playing)

    def test_a_missing_image_raises(self):
        with self.assertRaises(Exception):
            self.player.set.image(self.missing)

    def test_it_leaves_position_and_scale_alone(self):
        self.player.set.x(10.5)
        self.player.set.scale(2)
        self.player.set.image(self.idle)
        self.assertEqual(self.player.position, (10.5, 0))
        self.assertEqual(self.player.scale, 2.0)

    def test_the_assignment_form_works_too(self):
        self.player.set.image = self.idle
        self.assertEqual(self.showing(), (100, 100, 100))


class TestObjectBehaviourIsUntouched(AnimationTestCase):
    def setUp(self):
        super().setUp()
        self.define_walk()

    def test_animating_does_not_move_the_object(self):
        self.player.set.x(10.5)
        self.player.set.y(20.25)
        self.player.animation.play("walk", fps=10)
        for _ in range(6):
            self.tick(0.1)
        self.assertEqual(self.player.position, (10.5, 20.25))

    def test_animating_does_not_change_the_scale(self):
        self.player.set.scale(2.5)
        self.player.animation.play("walk", fps=10)
        for _ in range(6):
            self.tick(0.1)
        self.assertEqual(self.player.scale, 2.5)

    def test_moving_while_animating(self):
        self.player.animation.play("walk", fps=10)
        for _ in range(4):
            self.player.move.x(0.25)
            self.tick(0.1)
        self.assertEqual(self.player.x, 1.0)
        self.assertEqual(self.player.animation.frame, 1)

    def test_a_scaled_animation_draws_at_the_scaled_size(self):
        self.player.set.scale(3)
        self.player.animation.play("walk", fps=10)
        self.assertEqual(self.player.size, (12, 12))
        self.tick(0.1)
        self.assertEqual(self.player.size, (12, 12))

    def test_a_fractional_position_still_rounds_the_same_way(self):
        self.player.set.x(10.6)
        self.player.animation.play("walk", fps=10)
        buffer = Framebuffer(40, 20)
        buffer.clear()
        obj = current_scene().require("player")
        buffer.draw_image(obj.image, obj.x, obj.y, obj.scale)
        lit = [x for x in range(40)
               if tuple(reversed(buffer.pixels[x * 4:x * 4 + 3]))
               != DEFAULT_CLEAR_COLOUR]
        self.assertEqual(min(lit), 11)

    def test_an_invisible_object_still_animates(self):
        self.player.visible = False
        self.player.animation.play("walk", fps=10)
        self.tick(0.1)
        self.assertEqual(self.player.animation.frame, 2)


class TestHandles(AnimationTestCase):
    def test_a_direct_handle_works_the_same(self):
        GameObject("player").animation.add("walk", self.walk)
        GameObject("player").animation.play("walk", fps=10)
        self.assertTrue(GameObject("player").animation.is_playing)

    def test_two_handles_share_one_animator(self):
        self.define_walk()
        first = GameObject("player")
        second = GameObject("player")
        first.animation.play("walk", fps=10)
        self.assertEqual(second.animation.current, "walk")
        self.tick(0.1)
        self.assertEqual(second.animation.frame, 2)

    def test_stopping_through_another_handle(self):
        self.define_walk()
        self.player.animation.play("walk", fps=10)
        GameObject("player").animation.stop("walk")
        self.assertFalse(self.player.animation.is_playing)

    def test_animations_belong_to_the_object_not_the_handle(self):
        GameObject("player").animation.add("walk", self.walk)
        self.assertEqual(self.player.animation.names, ("walk",))

    def test_a_destroyed_object_refuses_every_animation_call(self):
        self.define_walk()
        held = GameObject("player")
        held.destroy()
        with self.assertRaises(SceneError):
            held.animation.play("walk")
        with self.assertRaises(SceneError):
            held.animation.add("other", self.walk)
        with self.assertRaises(SceneError):
            held.animation.current
        with self.assertRaises(SceneError):
            held.animation.is_playing
        with self.assertRaises(SceneError):
            held.animation.stop("walk")

    def test_two_objects_animate_independently(self):
        second = create.image(0, 0, self.idle, "enemy")
        self.define_walk()
        second.animation.add("walk", list(reversed(self.walk)))
        self.player.animation.play("walk", fps=10)
        second.animation.play("walk", fps=20)
        self.tick(0.05)
        self.assertEqual(self.player.animation.frame, 1)
        self.assertEqual(second.animation.frame, 2)


class TestThroughARealRun(AnimationTestCase):
    """Animation, movement, input and drawing all going on at once.

    An unpaced null-backend frame takes a few microseconds, so these play at
    an absurd frames-per-second to make the animation move within a run that
    lasts under a millisecond. What is being checked is that the loop drives
    animation at all, and alongside everything else -- the timing itself is
    checked exactly elsewhere, by handing the scene known numbers of seconds.
    """

    #: Fast enough that a few microseconds is several animation frames.
    FAST = 100_000

    def play(self, game, frames=None, max_fps=None):
        backend = NullBackend()
        Application(game, size=(40, 40), max_fps=max_fps,
                    backend=backend).run()
        return backend

    def test_the_loop_advances_the_animation(self):
        walk = self.walk
        seen = []

        class G(Game):
            count = 0

            def on_start(self):
                player = GameObject("player")
                player.animation.add("walk", walk)
                player.animation.play("walk", fps=TestThroughARealRun.FAST)

            def on_update(self, dt):
                self.count += 1
                seen.append(GameObject("player").animation.frame)
                if self.count >= 200:
                    self.quit()

        self.play(G())
        self.assertGreater(len(set(seen)), 1,
                           "the animation never advanced in a real run")

    def test_movement_and_animation_together(self):
        walk = self.walk
        result = {}

        class G(Game):
            count = 0

            def on_start(self):
                player = GameObject("player")
                player.animation.add("walk", walk)
                player.animation.play("walk", fps=TestThroughARealRun.FAST,
                                      loop=True)

            def on_update(self, dt):
                self.count += 1
                player = GameObject("player")
                player.move.x(0.5)
                if self.count >= 20:
                    result["x"] = player.x
                    result["playing"] = player.animation.is_playing
                    self.quit()

        self.play(G())
        self.assertEqual(result["x"], 10.0)
        self.assertTrue(result["playing"])

    def test_playing_every_update_keeps_it_progressing(self):
        """The documented pattern: play() called from on_update every frame."""
        walk = self.walk
        frames = []

        class G(Game):
            count = 0

            def on_start(self):
                GameObject("player").animation.add("walk", walk)

            def on_update(self, dt):
                self.count += 1
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", TrjoLudusWarning)
                    GameObject("player").animation.play(
                        "walk", fps=TestThroughARealRun.FAST)
                frames.append(GameObject("player").animation.frame)
                if self.count >= 200:
                    self.quit()

        self.play(G())
        self.assertGreater(len(set(frames)), 1,
                           "play() every frame froze the animation")

    def test_the_animated_frame_reaches_the_screen(self):
        walk = self.walk
        backend = NullBackend()
        seen = []

        class G(Game):
            count = 0

            def on_start(self):
                player = GameObject("player")
                player.animation.add("walk", walk)
                player.animation.play("walk", fps=TestThroughARealRun.FAST)

            def on_update(self, dt):
                self.count += 1
                frame = backend.windows[0].last_frame
                if frame:
                    blue, green, red, _ = frame[0:4]
                    seen.append((red, green, blue))
                if self.count >= 200:
                    self.quit()

        Application(G(), size=(40, 40), max_fps=None, backend=backend).run()
        self.assertGreater(len(set(seen)), 1,
                           "the drawn pixels never changed")
        self.assertTrue(set(seen) <= set(COLOURS), set(seen))

    def test_a_second_run_starts_from_a_clean_scene(self):
        walk = self.walk
        counts = []

        class G(Game):
            def on_start(self):
                player = create.image(0, 0, walk[0], "runner")
                player.animation.add("walk", walk)
                player.animation.play("walk")
                counts.append(player.animation.names)

            def on_update(self, dt):
                self.quit()

        game = G()
        self.play(game)
        self.play(game)
        self.assertEqual(counts, [("walk",), ("walk",)])


if __name__ == "__main__":
    unittest.main()
