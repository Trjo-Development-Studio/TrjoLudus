"""Platform detection and backend selection.

This package is the *only* place in TrjoLudus that is allowed to know which
operating system the engine is running on, or to talk to OS libraries. Every
other subsystem must go through the interfaces defined here.

Choosing a backend resolves in this order:

1. an explicit name passed to :func:`create_backend`
2. the ``TRJOLUDUS_BACKEND`` environment variable
3. the default for the host platform

Backend modules are imported inside :func:`create_backend`, never at module
level, so importing ``trjoludus`` neither loads ``ctypes`` nor opens a display.
"""

import os
import sys
from enum import Enum

from trjoludus.errors import PlatformError, UnsupportedPlatformError

__all__ = [
    "BACKEND_ENV_VAR",
    "BACKEND_NAMES",
    "PlatformName",
    "create_backend",
    "detect_platform",
    "resolve_backend_name",
]

#: Environment variable that overrides backend selection.
BACKEND_ENV_VAR = "TRJOLUDUS_BACKEND"

#: Every backend name that can be requested.
BACKEND_NAMES = ("x11", "null")


class PlatformName(Enum):
    """An operating system supported by TrjoLudus."""

    WINDOWS = "windows"
    LINUX = "linux"

    def __str__(self) -> str:
        return self.value


def detect_platform() -> PlatformName:
    """Return the :class:`PlatformName` for the host operating system.

    Raises:
        UnsupportedPlatformError: if the host is not Windows or Linux.
    """
    if sys.platform == "win32":
        return PlatformName.WINDOWS
    if sys.platform.startswith("linux"):
        return PlatformName.LINUX
    raise UnsupportedPlatformError(
        f"TrjoLudus supports Windows and Linux; got sys.platform={sys.platform!r}."
    )


#: The backend each platform uses when nothing overrides it. Windows is absent
#: on purpose: its backend does not exist yet, and defaulting it to something
#: else would fail further from the cause.
_PLATFORM_DEFAULTS = {PlatformName.LINUX: "x11"}


def resolve_backend_name(name: str | None = None) -> str:
    """Decide which backend to use, without constructing anything.

    Separate from :func:`create_backend` so the decision can be tested without
    a display.

    Args:
        name: An explicit backend name, which wins over everything else.

    Returns:
        One of :data:`BACKEND_NAMES`.

    Raises:
        PlatformError: If the requested name is unknown, or if the host
            platform has no backend yet.
        UnsupportedPlatformError: If the host is neither Windows nor Linux.
    """
    requested = name or os.environ.get(BACKEND_ENV_VAR) or None

    if requested is not None:
        if requested not in BACKEND_NAMES:
            raise PlatformError(
                f"Unknown backend {requested!r}. "
                f"Available backends: {', '.join(BACKEND_NAMES)}."
            )
        return requested

    platform = detect_platform()
    try:
        return _PLATFORM_DEFAULTS[platform]
    except KeyError:
        raise PlatformError(
            f"TrjoLudus has no backend for {platform} yet. Set "
            f"{BACKEND_ENV_VAR}=null to run headless in the meantime."
        ) from None


def create_backend(name: str | None = None):
    """Create the backend for this platform.

    Backend modules are imported here rather than at module level, so that
    importing ``trjoludus`` pulls in no ``ctypes`` and opens no display.

    Args:
        name: An explicit backend name. Defaults to
            :func:`resolve_backend_name`.

    Returns:
        A ready :class:`~trjoludus.platform.base.PlatformBackend`.

    Raises:
        PlatformError: If the backend is unknown, unavailable on this
            platform, or cannot start -- for example when no X display can be
            opened.
    """
    resolved = resolve_backend_name(name)

    if resolved == "null":
        from trjoludus.platform.null import NullBackend

        return NullBackend()

    if resolved == "x11":
        from trjoludus.platform.linux.x11 import X11Backend

        return X11Backend()

    raise PlatformError(  # pragma: no cover -- resolve_backend_name guards this
        f"Backend {resolved!r} is named but not wired up."
    )
