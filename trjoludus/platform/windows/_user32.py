"""Raw Win32 declarations. No engine logic lives here.

Every function is declared with an explicit ``argtypes`` **and** ``restype``,
for the reason recorded in ARCHITECTURE.md: ctypes defaults ``restype`` to
``c_int``, which truncates a 64-bit handle to 32 bits and corrupts memory the
next time that handle is used.

**Types are declared to Windows' widths, not the host's.** ``ctypes.wintypes``
is importable on Linux but derives some types from the *host* ABI: it maps
``LONG`` to ``c_long``, which is 8 bytes on 64-bit Linux and 4 bytes on
Windows. Structures built from it would therefore have the wrong layout when
inspected anywhere but Windows. This module instead uses fixed-width types
where Win32 is fixed-width, and pointer-sized types where Win32 is
pointer-sized, so a declaration means the same thing everywhere.

**This module imports on any platform.** It has to: the declarations are
reviewed and unit-tested on Linux, where the development happens. Actually
*loading* the DLLs is what fails off Windows, and that is
:func:`load_libraries`'s job.
"""

import ctypes
from ctypes import POINTER, Structure, c_int32, c_size_t, c_ssize_t
from ctypes import c_uint16, c_uint32, c_void_p, c_wchar_p

from trjoludus.errors import PlatformError

__all__ = [
    "HWND",
    "MSG",
    "OPTIONAL_FUNCTIONS",
    "RECT",
    "WNDCLASSEXW",
    "WNDPROC",
    "KERNEL32_SIGNATURES",
    "USER32_SIGNATURES",
    "load_libraries",
]

# --- types ---------------------------------------------------------------
# Fixed-width where Win32 is fixed-width. A Windows LONG is 32 bits on every
# Windows architecture, including x64 -- unlike a C long on Linux.

BOOL = c_int32
INT = c_int32
UINT = c_uint32
LONG = c_int32
DWORD = c_uint32
WORD = c_uint16
ATOM = c_uint16
LPCWSTR = c_wchar_p

# Pointer-sized. c_size_t / c_ssize_t follow the pointer width of whatever
# they are compiled against, which is what UINT_PTR and LONG_PTR mean.
HANDLE = c_void_p
HWND = HANDLE
HINSTANCE = HANDLE
HICON = HANDLE
HCURSOR = HANDLE
HBRUSH = HANDLE
HMENU = HANDLE
HDC = HANDLE
LPVOID = c_void_p
WPARAM = c_size_t
LPARAM = c_ssize_t
LRESULT = c_ssize_t

#: DPI_AWARENESS_CONTEXT is an opaque pointer-sized handle whose documented
#: values are small negative sentinels such as -4. A signed pointer-sized type
#: passes those correctly; c_void_p would have to carry them as huge unsigned
#: numbers.
DPI_AWARENESS_CONTEXT = c_ssize_t

#: True when this interpreter can actually call Win32.
IS_WINDOWS_RUNTIME = hasattr(ctypes, "WINFUNCTYPE")

if IS_WINDOWS_RUNTIME:  # pragma: no cover -- only true on Windows
    #: The window procedure signature. WINFUNCTYPE is stdcall, which is what
    #: Win32 callbacks require on 32-bit Windows; on x64 there is only one
    #: convention, but declaring it correctly costs nothing.
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)
else:
    # Off Windows there is no stdcall callback factory, but the declarations
    # must still import so they can be reviewed and tested. A function pointer
    # is pointer-sized, so WNDCLASSEXW's layout below is identical either way.
    WNDPROC = c_void_p


# --- structures ----------------------------------------------------------


class POINT(Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class RECT(Structure):
    """A rectangle. Used with AdjustWindowRectEx and GetClientRect."""

    _fields_ = [
        ("left", LONG),
        ("top", LONG),
        ("right", LONG),
        ("bottom", LONG),
    ]


class MSG(Structure):
    """One entry from the thread message queue."""

    _fields_ = [
        ("hwnd", HWND),
        ("message", UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", DWORD),
        ("pt", POINT),
    ]


class BITMAPINFOHEADER(Structure):
    """Describes the layout of a device-independent bitmap."""

    _fields_ = [
        ("biSize", DWORD),
        ("biWidth", LONG),
        ("biHeight", LONG),
        ("biPlanes", WORD),
        ("biBitCount", WORD),
        ("biCompression", DWORD),
        ("biSizeImage", DWORD),
        ("biXPelsPerMeter", LONG),
        ("biYPelsPerMeter", LONG),
        ("biClrUsed", DWORD),
        ("biClrImportant", DWORD),
    ]


class BITMAPINFO(Structure):
    """A bitmap header plus its (unused at 32 bpp) colour table."""

    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", DWORD * 3),
    ]


class WNDCLASSEXW(Structure):
    """A window class registration, wide-character variant."""

    _fields_ = [
        ("cbSize", UINT),
        ("style", UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", INT),
        ("cbWndExtra", INT),
        ("hInstance", HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", LPCWSTR),
        ("lpszClassName", LPCWSTR),
        ("hIconSm", HICON),
    ]


# --- constants -----------------------------------------------------------

#: Window messages this backend interprets. Everything else goes to
#: DefWindowProcW untouched.
WM_DESTROY = 0x0002
WM_SIZE = 0x0005
WM_CLOSE = 0x0010

#: Key went down. Virtual-key code arrives in wParam.
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

#: Pointer messages. Position arrives packed into lParam.
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208

#: Virtual-key codes that are not simply a character (WinUser.h).
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28

#: wParam of WM_SIZE when the window was minimised. Its client size is 0x0,
#: which is not a meaningful resize.
SIZE_MINIMIZED = 1

#: Class styles: redraw the whole client area when either dimension changes.
CS_VREDRAW = 0x0001
CS_HREDRAW = 0x0002

#: A normal resizable top-level window with a caption, system menu, and
#: minimise/maximise boxes.
WS_OVERLAPPEDWINDOW = 0x00CF0000

#: Extended style. The window appears on the taskbar.
WS_EX_APPWINDOW = 0x00040000

#: Let Windows choose the window position.
CW_USEDEFAULT = -0x80000000

#: ShowWindow command: show in its normal, non-minimised state.
SW_SHOWNORMAL = 1

#: PeekMessageW flag: remove the message from the queue after reading it.
PM_REMOVE = 0x0001

#: Standard arrow cursor, as a MAKEINTRESOURCE ordinal.
IDC_ARROW = 32512

#: Per-monitor DPI awareness, version 2 (Windows 10 1703+). Without this the
#: system lies about window dimensions on scaled displays.
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

#: BITMAPINFOHEADER compression: none, pixels stored directly.
BI_RGB = 0

#: SetDIBitsToDevice colour-table mode: the values are literal RGB.
DIB_RGB_COLORS = 0

#: StretchBlt/SetDIBits raster operation: copy the source over the target.
SRCCOPY = 0x00CC0020


# --- function signatures -------------------------------------------------

#: ``name -> (argtypes, restype)`` for user32.
USER32_SIGNATURES: dict[str, tuple[list, object]] = {
    "RegisterClassExW": ([POINTER(WNDCLASSEXW)], ATOM),
    "UnregisterClassW": ([LPCWSTR, HINSTANCE], BOOL),
    "CreateWindowExW": (
        [DWORD, LPCWSTR, LPCWSTR, DWORD, INT, INT, INT, INT,
         HWND, HMENU, HINSTANCE, LPVOID],
        HWND,
    ),
    "DestroyWindow": ([HWND], BOOL),
    "ShowWindow": ([HWND, INT], BOOL),
    "SetWindowTextW": ([HWND, LPCWSTR], BOOL),
    "AdjustWindowRectEx": ([POINTER(RECT), DWORD, BOOL, DWORD], BOOL),
    "GetClientRect": ([HWND, POINTER(RECT)], BOOL),
    "PeekMessageW": ([POINTER(MSG), HWND, UINT, UINT, UINT], BOOL),
    "TranslateMessage": ([POINTER(MSG)], BOOL),
    "DispatchMessageW": ([POINTER(MSG)], LRESULT),
    "DefWindowProcW": ([HWND, UINT, WPARAM, LPARAM], LRESULT),
    "PostQuitMessage": ([INT], None),
    "LoadCursorW": ([HINSTANCE, LPCWSTR], HCURSOR),
    "SetProcessDpiAwarenessContext": ([DPI_AWARENESS_CONTEXT], BOOL),
    # Used only to drive integration tests, which post WM_CLOSE and WM_SIZE to
    # a real window. Declaring it here keeps every Win32 prototype in one
    # audited place rather than duplicated into a test file.
    "PostMessageW": ([HWND, UINT, WPARAM, LPARAM], BOOL),
    # Presenting a frame.
    "GetDC": ([HWND], HDC),
    "ReleaseDC": ([HWND, HDC], INT),
}

#: ``name -> (argtypes, restype)`` for kernel32.
KERNEL32_SIGNATURES: dict[str, tuple[list, object]] = {
    "GetModuleHandleW": ([LPCWSTR], HINSTANCE),
}

#: ``name -> (argtypes, restype)`` for gdi32, used to put pixels on screen.
GDI32_SIGNATURES: dict[str, tuple[list, object]] = {
    "StretchDIBits": (
        [HDC, INT, INT, INT, INT, INT, INT, INT, INT,
         LPVOID, POINTER(BITMAPINFO), UINT, DWORD],
        INT,
    ),
}

#: Functions that may legitimately be missing on an older Windows. Their
#: absence is not an error; the backend degrades instead.
OPTIONAL_FUNCTIONS = frozenset({"SetProcessDpiAwarenessContext"})


def load_libraries():
    """Load user32 and kernel32 and apply every declared signature.

    Both are opened with ``use_last_error=True`` so that
    ``ctypes.get_last_error()`` reports the Win32 error code for a failed
    call without needing a separate ``GetLastError`` declaration.

    Returns:
        ``(user32, kernel32, gdi32)``. A function listed in
        :data:`OPTIONAL_FUNCTIONS` that this Windows version does not export
        is simply absent from the returned library.

    Raises:
        PlatformError: If this is not a Windows interpreter, or the libraries
            cannot be loaded.
    """
    if not IS_WINDOWS_RUNTIME:
        raise PlatformError(
            "The Win32 backend needs a Windows interpreter: this Python has no "
            "ctypes.WinDLL, so user32 and kernel32 cannot be loaded. Set "
            "TRJOLUDUS_BACKEND=null to run headless here."
        )

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    except OSError as exc:  # pragma: no cover -- needs a broken Windows
        raise PlatformError(f"Could not load the Win32 libraries: {exc}") from exc

    for library, signatures in (
        (user32, USER32_SIGNATURES),
        (kernel32, KERNEL32_SIGNATURES),
        (gdi32, GDI32_SIGNATURES),
    ):
        for name, (argtypes, restype) in signatures.items():
            try:
                function = getattr(library, name)
            except AttributeError:
                if name in OPTIONAL_FUNCTIONS:
                    continue
                raise PlatformError(  # pragma: no cover -- needs old Windows
                    f"This Windows does not export {name}, which TrjoLudus "
                    f"requires."
                ) from None
            function.argtypes = argtypes
            function.restype = restype

    return user32, kernel32, gdi32
