"""Foundation tests.

Run with:  python -m unittest discover -s tests
"""

import unittest
from unittest import mock

import trjoludus
from trjoludus.errors import UnsupportedPlatformError
from trjoludus.platform import PlatformName, detect_platform


class TestPublicApi(unittest.TestCase):
    def test_version_is_exposed(self):
        self.assertIsInstance(trjoludus.__version__, str)
        self.assertTrue(trjoludus.__version__)

    def test_public_names_are_importable(self):
        for name in trjoludus.__all__:
            self.assertTrue(hasattr(trjoludus, name), f"missing public name: {name}")

    def test_no_runtime_dependencies(self):
        """The engine must import using nothing but the standard library."""
        import trjoludus.errors
        import trjoludus.platform  # noqa: F401


class TestPlatformDetection(unittest.TestCase):
    def test_detects_a_supported_platform(self):
        self.assertIsInstance(detect_platform(), PlatformName)

    def test_windows(self):
        with mock.patch("sys.platform", "win32"):
            self.assertIs(detect_platform(), PlatformName.WINDOWS)

    def test_linux(self):
        with mock.patch("sys.platform", "linux"):
            self.assertIs(detect_platform(), PlatformName.LINUX)

    def test_unsupported_platform_raises(self):
        with mock.patch("sys.platform", "darwin"):
            with self.assertRaises(UnsupportedPlatformError):
                detect_platform()

    def test_unsupported_platform_error_is_a_trjoludus_error(self):
        self.assertTrue(
            issubclass(UnsupportedPlatformError, trjoludus.TrjoLudusError)
        )

    def test_platform_name_str(self):
        self.assertEqual(str(PlatformName.LINUX), "linux")


if __name__ == "__main__":
    unittest.main()
