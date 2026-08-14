"""Playing a sequence of images as one moving thing.

An animation is a list of pictures with a name::

    player.animation.add("walk", ["walk_1.png", "walk_2.png",
                                  "walk_3.png", "walk_4.png"])

    player.animation.play("walk", fps=12, loop=True)

**Defining and playing are separate.** ``add`` says what the animation *is*,
once, and loads every frame so a missing file is found straight away rather
than halfway through a run. ``play`` says how it should run *this time* --
how fast, and whether it repeats -- because the same walk cycle may be played
at different speeds in different situations.

**Playing does not block.** ``play`` starts an animation and returns; the
engine advances it a little every frame, using how long the frame took. A game
carries on moving, reading input and drawing while it runs, and an animation
looks the same on a slow machine as on a fast one because it is measured in
seconds rather than in frames.

**Calling play again does nothing.** A game that plays "walk" every frame
while a key is held is saying "keep walking", not "start walking again", so
the second call is ignored -- otherwise the animation would sit on frame 1
forever. It warns once, in case that was not what was meant. Changing the
speed means stopping first::

    player.animation.stop("walk")
    player.animation.play("walk", fps=24)

**Nothing switches by itself.** TrjoLudus never decides that an object should
be idling or walking. A game says which animation is playing, and that is the
only thing that changes it.
"""

import warnings

from trjoludus.errors import TrjoLudusError, TrjoLudusWarning
from trjoludus.image import ImageError, load_image

__all__ = ["AnimationError", "Animator", "DEFAULT_FPS"]

#: Frames per second an animation runs at when ``play`` is not told otherwise.
#: Slow enough to read as animation rather than flicker, and a round number to
#: work from.
DEFAULT_FPS = 10.0


class AnimationError(TrjoLudusError):
    """Raised when an animation is defined wrongly, or asked for and absent."""


def _check_fps(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"fps must be a number, got {type(value).__name__}"
        )
    if value <= 0:
        raise ValueError(
            f"fps must be greater than zero, got {value}. An animation at "
            f"zero frames a second would never move."
        )
    return float(value)


class Animator:
    """The animations one object knows, and the one it is playing.

    Lives on the scene's record of an object rather than on a handle, so every
    :class:`~trjoludus.scene.GameObject` naming that object sees the same
    animations and the same playback -- including a handle made, used and
    thrown away in one expression.

    Games reach this through ``player.animation``, never directly.
    """

    __slots__ = ("_object", "_frames", "_current", "_index", "_since",
                 "_fps", "_loop", "_playing", "_finished", "_warned")

    def __init__(self, obj) -> None:
        self._object = obj
        #: name -> the loaded images, in order.
        self._frames: dict[str, tuple] = {}
        self._current: str | None = None
        self._index = 0
        self._since = 0.0
        self._fps = DEFAULT_FPS
        self._loop = True
        self._playing = False
        self._finished = False
        # What has already been complained about. Cleared whenever playback
        # actually changes, so the same mistake made again in a new situation
        # is still worth hearing about -- but making it every frame is not.
        self._warned: set = set()

    # --- what a game can read --------------------------------------------

    @property
    def current(self) -> "str | None":
        """The animation being played, paused on, or stopped on.

        ``None`` until something has been played. It stays set after an
        animation finishes, because the object is still showing that
        animation's last frame.
        """
        return self._current

    @property
    def is_playing(self) -> bool:
        """Whether an animation is advancing right now.

        ``False`` while paused, after :meth:`stop`, and once a non-looping
        animation has reached its end.
        """
        return self._playing

    @property
    def finished(self) -> bool:
        """Whether a non-looping animation has played all the way through.

        A looping animation is never finished. Playing anything again clears
        this.
        """
        return self._finished

    @property
    def names(self) -> tuple:
        """Every animation this object knows, in the order they were added."""
        return tuple(self._frames)

    def frames(self, name: str) -> int:
        """How many frames an animation has.

        Raises:
            AnimationError: If there is no animation with that name.
        """
        return len(self._require(name))

    @property
    def frame(self) -> int:
        """Which frame of the current animation is showing, counting from 1.

        ``0`` when nothing has been played.
        """
        return 0 if self._current is None else self._index + 1

    # --- defining ---------------------------------------------------------

    def add(self, name: str, frames) -> None:
        """Teach this object an animation.

        Every frame is loaded now, so a missing or damaged file is reported
        here -- where the list of frames is written and easy to fix -- rather
        than mid-game when the animation first reaches that frame.

        Args:
            name: What to call it. Must be unique for this object.
            frames: Paths to the images, in the order they should play. One
                frame is a perfectly good animation.

        Raises:
            TypeError: If ``name`` is not a string, or ``frames`` is not a
                list of paths.
            ValueError: If ``name`` is empty.
            AnimationError: If the name is taken, the list is empty, or a
                frame cannot be loaded.
        """
        if not isinstance(name, str):
            raise TypeError(
                f"an animation name must be a string, got "
                f"{type(name).__name__}"
            )
        if not name:
            raise ValueError("an animation needs a name; got an empty string")
        if name in self._frames:
            raise AnimationError(
                f"{self._object.name!r} already has an animation called "
                f"{name!r}. Every animation on an object needs its own "
                f"name -- pick a different one, or play the existing one."
            )
        if isinstance(frames, (str, bytes)):
            raise TypeError(
                "frames must be a list of image paths, not a single path. "
                f'For one frame, write ["{frames}"].'
            )
        try:
            paths = list(frames)
        except TypeError:
            raise TypeError(
                f"frames must be a list of image paths, got "
                f"{type(frames).__name__}"
            ) from None
        if not paths:
            raise AnimationError(
                f"the animation {name!r} has no frames. An animation needs at "
                f"least one image to show."
            )

        loaded = []
        for position, path in enumerate(paths, start=1):
            try:
                loaded.append(load_image(path))
            except ImageError as error:
                raise AnimationError(
                    f"frame {position} of the animation {name!r} could not be "
                    f"loaded: {error} Check that the file exists, that the "
                    f"path is spelled the way the file is, and that it is a "
                    f"PNG."
                ) from error
        self._frames[name] = tuple(loaded)

    def _require(self, name: str) -> tuple:
        if not isinstance(name, str):
            raise TypeError(
                f"an animation name must be a string, got "
                f"{type(name).__name__}"
            )
        try:
            return self._frames[name]
        except KeyError:
            if not self._frames:
                raise AnimationError(
                    f"{self._object.name!r} has no animation called {name!r}: "
                    f"it has no animations at all yet. Add one with "
                    f'animation.add("{name}", [...]).'
                ) from None
            known = ", ".join(repr(other) for other in self._frames)
            raise AnimationError(
                f"{self._object.name!r} has no animation called {name!r}. "
                f"It knows: {known}."
            ) from None

    # --- playing ----------------------------------------------------------

    def play(self, name: str, fps=DEFAULT_FPS, loop: bool = True) -> None:
        """Start an animation, or carry on if it is already running.

        Playing something already playing is ignored, settings and all: a game
        saying ``play("walk")`` every frame while a key is held means "keep
        walking", and restarting would leave the animation stuck on frame 1.
        Stop it first to change how it plays.

        Playing a *different* animation replaces the current one and starts it
        from its first frame, which is how a game switches from walking to
        jumping.

        Args:
            name: Which animation to play.
            fps: Frames per second. Defaults to :data:`DEFAULT_FPS`.
            loop: Whether to start again at the end. When ``False`` the
                animation plays once and stays on its last frame.

        Raises:
            AnimationError: If there is no animation with that name.
            TypeError: If ``fps`` is not a number or ``loop`` is not a bool.
            ValueError: If ``fps`` is not greater than zero.
        """
        frames = self._require(name)
        rate = _check_fps(fps)
        if not isinstance(loop, bool):
            raise TypeError(
                f"loop must be True or False, got {type(loop).__name__}"
            )

        if self._playing and self._current == name:
            self._warn(
                ("playing", name),
                f"{name!r} is already playing on {self._object.name!r}, so "
                f"this play() was ignored -- including any fps or loop given "
                f"with it. That is usually what you want when play() is "
                f"called every frame. To change how it plays, stop it first.",
            )
            return

        self._current = name
        self._fps = rate
        self._loop = loop
        self._index = 0
        self._since = 0.0
        self._playing = True
        self._finished = False
        self._warned.clear()
        self._show(frames[0])

    def pause(self, name: str) -> None:
        """Freeze an animation on the frame it is showing.

        Raises:
            AnimationError: If there is no animation with that name.
        """
        self._require(name)
        if not self._playing or self._current != name:
            self._warn(
                ("pause", name),
                f"{name!r} is not playing on {self._object.name!r}, so there "
                f"was nothing to pause.",
            )
            return
        self._playing = False
        self._warned.clear()

    def resume(self, name: str) -> None:
        """Carry on from the frame :meth:`pause` stopped at.

        Raises:
            AnimationError: If there is no animation with that name.
        """
        self._require(name)
        if self._current != name or self._playing or self._finished:
            self._warn(
                ("resume", name),
                f"{name!r} is not paused on {self._object.name!r}, so there "
                f"was nothing to resume. Use play() to start it.",
            )
            return
        self._playing = True
        self._warned.clear()

    def stop(self, name: str) -> None:
        """Stop an animation, leaving the object on the frame it reached.

        Stopping something that is not playing warns rather than raising: it
        means the game's idea of what was running was wrong, which is worth
        knowing but not worth ending the game over.

        Raises:
            AnimationError: If there is no animation with that name.
        """
        self._require(name)
        if not self._playing or self._current != name:
            self._warn(
                ("stop", name),
                f"{name!r} is not playing on {self._object.name!r}, so there "
                f"was nothing to stop."
                + (f" {self._current!r} is." if self._playing else ""),
            )
            return
        self._playing = False
        self._warned.clear()

    def advance(self, seconds: float) -> None:
        """Move the animation on by however long the frame took.

        Called by the engine once a frame. A frame that took long enough to
        cover several animation frames advances several, so an animation that
        stutters still takes the time it should overall rather than playing in
        slow motion.
        """
        if not self._playing or self._current is None:
            return
        frames = self._frames[self._current]
        if len(frames) == 1:
            # One frame is a valid animation. There is nothing to advance to,
            # and a non-looping one is done as soon as it has been shown.
            if not self._loop:
                self._playing = False
                self._finished = True
            return

        self._since += seconds
        period = 1.0 / self._fps
        while self._since >= period:
            self._since -= period
            self._index += 1
            if self._index >= len(frames):
                if self._loop:
                    self._index = 0
                else:
                    self._index = len(frames) - 1
                    self._playing = False
                    self._finished = True
                    self._since = 0.0
                    break
        self._show(frames[self._index])

    # --- the image behind it ----------------------------------------------

    def _show(self, image) -> None:
        """Put one frame on the object.

        Only the image changes. Position and scale belong to the object and
        are none of an animation's business.
        """
        self._object.image = image

    def replaced_by_hand(self) -> None:
        """Called when a game sets the object's image itself.

        An animation would overwrite that image on its next frame, so the two
        cannot both be in charge. The image a game asked for wins, and the
        animation stops -- with a warning, because a game that did not realise
        something was playing would otherwise see its image quietly ignored.
        """
        if not self._playing:
            return
        name = self._current
        self._playing = False
        self._warn(
            ("replaced", name),
            f"set.image() stopped the animation {name!r} on "
            f"{self._object.name!r}. An animation and a hand-picked image "
            f"cannot both decide what is drawn, so the image you set wins. "
            f"Play it again if you want the animation back.",
        )

    def _warn(self, key, message: str) -> None:
        """Say something once, rather than every frame.

        These all come from things a game does repeatedly -- playing every
        frame while a key is held, setting an image every update -- so the
        same complaint would arrive sixty times a second. It is remembered
        until playback actually changes, and then it is worth hearing again.
        """
        if key in self._warned:
            return
        self._warned.add(key)
        warnings.warn(message, TrjoLudusWarning, stacklevel=4)

    def __repr__(self) -> str:
        state = "playing" if self._playing else "stopped"
        return (f"Animator({self._object.name!r}, {len(self._frames)} "
                f"animations, {self._current!r} {state})")
