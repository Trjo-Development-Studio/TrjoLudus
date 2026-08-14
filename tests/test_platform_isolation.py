"""Import-isolation rules, checked in subprocesses.

Every check here runs in a fresh interpreter. Asserting on ``sys.modules``
inside the suite would be meaningless: another test module importing a backend
first would make the assertion pass or fail for reasons unrelated to the code
under test.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

import trjoludus

PACKAGE_PARENT = str(Path(trjoludus.__file__).parent.parent)
ON_WINDOWS = sys.platform == "win32"


def run_python(script: str, env: dict | None = None):
    environment = dict(os.environ if env is None else env)
    environment["PYTHONPATH"] = PACKAGE_PARENT
    return subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


#: Reports which of the interesting modules a fresh interpreter has loaded.
REPORT = """
import sys
loaded = sorted(
    m for m in sys.modules
    if m.split('.')[0] == 'ctypes'
    or 'platform.linux' in m
    or 'platform.windows' in m
)
print(';'.join(loaded))
"""


class TestImportIsolation(unittest.TestCase):
    def loaded_after(self, setup: str, env=None):
        result = run_python(setup + REPORT, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [m for m in result.stdout.strip().split(";") if m]

    def test_importing_trjoludus_loads_nothing_platform_specific(self):
        self.assertEqual(self.loaded_after("import trjoludus\n"), [])

    def test_importing_trjoludus_needs_no_graphical_environment(self):
        env = {
            k: v for k, v in os.environ.items()
            if k not in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR",
                         "XDG_SESSION_TYPE")
        }
        self.assertEqual(self.loaded_after("import trjoludus\n", env), [])

    def test_importing_the_platform_package_loads_no_backend(self):
        self.assertEqual(
            self.loaded_after("import trjoludus.platform\n"), []
        )

    def test_resolving_a_backend_name_loads_no_backend(self):
        """Resolution decides; only construction imports."""
        self.assertEqual(
            self.loaded_after(
                "from trjoludus.platform import resolve_backend_name\n"
                "resolve_backend_name('x11')\n"
            ),
            [],
        )

    def test_selecting_null_loads_neither_graphical_backend(self):
        loaded = self.loaded_after(
            "from trjoludus.platform import create_backend\n"
            "create_backend('null')\n"
        )
        self.assertEqual(loaded, [])

    def test_running_a_game_on_null_loads_neither_graphical_backend(self):
        """No X11, no Win32.

        ``ctypes`` is not part of this any more: the native renderer loads it
        when a game runs on the native backend, which is a different thing
        from a graphical platform backend being dragged in. The next test
        pins the ctypes side down where it can be pinned down.
        """
        loaded = self.loaded_after(
            "import trjoludus as tl\n"
            "class G(tl.Game):\n"
            "    def on_update(self, dt): self.quit()\n"
            "tl.run(G(), max_fps=None)\n",
            {**os.environ, "TRJOLUDUS_BACKEND": "null"},
        )
        backends = [name for name in loaded if name.startswith("trjoludus")]
        self.assertEqual(backends, [])

    def test_the_python_renderer_loads_nothing_native(self):
        """A game that asked for Python rendering gets no ctypes at all."""
        loaded = self.loaded_after(
            "import trjoludus as tl\n"
            "tl.rendering.engine = 'python'\n"
            "class G(tl.Game):\n"
            "    def on_update(self, dt): self.quit()\n"
            "tl.run(G(), max_fps=None)\n",
            {**os.environ, "TRJOLUDUS_BACKEND": "null"},
        )
        self.assertEqual(loaded, [],
                         "the Python renderer pulled in native code")

    @unittest.skipIf(ON_WINDOWS, "X11 is not the platform backend here")
    @unittest.skipUnless(os.environ.get("DISPLAY"), "no X11 display")
    def test_selecting_x11_does_not_load_the_windows_backend(self):
        loaded = self.loaded_after(
            "from trjoludus.platform import create_backend\n"
            "b = create_backend('x11')\n"
            "b.shutdown()\n"
        )
        self.assertTrue(any("platform.linux" in m for m in loaded), loaded)
        self.assertFalse(any("platform.windows" in m for m in loaded), loaded)

    @unittest.skipUnless(ON_WINDOWS, "not running on Windows")
    def test_selecting_win32_does_not_load_the_x11_backend(self):
        loaded = self.loaded_after(
            "from trjoludus.platform import create_backend\n"
            "b = create_backend('win32')\n"
            "b.shutdown()\n"
        )
        self.assertTrue(any("platform.windows" in m for m in loaded), loaded)
        self.assertFalse(any("platform.linux" in m for m in loaded), loaded)

    def test_the_check_can_actually_fail(self):
        """A canary: importing a backend must show up in the report."""
        loaded = self.loaded_after(
            "import trjoludus.platform.windows._user32\n"
        )
        self.assertTrue(any("platform.windows" in m for m in loaded), loaded)


class TestGraphicalBackendsDoNotFallBack(unittest.TestCase):
    """A backend that cannot work must say so, not quietly become headless."""

    @unittest.skipIf(ON_WINDOWS, "asserts the non-Windows path")
    def test_requesting_win32_off_windows_fails_clearly(self):
        result = run_python(
            "from trjoludus.platform import create_backend\n"
            "from trjoludus.errors import PlatformError\n"
            "try:\n"
            "    create_backend('win32')\n"
            "except PlatformError as e:\n"
            "    assert 'Windows' in str(e), e\n"
            "    print('clear-failure')\n"
            "else:\n"
            "    raise AssertionError('silently succeeded off Windows')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "clear-failure")

    @unittest.skipIf(ON_WINDOWS, "no X server on Windows to speak of")
    def test_requesting_x11_without_a_display_fails_clearly(self):
        env = {k: v for k, v in os.environ.items() if k != "DISPLAY"}
        result = run_python(
            "from trjoludus.platform import create_backend\n"
            "from trjoludus.errors import PlatformError\n"
            "try:\n"
            "    create_backend('x11')\n"
            "except PlatformError as e:\n"
            "    assert 'display' in str(e).lower(), e\n"
            "    print('clear-failure')\n"
            "else:\n"
            "    raise AssertionError('opened a display that should not exist')\n",
            env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "clear-failure")

    @unittest.skipIf(ON_WINDOWS, "asserts the non-Windows path")
    def test_a_failing_graphical_backend_never_becomes_null(self):
        """The failure must be an error, not a silent headless downgrade."""
        env = {k: v for k, v in os.environ.items() if k != "DISPLAY"}
        result = run_python(
            "import trjoludus as tl\n"
            "from trjoludus.errors import PlatformError\n"
            "class G(tl.Game):\n"
            "    ran = False\n"
            "    def on_update(self, dt):\n"
            "        G.ran = True\n"
            "        self.quit()\n"
            "try:\n"
            "    tl.run(G(), max_fps=None)\n"
            "except PlatformError:\n"
            "    assert not G.ran, 'the game ran headless instead of failing'\n"
            "    print('no-fallback')\n"
            "else:\n"
            "    raise AssertionError('ran without a display')\n",
            env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "no-fallback")


if __name__ == "__main__":
    unittest.main()
