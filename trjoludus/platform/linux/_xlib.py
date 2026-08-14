"""Raw Xlib declarations. No engine logic lives here.

Every function is declared with an explicit ``argtypes`` **and** ``restype``.
This is a hard rule, not a style preference: ctypes defaults ``restype`` to
``c_int``, which silently truncates a returned 64-bit ``Display *`` to 32 bits,
and the resulting pointer segfaults the interpreter the next time it is used.
That failure is recorded in ARCHITECTURE.md because it actually happened during
the platform investigation.

Layouts here were verified against a live Xwayland server rather than copied
from memory: ``sizeof(XEvent) == 192``, a ``ClientMessage`` carrying
``WM_DELETE_WINDOW`` round-tripped through ``XSendEvent``, and a
``ConfigureNotify`` reported the expected geometry.

Only what Milestone 1 Step 4 needs is declared. Anything speculative belongs in
the step that needs it.
"""

import ctypes
import ctypes.util
from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    Union,
    c_char,
    c_char_p,
    c_int,
    c_long,
    c_short,
    c_ubyte,
    c_uint,
    c_ulong,
    c_void_p,
)

from trjoludus.errors import PlatformError

__all__ = [
    "Atom",
    "Bool",
    "Display",
    "ERROR_HANDLER",
    "FUNCTION_SIGNATURES",
    "IO_ERROR_HANDLER",
    "LIBRARY_NAME",
    "Window",
    "XErrorEvent",
    "XEvent",
    "load_xlib",
]

# --- types ---------------------------------------------------------------
# On every platform Xlib supports, XID/Atom/Window are `unsigned long` and
# Bool is `int`. A Display* is opaque, so it stays a void pointer.

Display = c_void_p
XID = c_ulong
Window = XID
Atom = c_ulong
Bool = c_int

# --- X protocol constants ------------------------------------------------

#: Event type codes (X11/X.h).
KEY_PRESS = 2
KEY_RELEASE = 3
BUTTON_PRESS = 4
BUTTON_RELEASE = 5
MOTION_NOTIFY = 6
DESTROY_NOTIFY = 17
CONFIGURE_NOTIFY = 22
CLIENT_MESSAGE = 33

#: Event mask selecting ConfigureNotify and DestroyNotify.
STRUCTURE_NOTIFY_MASK = 1 << 17

#: Event mask selecting KeyRelease, so that a held key can be seen to stop
#: being held. Selected alongside KeyPress rather than instead of it: state
#: needs both edges, and the waiting calls still only answer to presses.
KEY_RELEASE_MASK = 1 << 1

#: Event mask selecting KeyPress.
KEY_PRESS_MASK = 1 << 0

#: Masks selecting the pointer. Button releases *are* selected, unlike key
#: releases, because "is this button held" needs to know when it stops being.
BUTTON_PRESS_MASK = 1 << 2
BUTTON_RELEASE_MASK = 1 << 3
POINTER_MOTION_MASK = 1 << 6

#: X button numbers. 4 and 5 are the scroll wheel, which is not reported yet.
BUTTON_LEFT = 1
BUTTON_MIDDLE = 2
BUTTON_RIGHT = 3

#: XChangeProperty mode.
PROP_MODE_REPLACE = 0

#: Format code for byte-sized property data.
PROP_FORMAT_BYTE = 8

#: Format code used by WM_PROTOCOLS client messages.
CLIENT_MESSAGE_FORMAT_LONG = 32

#: Passed to XGetWindowProperty to accept whatever type a property has.
ANY_PROPERTY_TYPE = 0

#: XCreateImage format: one whole pixel per unit, packed.
Z_PIXMAP = 2

#: Bit order/padding for a 32-bit-per-pixel ZPixmap.
BITMAP_PAD_32 = 32


# --- event structures ----------------------------------------------------


class XClientMessageData(Union):
    """The 20-byte payload of a ClientMessage."""

    _fields_ = [("b", c_char * 20), ("s", c_short * 10), ("l", c_long * 5)]


class XClientMessageEvent(Structure):
    """A ClientMessage, the delivery mechanism for WM_DELETE_WINDOW."""

    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", Bool),
        ("display", Display),
        ("window", Window),
        ("message_type", Atom),
        ("format", c_int),
        ("data", XClientMessageData),
    ]


class XConfigureEvent(Structure):
    """A ConfigureNotify, which reports a window's new geometry."""

    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", Bool),
        ("display", Display),
        ("event", Window),
        ("window", Window),
        ("x", c_int),
        ("y", c_int),
        ("width", c_int),
        ("height", c_int),
        ("border_width", c_int),
        ("above", Window),
        ("override_redirect", Bool),
    ]


class XKeyEvent(Structure):
    """A KeyPress. ``keycode`` is hardware-specific and must be looked up."""

    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", Bool),
        ("display", Display),
        ("window", Window),
        ("root", Window),
        ("subwindow", Window),
        ("time", c_ulong),
        ("x", c_int),
        ("y", c_int),
        ("x_root", c_int),
        ("y_root", c_int),
        ("state", c_uint),
        ("keycode", c_uint),
        ("same_screen", Bool),
    ]


class XButtonEvent(Structure):
    """A ButtonPress or ButtonRelease."""

    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", Bool),
        ("display", Display),
        ("window", Window),
        ("root", Window),
        ("subwindow", Window),
        ("time", c_ulong),
        ("x", c_int),
        ("y", c_int),
        ("x_root", c_int),
        ("y_root", c_int),
        ("state", c_uint),
        ("button", c_uint),
        ("same_screen", Bool),
    ]


class XMotionEvent(Structure):
    """A MotionNotify.

    Identical to a button event up to ``state``, then differs: this carries a
    one-byte ``is_hint`` where the button event carries a four-byte button
    number. Sharing one struct for both would misread the coordinates.
    """

    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", Bool),
        ("display", Display),
        ("window", Window),
        ("root", Window),
        ("subwindow", Window),
        ("time", c_ulong),
        ("x", c_int),
        ("y", c_int),
        ("x_root", c_int),
        ("y_root", c_int),
        ("state", c_uint),
        ("is_hint", c_char),
        ("same_screen", Bool),
    ]


class XDestroyWindowEvent(Structure):
    """A DestroyNotify, reporting that a window is gone."""

    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", Bool),
        ("display", Display),
        ("event", Window),
        ("window", Window),
    ]


class Visual(Structure):
    """A display's colour layout. Read to confirm the byte order we assume."""

    _fields_ = [
        ("ext_data", c_void_p),
        ("visualid", c_ulong),
        ("c_class", c_int),
        ("red_mask", c_ulong),
        ("green_mask", c_ulong),
        ("blue_mask", c_ulong),
        ("bits_per_rgb", c_int),
        ("map_entries", c_int),
    ]


class XImage(Structure):
    """An image the server can draw.

    Only the fields TrjoLudus reads or writes are named; the trailing function
    table is opaque padding so the struct is the right size for Xlib to fill
    in. Instances are created by ``XCreateImage`` rather than by hand.
    """

    _fields_ = [
        ("width", c_int),
        ("height", c_int),
        ("xoffset", c_int),
        ("format", c_int),
        ("data", c_void_p),
        ("byte_order", c_int),
        ("bitmap_unit", c_int),
        ("bitmap_bit_order", c_int),
        ("bitmap_pad", c_int),
        ("depth", c_int),
        ("bytes_per_line", c_int),
        ("bits_per_pixel", c_int),
        ("red_mask", c_ulong),
        ("green_mask", c_ulong),
        ("blue_mask", c_ulong),
        ("obdata", c_void_p),
        ("funcs", c_void_p * 6),
    ]


class XErrorEvent(Structure):
    """Passed to the protocol error handler."""

    _fields_ = [
        ("type", c_int),
        ("display", Display),
        ("resourceid", XID),
        ("serial", c_ulong),
        ("error_code", c_ubyte),
        ("request_code", c_ubyte),
        ("minor_code", c_ubyte),
    ]


class XEvent(Union):
    """The XEvent union, as read by XNextEvent.

    XEvent is a union of every event type in the protocol, and Xlib writes a
    full-sized one into whatever buffer is handed to ``XNextEvent``. Declaring
    only the members actually interpreted would under-allocate that buffer and
    let the server scribble past the end of it.

    ``pad`` is what makes this safe: Xlib defines the union's final member as
    ``long pad[24]``, so an XEvent is always 192 bytes on a 64-bit system
    regardless of which member is live. Including it here forces ctypes to the
    same size -- asserted by the test suite -- while the named members stay
    limited to the three event types Step 4 actually reads.
    """

    _fields_ = [
        ("type", c_int),
        ("xclient", XClientMessageEvent),
        ("xconfigure", XConfigureEvent),
        ("xkey", XKeyEvent),
        ("xbutton", XButtonEvent),
        ("xmotion", XMotionEvent),
        ("xdestroywindow", XDestroyWindowEvent),
        ("pad", c_long * 24),
    ]


#: Signature of an Xlib protocol error handler.
ERROR_HANDLER = CFUNCTYPE(c_int, Display, POINTER(XErrorEvent))

#: Signature of an Xlib fatal I/O error handler.
IO_ERROR_HANDLER = CFUNCTYPE(c_int, Display)


# --- function signatures -------------------------------------------------

#: ``name -> (argtypes, restype)`` for every Xlib function Step 4 uses.
#: Exposed so the test suite can assert that none of them is left with
#: ctypes' defaults.
FUNCTION_SIGNATURES: dict[str, tuple[list, object]] = {
    # Connection.
    "XOpenDisplay": ([c_char_p], Display),
    "XCloseDisplay": ([Display], c_int),
    "XDefaultScreen": ([Display], c_int),
    "XRootWindow": ([Display, c_int], Window),
    "XBlackPixel": ([Display, c_int], c_ulong),
    "XWhitePixel": ([Display, c_int], c_ulong),
    # Window lifetime.
    "XCreateSimpleWindow": (
        [Display, Window, c_int, c_int, c_uint, c_uint, c_uint, c_ulong, c_ulong],
        Window,
    ),
    "XMapWindow": ([Display, Window], c_int),
    "XDestroyWindow": ([Display, Window], c_int),
    # Properties and protocols.
    "XInternAtom": ([Display, c_char_p, Bool], Atom),
    "XSetWMProtocols": ([Display, Window, POINTER(Atom), c_int], c_int),
    "XStoreName": ([Display, Window, c_char_p], c_int),
    "XChangeProperty": (
        [Display, Window, Atom, Atom, c_int, c_int, c_char_p, c_int],
        c_int,
    ),
    # Drawing.
    "XDefaultVisual": ([Display, c_int], POINTER(Visual)),
    "XDefaultDepth": ([Display, c_int], c_int),
    "XDefaultGC": ([Display, c_int], c_void_p),
    "XCreateImage": (
        [Display, POINTER(Visual), c_uint, c_int, c_int, c_void_p,
         c_uint, c_uint, c_int, c_int],
        POINTER(XImage),
    ),
    "XPutImage": (
        [Display, Window, c_void_p, POINTER(XImage),
         c_int, c_int, c_int, c_int, c_uint, c_uint],
        c_int,
    ),
    "XDestroyImage": ([POINTER(XImage)], c_int),
    # Keyboard. A keycode is hardware-specific, so it is translated to a
    # keysym; index 0 is the unshifted meaning, which is what a canonical
    # key name should be.
    "XLookupKeysym": ([POINTER(XKeyEvent), c_int], c_ulong),
    # Auto-repeat. Holding a key down makes the server send a stream of
    # KeyRelease/KeyPress pairs, which would make a held key flicker between
    # held and not held. Asking for *detectable* auto-repeat means one
    # KeyRelease when the key really comes up, which is what held state needs.
    # Part of the Xkb client API, which lives in libX11 itself.
    "XkbSetDetectableAutoRepeat": ([Display, c_int, POINTER(c_int)], c_int),
    # Events.
    "XSelectInput": ([Display, Window, c_long], c_int),
    "XPending": ([Display], c_int),
    "XNextEvent": ([Display, POINTER(XEvent)], c_int),
    "XFlush": ([Display], c_int),
    "XSync": ([Display, Bool], c_int),
    # Error handlers.
    "XSetErrorHandler": ([ERROR_HANDLER], c_void_p),
    "XSetIOErrorHandler": ([IO_ERROR_HANDLER], c_void_p),
    # Used only to drive integration tests: XSendEvent synthesises the
    # WM_DELETE_WINDOW a window manager would send, XResizeWindow triggers a
    # real ConfigureNotify, and XGetWindowProperty reads a property back as
    # raw bytes. Declaring them here keeps every Xlib prototype in one audited
    # place rather than duplicated into a test.
    "XSendEvent": ([Display, Window, Bool, c_long, POINTER(XEvent)], c_int),
    "XResizeWindow": ([Display, Window, c_uint, c_uint], c_int),
    "XGetWindowProperty": (
        [Display, Window, Atom, c_long, c_long, Bool, Atom,
         POINTER(Atom), POINTER(c_int), POINTER(c_ulong), POINTER(c_ulong),
         POINTER(POINTER(c_ubyte))],
        c_int,
    ),
    "XFree": ([c_void_p], c_int),
}

#: The Xlib shared object. Resolved through ctypes' normal search first.
LIBRARY_NAME = "libX11.so.6"

_library = None


def load_xlib() -> ctypes.CDLL:
    """Load Xlib and apply every declared signature.

    Cached: the library is loaded once per process. Loading does not require a
    display, so this succeeds on a headless machine that merely has Xlib
    installed.

    Returns:
        The loaded library, with ``argtypes`` and ``restype`` set on every
        function in :data:`FUNCTION_SIGNATURES`.

    Raises:
        PlatformError: If Xlib is not present or cannot be loaded.
    """
    global _library
    if _library is not None:
        return _library

    path = ctypes.util.find_library("X11") or LIBRARY_NAME
    try:
        library = ctypes.CDLL(path)
    except OSError as exc:
        raise PlatformError(
            f"Could not load Xlib ({path}). TrjoLudus needs libX11 for its "
            f"Linux backend; install your distribution's libX11 package. "
            f"Underlying error: {exc}"
        ) from exc

    for name, (argtypes, restype) in FUNCTION_SIGNATURES.items():
        try:
            function = getattr(library, name)
        except AttributeError as exc:
            raise PlatformError(
                f"Xlib at {path} does not export {name}; it may be too old or "
                f"not a real libX11."
            ) from exc
        function.argtypes = argtypes
        function.restype = restype

    _library = library
    return library
