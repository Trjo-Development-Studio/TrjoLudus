"""Tests for backend selection.

Resolution and construction are separate functions precisely so that the
*decision* can be tested without a display. Everything in this file except
:class:`TestCreateRealBackend` runs headlessly.
"""

import os
import unittest
from unittest import mock

from trjoludus.errors import PlatformError, UnsupportedPlatformError
from trjoludus.platform import (
    BACKEND_ENV_VAR,
    BACKEND_NAMES,
    PlatformName,
    create_backend,
    resolve_backend_name,
)
from trjoludus.platform.base import PlatformBackend
from trjoludus.platform.null import NullBackend


def without_override():
    """Environment with TRJOLUDUS_BACKEND removed."""
    env = {k: v for k, v in os.environ.items() if k != BACKEND_ENV_VAR}
    return mock.patch.dict(os.environ, env, clear=True)


class TestResolution(unittest.TestCase):
    def test_env_var_name(self):
        self.assertEqual(BACKEND_ENV_VAR, "TRJOLUDUS_BACKEND")

    def test_known_backend_names(self):
        self.assertEqual(set(BACKEND_NAMES), {"x11", "win32", "null"})

    def test_linux_defaults_to_x11(self):
        with without_override(), mock.patch(
            "trjoludus.platform.detect_platform",
            return_value=PlatformName.LINUX,
        ):
            self.assertEqual(resolve_backend_name(), "x11")

    def test_windows_defaults_to_win32(self):
        """Superseded Step 5 behaviour: Windows now has a backend."""
        with without_override(), mock.patch(
            "trjoludus.platform.detect_platform",
            return_value=PlatformName.WINDOWS,
        ):
            self.assertEqual(resolve_backend_name(), "win32")

    def test_windows_does_not_silently_fall_back_to_null(self):
        """A headless fallback would look like success while showing nothing."""
        with without_override(), mock.patch(
            "trjoludus.platform.detect_platform",
            return_value=PlatformName.WINDOWS,
        ):
            self.assertNotEqual(resolve_backend_name(), "null")

    def test_every_supported_platform_has_a_default(self):
        for platform in PlatformName:
            with self.subTest(platform=platform), without_override(), mock.patch(
                "trjoludus.platform.detect_platform", return_value=platform
            ):
                self.assertIn(resolve_backend_name(), BACKEND_NAMES)

    def test_unsupported_platform_propagates(self):
        with without_override(), mock.patch(
            "trjoludus.platform.detect_platform",
            side_effect=UnsupportedPlatformError("nope"),
        ):
            with self.assertRaises(UnsupportedPlatformError):
                resolve_backend_name()

    def test_environment_override(self):
        with mock.patch.dict(os.environ, {BACKEND_ENV_VAR: "null"}):
            self.assertEqual(resolve_backend_name(), "null")

    def test_explicit_name_beats_the_environment(self):
        with mock.patch.dict(os.environ, {BACKEND_ENV_VAR: "null"}):
            self.assertEqual(resolve_backend_name("x11"), "x11")

    def test_empty_environment_value_is_ignored(self):
        """An empty string must fall through to the platform default."""
        with mock.patch.dict(os.environ, {BACKEND_ENV_VAR: ""}), mock.patch(
            "trjoludus.platform.detect_platform",
            return_value=PlatformName.LINUX,
        ):
            self.assertEqual(resolve_backend_name(), "x11")

    def test_unknown_explicit_name_is_rejected(self):
        with self.assertRaises(PlatformError) as caught:
            resolve_backend_name("wayland")
        message = str(caught.exception)
        self.assertIn("wayland", message)
        for name in BACKEND_NAMES:
            self.assertIn(name, message)

    def test_unknown_environment_value_is_rejected(self):
        with mock.patch.dict(os.environ, {BACKEND_ENV_VAR: "sdl"}):
            with self.assertRaises(PlatformError):
                resolve_backend_name()

    def test_resolution_never_constructs_anything(self):
        """Resolving must not open a display, whatever it resolves to."""
        with mock.patch.dict(os.environ, {BACKEND_ENV_VAR: "x11"}):
            self.assertEqual(resolve_backend_name(), "x11")


class TestCreateNullBackend(unittest.TestCase):
    def test_creates_the_null_backend_by_name(self):
        backend = create_backend("null")
        self.assertIsInstance(backend, NullBackend)
        self.assertEqual(backend.name, "null")

    def test_creates_the_null_backend_from_the_environment(self):
        with mock.patch.dict(os.environ, {BACKEND_ENV_VAR: "null"}):
            self.assertIsInstance(create_backend(), NullBackend)

    def test_result_satisfies_the_contract(self):
        self.assertIsInstance(create_backend("null"), PlatformBackend)

    def test_each_call_returns_a_fresh_backend(self):
        self.assertIsNot(create_backend("null"), create_backend("null"))

    def test_unknown_name_is_rejected(self):
        with self.assertRaises(PlatformError):
            create_backend("nonsense")


class TestImportIsolation(unittest.TestCase):
    def test_selecting_null_does_not_import_the_x11_backend(self):
        """Backends are imported inside create_backend, not at module level."""
        import subprocess
        import sys
        from pathlib import Path

        import trjoludus

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys\n"
                "from trjoludus.platform import create_backend\n"
                "create_backend('null')\n"
                "leaked = [m for m in sys.modules\n"
                "          if 'platform.linux' in m or m.split('.')[0] == 'ctypes']\n"
                "assert not leaked, leaked\n"
                "print('ok')\n",
            ],
            env={
                **os.environ,
                "PYTHONPATH": str(Path(trjoludus.__file__).parent.parent),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


@unittest.skipUnless(os.environ.get("DISPLAY"), "no X11 display")
class TestCreateRealBackend(unittest.TestCase):
    """Constructing the real backend needs a real server."""

    def test_creates_the_x11_backend_by_name(self):
        from trjoludus.platform.linux.x11 import X11Backend

        backend = create_backend("x11")
        self.addCleanup(backend.shutdown)
        self.assertIsInstance(backend, X11Backend)
        self.assertEqual(backend.name, "x11")

    def test_linux_default_creates_x11(self):
        from trjoludus.platform.linux.x11 import X11Backend

        with without_override():
            backend = create_backend()
        self.addCleanup(backend.shutdown)
        self.assertIsInstance(backend, X11Backend)


if __name__ == "__main__":
    unittest.main()
