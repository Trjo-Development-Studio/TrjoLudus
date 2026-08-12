"""The public API, used the way a game is meant to use it.

Games import the names they need and call them unprefixed::

    from trjoludus import Game, GameObject, create, input, key, keyboard, run

These tests exist so that stays true: every documented name must be importable
straight from the package, and the canonical example must work when written
that way.

``import trjoludus`` alone cannot bind those names -- an import statement binds
exactly the module name -- so the package keeps a curated ``__all__`` and this
file checks it rather than any import-time magic.
"""

import subprocess
import sys
import unittest
from pathlib import Path

import trjoludus

#: Everything a game is expected to reach without touching a private module.
PUBLIC_NAMES = (
    "Game",
    "GameObject",
    "Application",
    "run",
    "create",
    "keyboard",
    "input",
    "key",
    "Event",
    "KeyPressed",
    "WindowCloseRequested",
    "WindowResized",
    "TrjoLudusError",
    "PlatformError",
    "UnsupportedPlatformError",
    "ImageError",
    "SceneError",
    "PlatformName",
    "detect_platform",
)


class TestPublicNames(unittest.TestCase):
    def test_every_public_name_is_importable_from_the_package(self):
        for name in PUBLIC_NAMES:
            with self.subTest(name=name):
                self.assertTrue(hasattr(trjoludus, name))

    def test_every_public_name_is_declared_in_all(self):
        for name in PUBLIC_NAMES:
            with self.subTest(name=name):
                self.assertIn(name, trjoludus.__all__)

    def test_all_declares_nothing_that_does_not_exist(self):
        for name in trjoludus.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(trjoludus, name))

    def test_from_import_binds_the_names_directly(self):
        """The documented style: no prefix on every call."""
        from trjoludus import (  # noqa: F401
            Game,
            GameObject,
            create,
            input,
            key,
            keyboard,
            run,
        )

        self.assertIs(Game, trjoludus.Game)
        self.assertIs(create, trjoludus.create)
        self.assertIs(keyboard, trjoludus.keyboard)
        self.assertIs(input, trjoludus.input)
        self.assertIs(key, trjoludus.key)

    def test_input_key_is_the_live_key(self):
        from trjoludus import input, key

        self.assertIs(input.key, key)

    def test_no_private_modules_are_exported(self):
        for name in trjoludus.__all__:
            with self.subTest(name=name):
                self.assertFalse(name.startswith("_") and name != "__version__")

    def test_the_platform_layer_is_not_part_of_the_public_api(self):
        """A game never needs a backend; selection is the engine's job."""
        for name in ("X11Backend", "Win32Backend", "NullBackend",
                     "create_backend", "PlatformBackend", "PlatformWindow"):
            with self.subTest(name=name):
                self.assertNotIn(name, trjoludus.__all__)

    def test_internal_helpers_are_not_exported(self):
        for name in ("Scene", "SceneObject", "Movement", "Framebuffer",
                     "Image", "Clock", "current_scene", "current_application"):
            with self.subTest(name=name):
                self.assertNotIn(name, trjoludus.__all__)


class TestCanonicalGame(unittest.TestCase):
    """The documented example, run for real on the null backend."""

    def test_a_game_written_in_the_documented_style_runs(self):
        from trjoludus import Game, GameObject, create, input, key, keyboard
        from trjoludus.app import Application
        from trjoludus.events import KeyPressed
        from trjoludus.platform.null import NullBackend
        from trjoludus.scene import current_scene

        self.addCleanup(current_scene().clear)
        sprite = _sprite(self)

        class Backend(NullBackend):
            def create_window(self, title, width, height):
                window = super().create_window(title, width, height)
                window.simulate_event(KeyPressed("W"))
                return window

        class MyGame(Game):
            seen = None
            ended = None

            def on_start(self):
                create.image(100, 100, sprite, "player")
                self.player = GameObject("player")

            def on_update(self, dt):
                keyboard.wait(input.key)
                self.seen = str(key)
                if key == "W":
                    self.player.move.y(-50)
                self.ended = self.player.position
                self.player.destroy()
                self.quit()

        game = MyGame()
        Application(game, size=(8, 8), max_fps=None, backend=Backend()).run()

        self.assertEqual(game.seen, "W")
        self.assertEqual(game.ended, (100, 50))

    def test_the_documented_style_needs_no_prefix_anywhere(self):
        """Checked in a fresh interpreter, so nothing is already imported."""
        script = (
            "from trjoludus import Game, GameObject, create, input, key, "
            "keyboard, run\n"
            "assert input.key is key\n"
            "assert callable(keyboard.wait)\n"
            "assert callable(create.image)\n"
            "assert hasattr(GameObject, 'move')\n"
            "assert hasattr(GameObject, 'destroy')\n"
            "print('ok')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": str(Path(trjoludus.__file__).parent.parent),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


class TestExamplesUseTheDocumentedStyle(unittest.TestCase):
    """The examples are what a beginner copies, so they must not teach a prefix."""

    def example_files(self):
        root = Path(trjoludus.__file__).resolve().parent.parent / "examples"
        return sorted(root.glob("*.py"))

    def test_there_are_examples_to_check(self):
        self.assertGreater(len(self.example_files()), 0)

    def test_no_example_imports_the_package_under_an_alias(self):
        for path in self.example_files():
            with self.subTest(example=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("import trjoludus as", source)

    def test_no_example_calls_through_a_prefix(self):
        for path in self.example_files():
            with self.subTest(example=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("tl.", source)

    def test_no_example_reaches_into_the_platform_layer(self):
        for path in self.example_files():
            with self.subTest(example=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("trjoludus.platform", source)


def _sprite(test):
    import struct
    import tempfile
    import zlib

    width = height = 2
    rows = b"".join(
        b"\x00" + bytes([200, 100, 50, 255]) * width for _ in range(height)
    )

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    path = Path(directory.name) / "sprite.png"
    path.write_bytes(png)
    return path


if __name__ == "__main__":
    unittest.main()
