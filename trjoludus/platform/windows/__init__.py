"""Windows platform backend.

Win32 through ctypes, using the wide-character APIs throughout.

Importing this package does not load user32 or kernel32; that happens when a
:class:`~trjoludus.platform.windows.win32.Win32Backend` is constructed, so the
module can be imported and inspected on any platform.
"""

from trjoludus.platform.windows.win32 import Win32Backend, Win32Window

__all__ = ["Win32Backend", "Win32Window"]
