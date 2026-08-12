"""Tests for the Win32 backend.

Structured so that the parts which *can* be checked off Windows are, and the
parts which cannot are skipped honestly rather than faked:

* :class:`TestDeclarations` -- ctypes declarations and constants. These run
  anywhere, and they are the ones worth running, because a wrong integer width
  or a missing restype corrupts memory rather than failing loudly.
* :class:`TestMessageParameterHelpers` -- the LOWORD/HIWORD arithmetic, which
  is pure and therefore fully testable on Linux.
* :class:`TestContractConformance` / :class:`TestImportIsolation` -- shape and
  layering rules.
* :class:`TestWin32Integration` -- needs a real Windows runtime and is skipped
  everywhere else. Nothing here mocks user32: a fake Windows would happily
  agree with a wrong struct layout, which is exactly the failure being guarded
  against.
"""

import ctypes
import os
import subprocess
import sys
import unittest
from pathlib import Path

import trjoludus
from trjoludus.errors import PlatformError
from trjoludus.events import KEY_NAMES, WindowCloseRequested, WindowResized
from trjoludus.platform.base import PlatformBackend, PlatformWindow
from trjoludus.platform.windows import _user32
from trjoludus.platform.windows.win32 import (
    BACKEND_NAME,
    Win32Backend,
    Win32Window,
    hiword,
    key_name,
    loword,
)

ON_WINDOWS = sys.platform == "win32"
requires_windows = unittest.skipUnless(ON_WINDOWS, "not running on Windows")

#: Win32 functions that genuinely return void.
VOID_FUNCTIONS = {"PostQuitMessage"}


class TestDeclarations(unittest.TestCase):
    def all_signatures(self):
        return {**_user32.USER32_SIGNATURES, **_user32.KERNEL32_SIGNATURES}

    def test_every_function_declares_argtypes_and_restype(self):
        signatures = self.all_signatures()
        self.assertGreater(len(signatures), 0)
        for name, (argtypes, restype) in signatures.items():
            with self.subTest(function=name):
                self.assertIsInstance(argtypes, list)
                if name in VOID_FUNCTIONS:
                    self.assertIsNone(restype, "void functions declare None")
                else:
                    self.assertIsNotNone(restype, "restype must be explicit")

    def test_required_functions_are_declared(self):
        """The set ARCHITECTURE.md names for this milestone."""
        required = {
            "RegisterClassExW", "CreateWindowExW", "DestroyWindow", "ShowWindow",
            "PeekMessageW", "TranslateMessage", "DispatchMessageW",
            "DefWindowProcW", "PostQuitMessage", "AdjustWindowRectEx",
            "GetClientRect", "SetProcessDpiAwarenessContext",
        }
        self.assertTrue(required <= set(_user32.USER32_SIGNATURES))
        self.assertIn("GetModuleHandleW", _user32.KERNEL32_SIGNATURES)

    def test_only_wide_character_entry_points(self):
        """The A variants mangle anything outside the active code page."""
        for name in self.all_signatures():
            with self.subTest(function=name):
                self.assertFalse(
                    name.endswith("A"), f"{name} is the ANSI variant"
                )

    def test_handle_returning_functions_are_pointer_sized(self):
        """c_int restype would truncate an HWND and corrupt memory."""
        for name in ("CreateWindowExW",):
            _, restype = _user32.USER32_SIGNATURES[name]
            with self.subTest(function=name):
                self.assertEqual(ctypes.sizeof(restype),
                                 ctypes.sizeof(ctypes.c_void_p))
        _, restype = _user32.KERNEL32_SIGNATURES["GetModuleHandleW"]
        self.assertEqual(ctypes.sizeof(restype), ctypes.sizeof(ctypes.c_void_p))

    def test_windows_long_is_32_bit_regardless_of_host(self):
        """A Windows LONG is 32 bits even on x64, unlike a Linux C long."""
        self.assertEqual(ctypes.sizeof(_user32.LONG), 4)
        self.assertEqual(ctypes.sizeof(_user32.DWORD), 4)
        self.assertEqual(ctypes.sizeof(_user32.UINT), 4)
        self.assertEqual(ctypes.sizeof(_user32.WORD), 2)
        self.assertEqual(ctypes.sizeof(_user32.ATOM), 2)

    def test_message_parameters_are_pointer_sized(self):
        pointer = ctypes.sizeof(ctypes.c_void_p)
        for name in ("WPARAM", "LPARAM", "LRESULT", "HWND", "HINSTANCE"):
            with self.subTest(type=name):
                self.assertEqual(ctypes.sizeof(getattr(_user32, name)), pointer)

    def test_lparam_and_lresult_are_signed(self):
        """LONG_PTR is signed; an unsigned type would corrupt return values."""
        self.assertEqual(_user32.LPARAM(-1).value, -1)
        self.assertEqual(_user32.LRESULT(-1).value, -1)

    def test_wparam_is_unsigned(self):
        self.assertGreater(_user32.WPARAM(-1).value, 0)

    def test_dpi_awareness_context_is_signed_pointer_sized(self):
        """Its documented values are small negative sentinels such as -4."""
        self.assertEqual(
            ctypes.sizeof(_user32.DPI_AWARENESS_CONTEXT),
            ctypes.sizeof(ctypes.c_void_p),
        )
        self.assertEqual(_user32.DPI_AWARENESS_CONTEXT(-4).value, -4)

    def test_structure_layouts_match_windows(self):
        """Sizes are host-independent because the types are fixed-width."""
        self.assertEqual(ctypes.sizeof(_user32.RECT), 16)
        self.assertEqual(ctypes.sizeof(_user32.POINT), 8)

    def test_rect_field_order(self):
        rect = _user32.RECT(1, 2, 30, 40)
        self.assertEqual(
            (rect.left, rect.top, rect.right, rect.bottom), (1, 2, 30, 40)
        )

    def test_wndclassexw_has_the_documented_fields(self):
        fields = [name for name, _ in _user32.WNDCLASSEXW._fields_]
        self.assertEqual(fields[0], "cbSize")
        for expected in ("lpfnWndProc", "hInstance", "lpszClassName", "hIconSm"):
            self.assertIn(expected, fields)

    def test_msg_has_the_documented_fields(self):
        fields = [name for name, _ in _user32.MSG._fields_]
        self.assertEqual(fields[:4], ["hwnd", "message", "wParam", "lParam"])

    def test_message_constants(self):
        self.assertEqual(_user32.WM_DESTROY, 0x0002)
        self.assertEqual(_user32.WM_SIZE, 0x0005)
        self.assertEqual(_user32.WM_CLOSE, 0x0010)
        self.assertEqual(_user32.SIZE_MINIMIZED, 1)

    def test_style_and_flag_constants(self):
        self.assertEqual(_user32.WS_OVERLAPPEDWINDOW, 0x00CF0000)
        self.assertEqual(_user32.PM_REMOVE, 0x0001)
        self.assertEqual(_user32.SW_SHOWNORMAL, 1)
        self.assertEqual(_user32.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, -4)

    def test_cw_usedefault_is_a_negative_int32(self):
        """It is (int)0x80000000, which must not arrive as a huge positive."""
        self.assertEqual(_user32.CW_USEDEFAULT, -2147483648)
        self.assertEqual(ctypes.c_int32(_user32.CW_USEDEFAULT).value,
                         _user32.CW_USEDEFAULT)

    def test_keyboard_message_constants(self):
        self.assertEqual(_user32.WM_KEYDOWN, 0x0100)
        self.assertEqual(_user32.WM_SYSKEYDOWN, 0x0104)
        self.assertEqual(_user32.VK_ESCAPE, 0x1B)
        self.assertEqual(_user32.VK_RETURN, 0x0D)

    def test_no_mouse_messages_are_declared(self):
        """Mouse input is still a later milestone."""
        for name in dir(_user32):
            self.assertNotIn("WM_MOUSE", name)
            self.assertNotIn("WM_LBUTTON", name)

    def test_backend_name_constant(self):
        self.assertEqual(BACKEND_NAME, "win32")


class TestVirtualKeyTranslation(unittest.TestCase):
    """Virtual-key code to canonical name. Pure, so it runs on Linux."""

    def test_letters(self):
        self.assertEqual(key_name(0x57), "W")
        self.assertEqual(key_name(0x41), "A")
        self.assertEqual(key_name(0x53), "S")
        self.assertEqual(key_name(0x44), "D")

    def test_digits(self):
        self.assertEqual(key_name(0x30), "0")
        self.assertEqual(key_name(0x39), "9")

    def test_named_keys(self):
        self.assertEqual(key_name(_user32.VK_ESCAPE), "ESCAPE")
        self.assertEqual(key_name(_user32.VK_RETURN), "ENTER")
        self.assertEqual(key_name(_user32.VK_SPACE), "SPACE")
        self.assertEqual(key_name(_user32.VK_UP), "UP")
        self.assertEqual(key_name(_user32.VK_DOWN), "DOWN")
        self.assertEqual(key_name(_user32.VK_LEFT), "LEFT")
        self.assertEqual(key_name(_user32.VK_RIGHT), "RIGHT")

    def test_unknown_codes_are_ignored_rather_than_guessed(self):
        for code in (0x10, 0x11, 0x00):
            with self.subTest(code=hex(code)):
                self.assertIsNone(key_name(code))

    def test_every_name_produced_is_a_canonical_name(self):
        for code in range(0x100):
            name = key_name(code)
            if name is not None:
                with self.subTest(code=hex(code)):
                    self.assertIn(name, KEY_NAMES)

    def test_both_backends_agree_on_the_names_they_produce(self):
        """The same physical key must read the same on either platform."""
        from trjoludus.platform.linux.x11 import key_name as x11_key_name

        pairs = [(0x57, 0x77), (0x41, 0x61), (_user32.VK_ESCAPE, 0xFF1B),
                 (_user32.VK_SPACE, 0x0020), (_user32.VK_UP, 0xFF52)]
        for virtual_key, keysym in pairs:
            with self.subTest(vk=hex(virtual_key)):
                self.assertEqual(key_name(virtual_key), x11_key_name(keysym))


class TestMessageParameterHelpers(unittest.TestCase):
    """LOWORD/HIWORD on a signed, pointer-sized LPARAM."""

    def test_extracts_width_and_height(self):
        lparam = (600 << 16) | 800
        self.assertEqual(loword(lparam), 800)
        self.assertEqual(hiword(lparam), 600)

    def test_zero(self):
        self.assertEqual((loword(0), hiword(0)), (0, 0))

    def test_maximum_16_bit_values(self):
        lparam = (0xFFFF << 16) | 0xFFFF
        self.assertEqual(loword(lparam), 0xFFFF)
        self.assertEqual(hiword(lparam), 0xFFFF)

    def test_negative_lparam_still_yields_unsigned_words(self):
        """LPARAM is signed, so this is the case naive slicing gets wrong."""
        self.assertGreaterEqual(loword(-1), 0)
        self.assertGreaterEqual(hiword(-1), 0)
        self.assertEqual(loword(-1), 0xFFFF)
        self.assertEqual(hiword(-1), 0xFFFF)

    def test_results_are_always_in_range(self):
        for lparam in (-(2 ** 40), -12345, -1, 0, 1, 12345, 2 ** 40):
            with self.subTest(lparam=lparam):
                self.assertTrue(0 <= loword(lparam) <= 0xFFFF)
                self.assertTrue(0 <= hiword(lparam) <= 0xFFFF)


class TestLibraryLoading(unittest.TestCase):
    def test_optional_functions_are_declared_optional(self):
        self.assertIn("SetProcessDpiAwarenessContext", _user32.OPTIONAL_FUNCTIONS)

    @unittest.skipIf(ON_WINDOWS, "this asserts the non-Windows path")
    def test_loading_off_windows_raises_platform_error(self):
        with self.assertRaises(PlatformError) as caught:
            _user32.load_libraries()
        message = str(caught.exception)
        self.assertIn("Windows", message)
        self.assertIn("TRJOLUDUS_BACKEND=null", message)

    @unittest.skipIf(ON_WINDOWS, "this asserts the non-Windows path")
    def test_constructing_the_backend_off_windows_raises(self):
        with self.assertRaises(PlatformError):
            Win32Backend()

    @unittest.skipIf(ON_WINDOWS, "this asserts the non-Windows path")
    def test_windows_runtime_flag_is_false_here(self):
        self.assertFalse(_user32.IS_WINDOWS_RUNTIME)


class TestContractConformance(unittest.TestCase):
    """Shape checks that need no Windows runtime."""

    def test_backend_implements_the_contract(self):
        self.assertTrue(issubclass(Win32Backend, PlatformBackend))

    def test_window_implements_the_contract(self):
        self.assertTrue(issubclass(Win32Window, PlatformWindow))

    def test_backend_declares_no_abstract_methods(self):
        self.assertEqual(Win32Backend.__abstractmethods__, frozenset())

    def test_window_declares_no_abstract_methods(self):
        self.assertEqual(Win32Window.__abstractmethods__, frozenset())

    def test_window_has_no_event_injection(self):
        self.assertFalse(hasattr(Win32Window, "simulate_event"))

    def test_window_exposes_the_same_surface_as_other_backends(self):
        from trjoludus.platform.linux.x11 import X11Window

        for name in ("size", "title", "poll_events", "close", "is_closed"):
            with self.subTest(member=name):
                self.assertTrue(hasattr(Win32Window, name))
                self.assertTrue(hasattr(X11Window, name))

    def test_backend_exposes_the_same_surface_as_other_backends(self):
        from trjoludus.platform.linux.x11 import X11Backend

        for name in ("name", "create_window", "shutdown", "is_shut_down",
                     "windows"):
            with self.subTest(member=name):
                self.assertTrue(hasattr(Win32Backend, name))
                self.assertTrue(hasattr(X11Backend, name))


class TestImportIsolation(unittest.TestCase):
    def test_importing_trjoludus_loads_no_windows_module(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, trjoludus\n"
                "leaked = [m for m in sys.modules if 'platform.windows' in m]\n"
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

    def test_declarations_import_on_any_platform(self):
        """They must be reviewable and testable off Windows."""
        self.assertIsNotNone(_user32.WNDCLASSEXW)
        self.assertIsNotNone(_user32.MSG)


@requires_windows
class TestWin32Integration(unittest.TestCase):
    """Real windows on a real Windows. Skipped everywhere else."""

    def setUp(self):
        self.backend = Win32Backend()
        self.addCleanup(self.backend.shutdown)

    def test_backend_name(self):
        self.assertEqual(self.backend.name, "win32")

    def test_creates_a_real_window(self):
        window = self.backend.create_window("test", 320, 240)
        self.assertIsInstance(window, Win32Window)
        self.assertTrue(window.hwnd)

    def test_client_area_matches_the_request(self):
        """AdjustWindowRectEx must have expanded for the frame, not shrunk."""
        window = self.backend.create_window("test", 400, 300)
        self.assertEqual(window.size, (400, 300))

    def test_title_is_readable_and_writable(self):
        window = self.backend.create_window("before", 200, 150)
        self.assertEqual(window.title, "before")
        window.title = "after"
        self.assertEqual(window.title, "after")

    def test_title_accepts_non_ascii(self):
        title = "TrjoLudus — Windows Test åæø"
        window = self.backend.create_window(title, 200, 150)
        self.assertEqual(window.title, title)
        window.title = "Apex Horizon åæø"
        self.assertEqual(window.title, "Apex Horizon åæø")

    def test_poll_events_never_blocks(self):
        import time

        window = self.backend.create_window("test", 200, 150)
        started = time.monotonic()
        for _ in range(5):
            list(window.poll_events())
        self.assertLess(time.monotonic() - started, 2.0)

    def test_close_message_becomes_a_close_request(self):
        import time

        window = self.backend.create_window("test", 200, 150)
        self.backend._user32.PostMessageW(window.hwnd, _user32.WM_CLOSE, 0, 0)

        deadline = time.monotonic() + 5.0
        seen = []
        while time.monotonic() < deadline:
            seen.extend(window.poll_events())
            if any(isinstance(e, WindowCloseRequested) for e in seen):
                break
            time.sleep(0.01)
        self.assertTrue(any(isinstance(e, WindowCloseRequested) for e in seen))

    def test_close_request_does_not_destroy_the_window(self):
        """DefWindowProcW would destroy it; answering WM_CLOSE must not."""
        import time

        window = self.backend.create_window("test", 200, 150)
        self.backend._user32.PostMessageW(window.hwnd, _user32.WM_CLOSE, 0, 0)

        # Wait for the request to actually arrive rather than sleeping a fixed
        # interval and hoping. Asserting the negative only means something
        # once the positive has happened.
        deadline = time.monotonic() + 5.0
        arrived = False
        while time.monotonic() < deadline and not arrived:
            arrived = any(
                isinstance(e, WindowCloseRequested) for e in window.poll_events()
            )
            if not arrived:
                time.sleep(0.01)

        self.assertTrue(arrived, "close request never arrived")
        self.assertFalse(window.is_closed)

    def test_resize_produces_a_window_resized_event(self):
        import time

        window = self.backend.create_window("test", 400, 300)
        self.backend._user32.PostMessageW(
            window.hwnd, _user32.WM_SIZE, 0, (480 << 16) | 640
        )
        deadline = time.monotonic() + 5.0
        found = None
        while time.monotonic() < deadline and found is None:
            for event in window.poll_events():
                if isinstance(event, WindowResized):
                    found = event
            time.sleep(0.01)
        self.assertIsNotNone(found)
        self.assertEqual((found.width, found.height), (640, 480))
        self.assertEqual(window.size, (640, 480))

    def test_close_is_idempotent(self):
        window = self.backend.create_window("test", 200, 150)
        window.close()
        window.close()
        self.assertTrue(window.is_closed)

    def test_shutdown_is_idempotent(self):
        backend = Win32Backend()
        backend.shutdown()
        backend.shutdown()
        self.assertTrue(backend.is_shut_down)

    def test_shutdown_closes_remaining_windows(self):
        backend = Win32Backend()
        window = backend.create_window("test", 200, 150)
        backend.shutdown()
        self.assertTrue(window.is_closed)

    def test_create_window_after_shutdown_raises(self):
        backend = Win32Backend()
        backend.shutdown()
        with self.assertRaises(PlatformError):
            backend.create_window("test", 200, 150)

    def test_application_runs_on_a_real_window(self):
        from trjoludus.app import Application
        from trjoludus.game import Game

        class Counting(Game):
            def __init__(self):
                self.frames = 0

            def on_update(self, dt):
                self.frames += 1
                if self.frames >= 3:
                    self.quit()

        game = Counting()
        backend = Win32Backend()
        Application(game, title="win32 lifecycle", size=(320, 240),
                    max_fps=None, backend=backend).run()
        self.assertEqual(game.frames, 3)
        self.assertTrue(backend.is_shut_down)


if __name__ == "__main__":
    unittest.main()
