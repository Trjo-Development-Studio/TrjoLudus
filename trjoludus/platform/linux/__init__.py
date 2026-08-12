"""Linux platform backends.

Xlib is the initial Linux backend, reached through Xwayland on a Wayland
session. A native Wayland backend is expected to live alongside it later,
behind the same contracts.

Importing this package does not open a display or load Xlib; both happen when
an :class:`~trjoludus.platform.linux.x11.X11Backend` is constructed.
"""

from trjoludus.platform.linux.x11 import X11Backend, X11Window

__all__ = ["X11Backend", "X11Window"]
