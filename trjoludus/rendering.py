"""Turning what a game says into pixels.

The system, not the implementation. Today the implementation is
:class:`trjoludus.rendering_python.Framebuffer` -- pure Python, one pixel
at a time -- and this module is where the choice between that and
a native one is made.

Rendering touches every pixel of every frame, so it is the first
place a native implementation is worth having, and the first that
``"auto"`` will prefer once one exists. Nothing about how a game
draws changes when it does: ``draw.rect(...)``, ``draw.text(...)``
and ``create.image(...)`` are the API either way.

**Backend.** ``rendering.engine`` chooses which implementation runs::

    rendering.engine = "auto"     # the default; a game need never set it
    rendering.engine = "rust"
    rendering.engine = "python"

See :mod:`trjoludus.native` for what those mean and when they take effect.
"""

from trjoludus.native import RUST, expose

__all__ = ["engine"]

#: What a game has asked for. Served by the module's own type, so that reading
#: it is live and writing something TrjoLudus does not know is refused.
engine: str

def _native_available() -> bool:
    """Whether the native renderer can actually start.

    Rendering needs every one of its functions in the library, not just the
    library's word that rendering is implemented -- so this subsystem says how
    to find out rather than leaving the resolver to know.

    The import is in here rather than at the top of the file on purpose:
    importing TrjoLudus must not load ``ctypes`` or open a library, and a
    game that never draws never asks this question.
    """
    from trjoludus.native import renderer

    return renderer.available()


_SYSTEM = expose(__name__, recommends=RUST,
                 python_implementation="trjoludus.rendering_python",
                 native_check=_native_available)


def create_framebuffer(width: int, height: int):
    """The frame buffer this game should draw into.

    Engine-internal: :class:`~trjoludus.app.Application` calls this once, when
    a run begins, and everything above it just draws. Which implementation
    comes back is the only place the choice is made, and the two are the same
    surface with the same pixels -- so nothing that holds one needs to know.

    Raises:
        EngineError: If a game asked for an implementation that is not there.
        RenderingError: If the native renderer is chosen but cannot start.
    """
    if _SYSTEM.resolve() == RUST:
        from trjoludus.native.renderer import NativeFramebuffer

        return NativeFramebuffer(width, height)

    from trjoludus.rendering_python import Framebuffer

    return Framebuffer(width, height)
