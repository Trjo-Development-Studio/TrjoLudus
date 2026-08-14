"""Tests for the decoded-image cache.

A game asks for the same file repeatedly as a matter of course: an animation
is a list of paths, and switching a picture back and forth asks for each again.
Decoding a PNG is the most expensive thing a game does that it does not have
to do twice.

These check that it is decoded once per run, that the same image comes back,
and that a run does not inherit what the last one loaded.
"""

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from trjoludus import Game, GameObject, create, engine
from trjoludus.app import Application
from trjoludus.image import Image, ImageError, load_image, loaded_images
from trjoludus.platform.null import NullBackend
from trjoludus.scene import current_scene
from trjoludus.ui import current_ui


def write_png(path, colour=(250, 0, 0), size=4):
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


class CacheTestCase(unittest.TestCase):
    def setUp(self):
        engine.end_run()
        self.addCleanup(engine.end_run)
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.folder = Path(self._folder.name)
        self.red = write_png(self.folder / "red.png", (250, 0, 0))
        self.green = write_png(self.folder / "green.png", (0, 250, 0))
        self.frames = [write_png(self.folder / f"walk{n}.png", (n * 40, 0, 0))
                       for n in range(4)]

    def resources(self):
        return engine.current().resources


class TestItDecodesOnce(CacheTestCase):
    def test_the_same_path_gives_the_same_image(self):
        first = load_image(self.red)
        second = load_image(self.red)
        self.assertIs(first, second)

    def test_different_paths_give_different_images(self):
        self.assertIsNot(load_image(self.red), load_image(self.green))

    def test_the_image_is_kept_by_the_run(self):
        load_image(self.red)
        self.assertEqual(loaded_images(), 1)
        load_image(self.red)
        self.assertEqual(loaded_images(), 1)

    def test_different_spellings_are_one_image(self):
        """Several names for a file, one decode.

        They occupy several keys -- each spelling remembered so that asking
        again is a dictionary lookup -- but they are the same image.
        """
        import os

        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.folder)
        first = load_image("red.png")
        second = load_image("./red.png")
        third = load_image(self.red)
        self.assertIs(first, second)
        self.assertIs(first, third)
        self.assertEqual(loaded_images(), 1)

    def test_a_symlink_is_the_same_image(self):
        """Resolution still happens, just only when a spelling is new."""
        import os

        link = self.folder / "alias.png"
        try:
            os.symlink(self.red, link)
        except (OSError, NotImplementedError):   # pragma: no cover
            self.skipTest("this filesystem has no symlinks")
        self.assertIs(load_image(self.red), load_image(link))
        self.assertEqual(loaded_images(), 1)

    def test_a_repeated_load_touches_no_filesystem(self):
        """The point of the fix: a hit is a lookup and nothing else."""
        import pathlib as _pathlib

        load_image(self.red)
        calls = []
        real = _pathlib.Path.resolve

        def counting(self, *args, **kwargs):
            calls.append(1)
            return real(self, *args, **kwargs)

        _pathlib.Path.resolve = counting
        self.addCleanup(setattr, _pathlib.Path, "resolve", real)
        for _ in range(20):
            load_image(self.red)
        self.assertEqual(calls, [], "a cache hit resolved the path")

    def test_a_new_spelling_still_resolves_once(self):
        import os
        import pathlib as _pathlib

        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.folder)
        load_image(self.red)

        calls = []
        real = _pathlib.Path.resolve

        def counting(self, *args, **kwargs):
            calls.append(1)
            return real(self, *args, **kwargs)

        _pathlib.Path.resolve = counting
        self.addCleanup(setattr, _pathlib.Path, "resolve", real)
        load_image("red.png")
        self.assertEqual(len(calls), 1, "a new spelling must resolve once")
        load_image("red.png")
        self.assertEqual(len(calls), 1, "and only once")

    def test_distinct_files_stay_distinct(self):
        self.assertIsNot(load_image(self.red), load_image(self.green))
        self.assertEqual(loaded_images(), 2)

    def test_creating_an_object_and_switching_to_it_decodes_once(self):
        create.image(0, 0, self.red, "player")
        GameObject("player").set.image(self.red)
        GameObject("player").set.image(self.green)
        GameObject("player").set.image(self.red)
        self.assertEqual(loaded_images(), 2)

    def test_an_animation_reuses_what_is_already_loaded(self):
        create.image(0, 0, self.frames[0], "player")
        GameObject("player").animation.add("walk", self.frames)
        # Four frames, the first of which was already the object's picture.
        self.assertEqual(loaded_images(), 4)

    def test_two_animations_sharing_frames_decode_them_once(self):
        create.image(0, 0, self.red, "player")
        player = GameObject("player")
        player.animation.add("walk", self.frames)
        player.animation.add("run", self.frames)
        self.assertEqual(loaded_images(), 5)

    def test_two_objects_can_share_one_image(self):
        create.image(0, 0, self.red, "a")
        create.image(0, 0, self.red, "b")
        self.assertIs(current_scene().require("a").image,
                      current_scene().require("b").image)
        self.assertEqual(loaded_images(), 1)

    def test_the_image_is_the_same_object_the_animation_holds(self):
        create.image(0, 0, self.frames[0], "player")
        GameObject("player").animation.add("walk", self.frames)
        self.assertIs(current_scene().require("player").image,
                      load_image(self.frames[0]))


class TestSemanticsAreUnchanged(CacheTestCase):
    def test_a_shared_image_is_still_an_image(self):
        loaded = load_image(self.red)
        self.assertIsInstance(loaded, Image)
        self.assertEqual(loaded.size, (4, 4))
        self.assertIsInstance(loaded.pixels, bytes)
        self.assertTrue(loaded.is_opaque)

    def test_images_cannot_be_changed_so_sharing_is_safe(self):
        loaded = load_image(self.red)
        for name in ("width", "height", "pixels", "is_opaque", "size"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(loaded, name, None)

    def test_a_missing_file_still_says_so(self):
        with self.assertRaises(ImageError) as caught:
            load_image(self.folder / "nowhere.png")
        self.assertIn("No such image file", str(caught.exception))

    def test_a_failure_is_not_cached(self):
        missing = self.folder / "later.png"
        with self.assertRaises(ImageError):
            load_image(missing)
        self.assertEqual(len(self.resources()), 0)
        # And it works once the file appears.
        write_png(missing)
        self.assertIsInstance(load_image(missing), Image)

    def test_a_broken_file_still_names_the_file(self):
        broken = self.folder / "broken.png"
        broken.write_bytes(b"not a png at all")
        with self.assertRaises(ImageError) as caught:
            load_image(broken)
        self.assertIn("broken.png", str(caught.exception))
        self.assertEqual(len(self.resources()), 0)


class TestLifetime(CacheTestCase):
    def play(self, game):
        Application(game, size=(20, 20), max_fps=None,
                    backend=NullBackend()).run()

    def test_images_are_available_during_a_run(self):
        seen = []
        red = self.red

        class G(Game):
            def on_start(self):
                create.image(0, 0, red, "player")
                seen.append(len(engine.current().resources))

            def on_update(self, dt):
                self.quit()

        self.play(G())
        self.assertEqual(seen, [1])

    def test_a_run_releases_what_it_loaded(self):
        red = self.red

        class G(Game):
            def on_start(self):
                create.image(0, 0, red, "player")

            def on_update(self, dt):
                self.quit()

        self.play(G())
        self.assertEqual(len(self.resources()), 0)

    def test_a_second_run_does_not_inherit_them(self):
        counts = []
        red = self.red

        class G(Game):
            def on_start(self):
                counts.append(len(engine.current().resources))
                create.image(0, 0, red, "player")

            def on_update(self, dt):
                self.quit()

        game = G()
        self.play(game)
        self.play(game)
        self.assertEqual(counts, [0, 0])

    def test_a_run_that_raised_still_releases_them(self):
        red = self.red

        class Breaking(Game):
            def on_start(self):
                create.image(0, 0, red, "player")

            def on_update(self, dt):
                raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            self.play(Breaking())
        self.assertEqual(len(self.resources()), 0)

    def test_it_is_not_a_process_wide_cache(self):
        load_image(self.red)
        self.assertEqual(len(self.resources()), 1)
        engine.end_run()
        self.assertEqual(len(self.resources()), 0)

    def test_backend_configuration_outlives_the_cache(self):
        from trjoludus import image as image_module
        from trjoludus.native import PYTHON, registry

        image_module.engine = PYTHON
        self.addCleanup(registry.reset)
        load_image(self.red)
        engine.end_run()
        self.assertEqual(image_module.engine, PYTHON)

    def test_the_cache_is_part_of_the_engine_state(self):
        self.assertIn("resources", engine.EngineState.__slots__)
        self.assertIs(self.resources(), engine.current().resources)

    def test_there_is_no_second_cache_anywhere(self):
        """One place decoded images live."""
        import ast
        import pathlib

        root = pathlib.Path(engine.__file__).parent
        suspicious = []
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if path.name in ("engine.py", "image.py"):
                continue
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Attribute) and node.attr in (
                        "_image_cache", "_images", "_decoded"):
                    suspicious.append(path.name)
        self.assertEqual(suspicious, [])


class TestExplicitRustWithoutALibrary(CacheTestCase):
    """What `image.engine = "rust"` does when there is nothing to run.

    The audit found this had no test of its own: the backend tests covered it
    generically and for rendering, but the one subsystem this milestone
    migrated was checked only by hand.
    """

    def setUp(self):
        super().setUp()
        from trjoludus.native import imaging, library, registry

        self._library = library._library
        self._problem = library._problem
        library._library = None
        library._problem = "no native library found (test)"
        imaging.forget()
        registry.reset()

        def restore():
            library._library = self._library
            library._problem = self._problem
            imaging.forget()
            registry.reset()

        self.addCleanup(restore)

    def test_loading_an_image_says_the_native_one_is_missing(self):
        from trjoludus import image as image_module
        from trjoludus.native import EngineError

        image_module.engine = "rust"
        with self.assertRaises(EngineError) as caught:
            load_image(self.red)
        message = str(caught.exception)
        self.assertIn("image.engine is 'rust'", message)
        self.assertIn("no native implementation of image", message)

    def test_the_message_says_what_to_do_about_it(self):
        from trjoludus import image as image_module
        from trjoludus.native import EngineError

        image_module.engine = "rust"
        with self.assertRaises(EngineError) as caught:
            load_image(self.red)
        self.assertIn("'auto'", str(caught.exception))

    def test_building_an_image_says_so_too(self):
        """Opacity is image processing, so it uses the image backend."""
        from trjoludus import image as image_module
        from trjoludus.native import EngineError

        image_module.engine = "rust"
        with self.assertRaises(EngineError):
            Image(1, 1, bytes([1, 2, 3, 255]))

    def test_python_still_works_with_no_library(self):
        from trjoludus import image as image_module

        image_module.engine = "python"
        loaded = load_image(self.red)
        self.assertEqual(loaded.size, (4, 4))
        self.assertTrue(loaded.is_opaque)

    def test_auto_still_works_with_no_library(self):
        from trjoludus import image as image_module

        image_module.engine = "auto"
        self.assertEqual(load_image(self.red).size, (4, 4))

    def test_nothing_was_cached_by_the_failure(self):
        from trjoludus import image as image_module
        from trjoludus.native import EngineError

        image_module.engine = "rust"
        with self.assertRaises(EngineError):
            load_image(self.red)
        self.assertEqual(loaded_images(), 0)


class TestBothBackendsUseTheCache(CacheTestCase):
    def test_the_cache_works_whichever_backend_decodes(self):
        from trjoludus import image as image_module
        from trjoludus.native import registry

        self.addCleanup(registry.reset)
        for engine_name in ("python", "rust"):
            with self.subTest(engine=engine_name):
                engine.end_run()
                try:
                    image_module.engine = engine_name
                    registry.system("image").resolve()
                except Exception:
                    self.skipTest(f"{engine_name} backend unavailable")
                first = load_image(self.red)
                self.assertIs(first, load_image(self.red))
                self.assertEqual(len(self.resources()), 1)

    def test_both_backends_decode_the_same_image(self):
        from trjoludus import image as image_module
        from trjoludus.native import registry

        self.addCleanup(registry.reset)
        results = {}
        for engine_name in ("python", "rust"):
            engine.end_run()
            try:
                image_module.engine = engine_name
                registry.system("image").resolve()
            except Exception:
                self.skipTest(f"{engine_name} backend unavailable")
            loaded = load_image(self.red)
            results[engine_name] = (loaded.size, loaded.pixels,
                                    loaded.is_opaque)
        self.assertEqual(results["python"], results["rust"])


if __name__ == "__main__":
    unittest.main()
