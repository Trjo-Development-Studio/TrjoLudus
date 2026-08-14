"""The engine drawn through both renderers, from a game's point of view.

The differential tests next door compare the two renderers directly. These go
through everything above them -- the scene, drawing lists, animation, the
frame the backend is handed -- and check that a whole game frame comes out the
same either way.

That is the promise of this milestone: the same TrjoLudus, whichever renderer
is underneath.
"""

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from trjoludus import Game, GameObject, color, create, draw
from trjoludus.app import Application
from trjoludus.native import PYTHON, RUST, EngineError, library, registry
from trjoludus.native import renderer as native_renderer
from trjoludus.platform.null import NullBackend
from trjoludus.scene import current_scene
from trjoludus.ui import current_ui
from trjoludus import rendering

COLOURS = [(250, 0, 0), (0, 250, 0), (0, 0, 250), (250, 250, 0)]


def write_png(path, colour, size=8):
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


class BothRenderers(unittest.TestCase):
    """Runs a whole game twice and compares the frames it presented."""

    SIZE = (60, 40)

    @classmethod
    def setUpClass(cls):
        cls._folder = tempfile.TemporaryDirectory()
        folder = Path(cls._folder.name)
        cls.frames = [write_png(folder / f"f{n}.png", COLOURS[n])
                      for n in range(4)]
        cls.sprite = cls.frames[0]

    @classmethod
    def tearDownClass(cls):
        cls._folder.cleanup()

    def setUp(self):
        registry.reset()
        library.forget()
        native_renderer.forget()
        current_scene().clear()
        current_ui().clear()
        self.addCleanup(registry.reset)
        self.addCleanup(current_scene().clear)
        self.addCleanup(current_ui().clear)

    def native_available(self):
        return native_renderer.available()

    def play(self, build, act=None, frames=3, engine=PYTHON):
        """Run a game on one renderer, returning every presented frame."""
        registry.reset()
        rendering.engine = engine
        current_scene().clear()
        current_ui().clear()

        backend = NullBackend()
        presented = []

        class G(Game):
            count = 0

            def on_start(self):
                build()

            def on_update(self, dt):
                if act is not None:
                    act(self.count)
                self.count += 1
                if self.count >= frames:
                    self.quit()

            def on_stop(self):
                presented.append(bytes(backend.windows[0].last_frame))

        Application(G(), size=self.SIZE, max_fps=None, backend=backend).run()
        return presented[0]

    def assertSameFrame(self, build, act=None, frames=3):
        """The same game on each renderer must present the same bytes."""
        if not self.native_available():
            self.skipTest("no native renderer built here")

        by_python = self.play(build, act, frames, engine=PYTHON)
        by_rust = self.play(build, act, frames, engine=RUST)
        self.assertEqual(len(by_python), len(by_rust))
        if by_python == by_rust:
            return

        width = self.SIZE[0]
        for index in range(0, len(by_python), 4):
            if by_python[index:index + 4] != by_rust[index:index + 4]:
                pixel = index // 4
                self.fail(
                    f"pixel ({pixel % width}, {pixel // width}) differs: "
                    f"Python {tuple(by_python[index:index + 4])}, "
                    f"Rust {tuple(by_rust[index:index + 4])} (BGRA)"
                )


class TestGameObjects(BothRenderers):
    def test_one_object(self):
        self.assertSameFrame(
            lambda: create.image(10, 10, self.sprite, "player"))

    def test_a_fractional_position(self):
        def build():
            create.image(10.6, 5.4, self.sprite, "player")

        self.assertSameFrame(build)

    def test_movement_by_fractions(self):
        def build():
            create.image(0, 10, self.sprite, "player")

        def act(count):
            GameObject("player").move.x(1 / 3)

        self.assertSameFrame(build, act, frames=7)

    def test_scaling(self):
        for scale in (0.5, 1.0, 1.5, 2.0, 3.0):
            with self.subTest(scale=scale):
                def build(s=scale):
                    create.image(4, 4, self.sprite, "player")
                    GameObject("player").set.scale(s)

                self.assertSameFrame(build)

    def test_several_objects_in_order(self):
        def build():
            for index in range(4):
                create.image(index * 5, index * 4, self.frames[index],
                             f"thing{index}")

        self.assertSameFrame(build)

    def test_an_invisible_object(self):
        def build():
            create.image(5, 5, self.sprite, "player")
            create.image(10, 10, self.frames[1], "hidden")
            GameObject("hidden").visible = False

        self.assertSameFrame(build)

    def test_an_object_off_the_edge(self):
        def build():
            create.image(-4, -4, self.sprite, "corner")
            create.image(56, 36, self.frames[1], "other")

        self.assertSameFrame(build)


class TestDrawings(BothRenderers):
    def test_rectangles(self):
        def build():
            menu = draw.list("menu")
            menu.rect(2, 2, 20, 10, color.blue)
            menu.rect(10, 6, 20, 10, color.red)

        self.assertSameFrame(build)

    def test_lines(self):
        def build():
            menu = draw.list("menu")
            menu.line(0, 0, 59, 39, color.green)
            menu.line(0, 39, 59, 0, color.yellow)

        self.assertSameFrame(build)

    def test_text(self):
        def build():
            draw.list("menu").text(2, 2, "Score: 100", color.white)

        self.assertSameFrame(build)

    def test_scaled_text(self):
        def build():
            draw.list("menu").text(2, 2, "big", color.white).set.scale(3)

        self.assertSameFrame(build)

    def test_scaled_rectangles(self):
        def build():
            draw.list("menu").rect(3, 3, 8, 5, color.blue).set.scale(2.5)

        self.assertSameFrame(build)

    def test_a_whole_interface(self):
        def build():
            hud = draw.list("hud")
            hud.rect(0, 0, 60, 8, color.blue)
            hud.text(1, 1, "HUD", color.white)
            hud.line(0, 9, 59, 9, color.gray)
            hud.rect(20, 15, 20, 12, color.red)
            hud.text(22, 19, "PLAY", color.white)

        self.assertSameFrame(build)

    def test_a_hidden_list(self):
        def build():
            draw.list("shown").rect(2, 2, 10, 10, color.blue)
            draw.list("hidden").rect(5, 5, 10, 10, color.red).list.hide()

        self.assertSameFrame(build)

    def test_drawings_changed_during_the_run(self):
        def build():
            menu = draw.list("menu")
            menu.text(2, 2, "start", color.white)
            menu.rect(2, 12, 10, 6, color.blue)

        def act(count):
            menu = current_ui().require("menu")
            label, box = menu.drawings()
            label.set.text(f"frame {count}")
            label.set.color((100 + count * 20, 50, 200))
            box.move.x(2.5)
            box.set.scale(1 + count * 0.25)

        self.assertSameFrame(build, act, frames=5)


class TestObjectsAndDrawingsTogether(BothRenderers):
    def test_the_ui_is_drawn_over_the_scene(self):
        def build():
            create.image(5, 5, self.sprite, "player")
            draw.list("hud").rect(0, 0, 60, 12, color.blue)

        self.assertSameFrame(build)

    def test_a_busy_frame(self):
        def build():
            for index in range(4):
                create.image(index * 9 + 0.5, index * 6, self.frames[index],
                             f"thing{index}")
            GameObject("thing1").set.scale(2)
            hud = draw.list("hud")
            hud.rect(0, 30, 60, 10, color.blue)
            hud.text(2, 32, "score 42", color.white)
            hud.line(0, 29, 59, 29, color.yellow)

        self.assertSameFrame(build)


class TestAnimation(BothRenderers):
    """Both renderers must draw the frame the Animator is on.

    The animation is advanced by an exact number of seconds and then stopped,
    so both runs render a known picture. Leaving it playing would compare the
    two runs' *timing*: an animation advances on how long each frame took, the
    two renderers do not take the same time, and after a few frames they can
    honestly be on different pictures. That is not a rendering difference, and
    an earlier version of this test failed on it about one run in four.

    What the renderer owes is to draw whatever the Animator chose. That is
    what this checks.
    """

    def settled_on(self, frame_wanted, scale=None):
        """Build a scene whose animation has stopped on a chosen frame."""
        def build():
            create.image(6, 6, self.frames[0], "player")
            player = GameObject("player")
            if scale is not None:
                player.set.scale(scale)
            player.animation.add("walk", self.frames)
            player.animation.play("walk", fps=10, loop=True)
            # Exactly (frame_wanted - 1) frames on, at a tenth of a second
            # each, then stopped so the loop's own advance changes nothing.
            current_scene().advance_animations(0.1 * (frame_wanted - 1))
            player.animation.stop("walk")

        return build

    def test_it_settles_where_it_should(self):
        """Otherwise the tests below could agree on the wrong picture."""
        registry.reset()
        current_scene().clear()
        self.settled_on(3)()
        player = GameObject("player")
        self.assertEqual(player.animation.frame, 3)
        self.assertFalse(player.animation.is_playing)

    def test_an_animation_renders_the_same(self):
        for frame in (1, 2, 3, 4):
            with self.subTest(frame=frame):
                self.assertSameFrame(self.settled_on(frame))

    def test_a_scaled_animation(self):
        for frame in (1, 3):
            with self.subTest(frame=frame):
                self.assertSameFrame(self.settled_on(frame, scale=2))

    def test_a_playing_animation_still_reaches_both_renderers(self):
        """Left playing, both must draw *some* frame of it, not nothing."""
        if not self.native_available():
            self.skipTest("no native renderer built here")

        drawn = {}
        for engine in (PYTHON, RUST):
            registry.reset()
            rendering.engine = engine
            current_scene().clear()
            current_ui().clear()
            backend = NullBackend()
            frames = self.frames

            class G(Game):
                count = 0

                def on_start(self):
                    create.image(0, 0, frames[0], "player")
                    GameObject("player").animation.add("walk", frames)
                    GameObject("player").animation.play("walk", fps=1000)

                def on_update(self, dt):
                    self.count += 1
                    if self.count >= 20:
                        self.quit()

                def on_stop(self):
                    frame = backend.windows[0].last_frame
                    drawn[engine] = (frame[2], frame[1], frame[0])

            Application(G(), size=self.SIZE, max_fps=None,
                        backend=backend).run()

        # Which frame each landed on depends on how fast it ran, which is not
        # the renderer's business. That each drew a real frame of the
        # animation is.
        for engine, colour in drawn.items():
            with self.subTest(engine=engine):
                self.assertIn(colour, COLOURS)


class TestBackendSelection(BothRenderers):
    def test_python_works_without_any_library(self):
        library._library = None
        library._problem = "no native library found (test)"
        native_renderer.forget()

        rendering.engine = PYTHON
        frame = self.play(lambda: draw.list("m").rect(1, 1, 4, 4, color.red),
                          engine=PYTHON)
        self.assertTrue(frame)

    def test_rust_refuses_without_a_library(self):
        library._library = None
        library._problem = "no native library found (test)"
        native_renderer.forget()

        rendering.engine = RUST
        with self.assertRaises(EngineError) as caught:
            rendering.create_framebuffer(10, 10)
        self.assertIn("no native implementation", str(caught.exception))

    def test_auto_falls_back_without_a_library(self):
        library._library = None
        library._problem = "no native library found (test)"
        native_renderer.forget()

        from trjoludus.rendering_python import Framebuffer

        self.assertIsInstance(rendering.create_framebuffer(10, 10),
                              Framebuffer)

    def test_auto_takes_rust_when_it_is_there(self):
        if not self.native_available():
            self.skipTest("no native renderer built here")
        self.assertIsInstance(rendering.create_framebuffer(10, 10),
                              native_renderer.NativeFramebuffer)

    def test_python_is_honoured_even_when_rust_is_there(self):
        if not self.native_available():
            self.skipTest("no native renderer built here")
        from trjoludus.rendering_python import Framebuffer

        rendering.engine = PYTHON
        self.assertIsInstance(rendering.create_framebuffer(10, 10),
                              Framebuffer)

    def test_rust_is_used_when_asked_for(self):
        if not self.native_available():
            self.skipTest("no native renderer built here")
        rendering.engine = RUST
        self.assertIsInstance(rendering.create_framebuffer(10, 10),
                              native_renderer.NativeFramebuffer)

    def test_a_game_runs_on_each(self):
        if not self.native_available():
            self.skipTest("no native renderer built here")
        for engine in (PYTHON, RUST):
            with self.subTest(engine=engine):
                frame = self.play(
                    lambda: draw.list("m").rect(1, 1, 4, 4, color.red),
                    engine=engine)
                self.assertEqual(len(frame), 60 * 40 * 4)

    def test_the_choice_is_made_once_per_run(self):
        """Not per frame: a run cannot be half on one renderer."""
        if not self.native_available():
            self.skipTest("no native renderer built here")

        kinds = []
        rendering.engine = RUST
        backend = NullBackend()

        class G(Game):
            count = 0

            def on_update(self, dt):
                from trjoludus.app import current_application

                kinds.append(type(current_application()._framebuffer).__name__)
                self.count += 1
                if self.count >= 3:
                    self.quit()

        Application(G(), size=(20, 20), max_fps=None, backend=backend).run()
        self.assertEqual(set(kinds), {"NativeFramebuffer"})


class TestHitTestingIsUnaffected(BothRenderers):
    """Where a drawing is clickable must not depend on who drew it."""

    def test_bounds_are_the_same_on_both(self):
        if not self.native_available():
            self.skipTest("no native renderer built here")

        found = {}
        for engine in (PYTHON, RUST):
            registry.reset()
            rendering.engine = engine
            current_ui().clear()
            backend = NullBackend()

            class G(Game):
                def on_start(self):
                    self.box = draw.list("menu").rect(10.6, 5.4, 12, 8,
                                                      color.blue)
                    self.box.set.scale(1.5)

                def on_update(self, dt):
                    found[engine] = (self.box.bounds,
                                     self.box.screen_position)
                    self.quit()

            Application(G(), size=self.SIZE, max_fps=None,
                        backend=backend).run()

        self.assertEqual(found[PYTHON], found[RUST])

    def test_what_is_drawn_matches_the_hitbox_on_rust(self):
        if not self.native_available():
            self.skipTest("no native renderer built here")

        registry.reset()
        rendering.engine = RUST
        current_ui().clear()
        backend = NullBackend()
        result = {}

        class G(Game):
            def on_start(self):
                self.box = draw.list("menu").rect(10.6, 5.4, 12, 8,
                                                  color.red)

            def on_update(self, dt):
                result["bounds"] = self.box.bounds
                self.quit()

            def on_stop(self):
                result["frame"] = bytes(backend.windows[0].last_frame)

        Application(G(), size=self.SIZE, max_fps=None, backend=backend).run()

        left, top, right, bottom = result["bounds"]
        frame, width = result["frame"], self.SIZE[0]

        def pixel(x, y):
            index = (y * width + x) * 4
            return (frame[index + 2], frame[index + 1], frame[index])

        self.assertEqual(pixel(left, top), (250, 0, 0))
        self.assertEqual(pixel(right - 1, bottom - 1), (250, 0, 0))
        self.assertNotEqual(pixel(right, bottom), (250, 0, 0))


if __name__ == "__main__":
    unittest.main()
