"""Tests for the per-subsystem backend architecture.

Milestone 3.0 is architecture rather than behaviour, so these check the rules
that architecture is made of: every subsystem defaults to ``"auto"``, an
explicit choice is never quietly replaced by the other one, one subsystem's
setting cannot move another's, and a game that never mentions ``.engine``
works exactly as it did.

**Nothing here fakes a native library to make a test pass.** The real state of
this checkout is that no native library is built, so that is what the
unavailable path is tested against. The available path is tested by loading a
*stand-in* library object into the loader -- not a stub implementation of a
subsystem, just something that answers the two discovery functions -- so that
"auto prefers Rust" can be checked at all.
"""

import pathlib
import unittest

from trjoludus import (
    ai,
    animation,
    audio,
    collision,
    image,
    pathfinding,
    physics,
    rendering,
)
from trjoludus import Game
from trjoludus.app import Application
from trjoludus.native import (
    AUTO,
    PYTHON,
    RUST,
    EngineError,
    library,
    registry,
    renderer,
)
from trjoludus.platform.null import NullBackend

#: What each subsystem recommends. Only subsystems that exist get one; a
#: recommendation is not invented for a system nobody has written.
RECOMMENDATIONS = {
    "rendering": "rust",
    "image": "rust",
    "animation": "python",
    "collision": "python",
    "physics": None,
    "ai": None,
    "pathfinding": None,
    "audio": None,
}

MODULES = {
    "rendering": rendering, "image": image, "collision": collision,
    "physics": physics, "ai": ai, "pathfinding": pathfinding,
    "animation": animation, "audio": audio,
}

#: Where the package is, and where the repository is if this is a checkout.
PACKAGE_ROOT = pathlib.Path(
    __import__("trjoludus").__file__).parent
REPOSITORY = PACKAGE_ROOT.parent


class PretendLibrary:
    """Answers the two discovery functions, and implements nothing.

    Not a stub subsystem: it cannot render or collide anything. It exists so
    that the *decision* "a native implementation is available" can be tested
    for subsystems that have no native implementation at all.

    It deliberately cannot stand in for rendering. Rendering now asks its
    binding whether the library really has the functions, so a stand-in that
    only says the word "rendering" is correctly judged unavailable -- which is
    the behaviour that stops a half-built library failing on the first frame.
    """

    def __init__(self, implements=(), abi=library.ABI_VERSION):
        self._implements = set(implements)
        self._abi = abi

    def trjoludus_abi_version(self):
        return self._abi

    def trjoludus_implements(self, name):
        return int(name.decode("ascii") in self._implements)


class BackendTestCase(unittest.TestCase):
    def setUp(self):
        registry.reset()
        library.forget()
        renderer.forget()
        from trjoludus.native import imaging
        imaging.forget()
        self.addCleanup(imaging.forget)
        self.addCleanup(renderer.forget)
        self.addCleanup(library.forget)
        self.addCleanup(registry.reset)

    def pretend(self, *names):
        """Answer as though a library implementing these names existed."""
        library._library = PretendLibrary(names)
        library._problem = None
        renderer.forget()
        from trjoludus.native import imaging
        imaging.forget()

    def pretend_nothing(self):
        """Make the loader answer as if there were no library at all."""
        library._library = None
        library._problem = "no native library found (test)"
        renderer.forget()
        from trjoludus.native import imaging
        imaging.forget()


class TestDefaults(BackendTestCase):
    def test_every_subsystem_defaults_to_auto(self):
        for name, module in MODULES.items():
            with self.subTest(system=name):
                self.assertEqual(module.engine, AUTO)

    def test_the_registry_knows_every_subsystem(self):
        self.assertEqual(
            {found.name for found in registry.systems()},
            set(RECOMMENDATIONS),
        )

    def test_each_subsystem_recommends_what_it_should(self):
        for name, expected in RECOMMENDATIONS.items():
            with self.subTest(system=name):
                self.assertEqual(registry.system(name).recommends, expected)

    def test_the_migrated_subsystems_recommend_rust(self):
        self.assertEqual(registry.system("rendering").recommends, RUST)
        self.assertEqual(registry.system("image").recommends, RUST)

    def test_the_python_subsystems_recommend_python(self):
        self.assertEqual(registry.system("animation").recommends, PYTHON)
        self.assertEqual(registry.system("collision").recommends, PYTHON)

    def test_nothing_unwritten_recommends_anything(self):
        """A recommendation is for a subsystem that exists."""
        for name in ("physics", "ai", "pathfinding", "audio"):
            with self.subTest(system=name):
                self.assertIsNone(registry.system(name).recommends)

    def test_a_recommendation_must_be_a_backend_or_nothing(self):
        with self.assertRaises(ValueError):
            registry.System("nonsense", recommends="c++",
                            python_implementation=None)

    def test_a_game_never_has_to_mention_engine(self):
        """The whole point: normal use requires no configuration."""
        played = []

        class G(Game):
            def on_update(self, dt):
                played.append(rendering.engine)
                self.quit()

        Application(G(), size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        self.assertEqual(played, [AUTO])


class TestValidValues(BackendTestCase):
    def test_the_three_choices_are_accepted(self):
        for value in (AUTO, RUST, PYTHON):
            with self.subTest(value=value):
                rendering.engine = value
                self.assertEqual(rendering.engine, value)

    def test_the_choices_are_what_they_should_be(self):
        self.assertEqual(registry.CHOICES, ("auto", "rust", "python"))

    def test_an_unknown_value_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            rendering.engine = "c++"
        message = str(caught.exception)
        self.assertIn("not a backend TrjoLudus knows", message)
        self.assertIn("'auto'", message)
        self.assertEqual(rendering.engine, AUTO, "the bad value was kept")

    def test_case_matters(self):
        for value in ("Rust", "RUST", "Python", "Auto"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    rendering.engine = value

    def test_a_non_string_is_refused(self):
        for value in (1, None, True, ["rust"]):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    physics.engine = value

    def test_the_error_names_the_system(self):
        with self.assertRaises(ValueError) as caught:
            pathfinding.engine = "fortran"
        self.assertIn("pathfinding.engine", str(caught.exception))

    def test_reading_something_else_from_a_system_module_still_fails(self):
        with self.assertRaises(AttributeError):
            rendering.nonsense


class TestWithNoNativeLibrary(BackendTestCase):
    """The real state of this checkout: nothing is built."""

    def setUp(self):
        super().setUp()
        self.pretend_nothing()

    def test_nothing_is_available(self):
        for name in MODULES:
            with self.subTest(system=name):
                self.assertFalse(registry.system(name).native_available())

    def test_auto_falls_back_to_python(self):
        for name in ("rendering", "image", "animation"):
            with self.subTest(system=name):
                self.assertEqual(registry.system(name).resolve(), PYTHON)

    def test_asking_for_rust_is_an_error_not_a_fallback(self):
        rendering.engine = RUST
        with self.assertRaises(EngineError) as caught:
            registry.system("rendering").resolve()
        message = str(caught.exception)
        self.assertIn("rendering", message)
        self.assertIn("no native implementation", message)

    def test_the_error_says_where_to_look(self):
        physics.engine = RUST
        with self.assertRaises(EngineError) as caught:
            registry.system("physics").resolve()
        self.assertIn("rust/README.md", str(caught.exception))

    def test_asking_for_python_works_where_there_is_python(self):
        for name in ("rendering", "image", "animation"):
            with self.subTest(system=name):
                MODULES[name].engine = PYTHON
                self.assertEqual(registry.system(name).resolve(), PYTHON)

    def test_a_system_with_no_implementation_at_all_says_so(self):
        for name in ("physics", "ai", "pathfinding", "audio"):
            with self.subTest(system=name):
                with self.assertRaises(EngineError) as caught:
                    registry.system(name).resolve()
                message = str(caught.exception)
                self.assertIn("no implementation", message)
                self.assertIn(name, message)

    def test_asking_such_a_system_for_python_says_so_too(self):
        physics.engine = PYTHON
        with self.assertRaises(EngineError) as caught:
            registry.system("physics").resolve()
        self.assertIn("no Python implementation", str(caught.exception))

    def test_asking_for_python_never_gives_rust(self):
        """Explicit means explicit, in both directions."""
        physics.engine = PYTHON
        with self.assertRaises(EngineError):
            registry.system("physics").resolve()

    def test_a_python_only_system_resolves_to_python(self):
        """Collision has an implementation now, and it is Python's."""
        self.assertEqual(registry.system("collision").resolve(), PYTHON)

    def test_asking_a_python_only_system_for_rust_says_there_is_none(self):
        collision.engine = RUST
        with self.assertRaises(EngineError) as caught:
            registry.system("collision").resolve()
        self.assertIn("no native implementation", str(caught.exception))


class TestWithANativeLibrary(BackendTestCase):
    def test_auto_prefers_the_native_one_where_it_is_recommended(self):
        """Rendering recommends native, so auto takes it when it is there."""
        if not renderer.available():
            self.skipTest("no native renderer built here")
        library.forget()
        self.assertEqual(registry.system("rendering").resolve(), RUST)

    def test_a_library_that_only_says_the_word_is_not_enough(self):
        """A stand-in claiming rendering, with no functions, is refused."""
        self.pretend("rendering")
        self.assertFalse(registry.system("rendering").native_available())
        rendering.engine = RUST
        with self.assertRaises(EngineError):
            registry.system("rendering").resolve()

    def test_auto_leaves_python_recommended_systems_on_python(self):
        """"auto" must not sweep a system into Rust just because it can."""
        self.pretend("animation")
        self.assertTrue(registry.system("animation").native_available())
        self.assertEqual(registry.system("animation").resolve(), PYTHON)

    def test_a_python_recommended_system_can_still_be_asked_for_rust(self):
        self.pretend("animation")
        animation.engine = RUST
        self.assertEqual(registry.system("animation").resolve(), RUST)

    def test_python_is_honoured_even_when_rust_is_there(self):
        self.pretend("rendering")
        rendering.engine = PYTHON
        self.assertEqual(registry.system("rendering").resolve(), PYTHON)

    def test_availability_is_per_system(self):
        self.pretend("animation")
        self.assertTrue(registry.system("animation").native_available())
        self.assertFalse(registry.system("physics").native_available())

    def test_a_system_the_library_does_not_implement_still_errors(self):
        self.pretend("animation")
        physics.engine = RUST
        with self.assertRaises(EngineError) as caught:
            registry.system("physics").resolve()
        self.assertIn("does not implement it yet", str(caught.exception))

    def test_auto_is_not_a_coin_toss(self):
        """The same question must give the same answer every time."""
        self.pretend("animation")
        animation.engine = RUST
        answers = {registry.system("animation").resolve() for _ in range(50)}
        self.assertEqual(answers, {RUST})


class TestSystemsAreIndependent(BackendTestCase):
    def test_setting_one_does_not_move_the_others(self):
        rendering.engine = RUST
        for name, module in MODULES.items():
            if name == "rendering":
                continue
            with self.subTest(system=name):
                self.assertEqual(module.engine, AUTO)

    def test_the_other_way_round_too(self):
        physics.engine = PYTHON
        self.assertEqual(rendering.engine, AUTO)
        self.assertEqual(ai.engine, AUTO)
        self.assertEqual(animation.engine, AUTO)

    def test_every_pair_is_independent(self):
        for name, module in MODULES.items():
            with self.subTest(system=name):
                registry.reset()
                module.engine = RUST
                for other_name, other in MODULES.items():
                    if other_name == name:
                        continue
                    self.assertEqual(other.engine, AUTO,
                                     f"{name} moved {other_name}")

    def test_a_mixed_configuration_is_valid(self):
        rendering.engine = RUST
        physics.engine = PYTHON
        self.assertEqual(rendering.engine, RUST)
        self.assertEqual(physics.engine, PYTHON)
        self.assertEqual(ai.engine, AUTO)

    def test_two_systems_cannot_share_a_registration(self):
        self.assertIsNot(registry.system("rendering"),
                         registry.system("image"))

    def test_registering_a_name_twice_is_refused(self):
        with self.assertRaises(EngineError):
            registry.register("rendering", recommends=RUST,
                              python_implementation=None)

    def test_asking_for_a_system_that_does_not_exist(self):
        with self.assertRaises(EngineError) as caught:
            registry.system("teleportation")
        self.assertIn("no subsystem called", str(caught.exception))


class TestConfigurationTiming(BackendTestCase):
    def test_it_can_be_set_before_a_run(self):
        seen = []

        class G(Game):
            def on_update(self, dt):
                seen.append(rendering.engine)
                self.quit()

        rendering.engine = PYTHON
        Application(G(), size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        self.assertEqual(seen, [PYTHON])

    def test_changing_it_during_a_run_is_refused(self):
        errors = []

        class G(Game):
            def on_update(self, dt):
                try:
                    rendering.engine = PYTHON
                except EngineError as error:
                    errors.append(str(error))
                self.quit()

        Application(G(), size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        self.assertEqual(len(errors), 1)
        self.assertIn("cannot be changed while a game is running", errors[0])
        self.assertIn("Set it before run()", errors[0])

    def test_setting_it_to_what_it_already_is_is_harmless(self):
        """Not a change, so not a half-switched subsystem."""
        errors = []

        class G(Game):
            def on_update(self, dt):
                try:
                    rendering.engine = AUTO
                except EngineError as error:
                    errors.append(error)
                self.quit()

        Application(G(), size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        self.assertEqual(errors, [])

    def test_a_setting_survives_into_the_next_run(self):
        """It is a statement about the program, not about one game."""
        seen = []

        class G(Game):
            def on_update(self, dt):
                seen.append(rendering.engine)
                self.quit()

        rendering.engine = PYTHON
        game = G()
        for _ in range(2):
            Application(game, size=(40, 30), max_fps=None,
                        backend=NullBackend()).run()
        self.assertEqual(seen, [PYTHON, PYTHON])

    def test_a_change_between_runs_takes_effect(self):
        seen = []

        class G(Game):
            def on_update(self, dt):
                seen.append(rendering.engine)
                self.quit()

        game = G()
        Application(game, size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        rendering.engine = PYTHON
        Application(game, size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        self.assertEqual(seen, [AUTO, PYTHON])

    def test_no_resolution_is_cached_across_runs(self):
        """A run leaves no decision behind for a later change to miss."""
        self.pretend("animation")
        animation.engine = RUST
        self.assertEqual(registry.system("animation").resolve(), RUST)
        self.pretend_nothing()
        animation.engine = AUTO
        self.assertEqual(registry.system("animation").resolve(), PYTHON)


class TestSettingsPersist(BackendTestCase):
    """A choice lasts until the developer changes it, and no longer."""

    def test_a_new_game_instance_does_not_reset_it(self):
        # PYTHON rather than RUST: this is about a setting surviving a run,
        # and rendering now actually uses the setting -- asking for a renderer
        # that may not be built here would be testing something else.
        rendering.engine = PYTHON

        class First(Game):
            def on_update(self, dt):
                self.quit()

        class Second(Game):
            def on_update(self, dt):
                self.quit()

        Application(First(), size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        self.assertEqual(rendering.engine, PYTHON)
        Application(Second(), size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        self.assertEqual(rendering.engine, PYTHON,
                         "a new Game instance reset the configuration")

    def test_constructing_an_application_does_not_reset_it(self):
        physics.engine = PYTHON
        Application(Game(), size=(40, 30), max_fps=None,
                    backend=NullBackend())
        self.assertEqual(physics.engine, PYTHON)

    def test_a_run_that_raised_does_not_reset_it(self):
        image.engine = PYTHON

        class Breaking(Game):
            def on_update(self, dt):
                raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            Application(Breaking(), size=(40, 30), max_fps=None,
                        backend=NullBackend()).run()
        self.assertEqual(image.engine, PYTHON)

    def test_several_runs_keep_every_setting(self):
        rendering.engine = PYTHON
        animation.engine = RUST      # nothing resolves animation in a run
        physics.engine = PYTHON

        class G(Game):
            def on_update(self, dt):
                self.quit()

        game = G()
        for _ in range(3):
            Application(game, size=(40, 30), max_fps=None,
                        backend=NullBackend()).run()
        self.assertEqual(
            (rendering.engine, animation.engine, physics.engine),
            (PYTHON, RUST, PYTHON),
        )

    def test_nothing_in_the_engine_writes_a_setting(self):
        """Only a developer sets these; the engine only reads them."""
        import ast
        import pathlib as _pathlib

        root = _pathlib.Path(__file__).parent.parent / "trjoludus"
        writers = []
        for path in sorted(root.rglob("*.py")):
            if path.parent.name == "native":
                continue          # the registry is where the value lives
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (isinstance(target, ast.Attribute)
                                and target.attr == "engine"):
                            writers.append(path.name)
        self.assertEqual(writers, [], "the engine assigns to a .engine")

    def test_availability_is_asked_again_each_time(self):
        """A resolver that cached would answer for a library long gone."""
        self.pretend("animation")
        self.assertTrue(registry.system("animation").native_available())
        self.pretend_nothing()
        self.assertFalse(registry.system("animation").native_available())
        self.pretend("animation")
        self.assertTrue(registry.system("animation").native_available())


class TestTheWildcardImport(BackendTestCase):
    """``from trjoludus import *`` is the whole public API and no more."""

    def star_import(self):
        namespace = {}
        exec("from trjoludus import *", namespace)
        namespace.pop("__builtins__", None)
        return namespace

    def test_it_gives_exactly_what_is_public(self):
        import trjoludus

        self.assertEqual(set(self.star_import()), set(trjoludus.__all__))

    def test_everything_a_game_needs_is_there(self):
        names = self.star_import()
        for needed in ("Game", "run", "create", "draw", "color", "keyboard",
                       "mouse", "input", "key", "time", "GameObject"):
            with self.subTest(name=needed):
                self.assertIn(needed, names)

    def test_no_internals_come_with_it(self):
        names = self.star_import()
        for internal in ("Framebuffer", "Scene", "Clock", "Animator",
                         "System", "library", "registry", "expose",
                         "native", "ctypes", "MouseState", "KeyboardState",
                         "PendingInput"):
            with self.subTest(name=internal):
                self.assertNotIn(internal, names)

    def test_no_name_speaks_of_the_implementation(self):
        for name in self.star_import():
            with self.subTest(name=name):
                lowered = name.lower()
                for word in ("rust", "ffi", "native", "cdll", "ctypes",
                             "pointer", "handle", "abi"):
                    self.assertNotIn(word, lowered)

    def test_nothing_exported_is_a_ctypes_object(self):
        import ctypes

        for name, value in self.star_import().items():
            with self.subTest(name=name):
                self.assertNotIsInstance(value, ctypes.CDLL)
                self.assertFalse(
                    type(value).__module__.startswith("ctypes"),
                    f"{name} is a ctypes object",
                )

    def test_the_subsystem_modules_come_with_it(self):
        names = self.star_import()
        for system_name in MODULES:
            with self.subTest(system=system_name):
                self.assertIn(system_name, names)
                self.assertEqual(names[system_name].engine, AUTO)


class TestTheLibraryLoader(BackendTestCase):
    """The real loader, pointed at directories these tests control.

    Not at whatever the developer happens to have built.
    ``TRJOLUDUS_NATIVE_DIR`` is what makes "there is a library" and "there is
    not" both reachable on purpose, so the suite gives the same answer before
    and after someone runs cargo.
    """

    def look_in(self, folder):
        """Point the loader at a directory for the rest of this test."""
        import os

        previous = os.environ.get(library.DIRECTORY_VARIABLE)
        os.environ[library.DIRECTORY_VARIABLE] = str(folder)
        library.forget()

        def restore():
            if previous is None:
                os.environ.pop(library.DIRECTORY_VARIABLE, None)
            else:
                os.environ[library.DIRECTORY_VARIABLE] = previous
            library.forget()

        self.addCleanup(restore)

    def empty_directory(self):
        import tempfile

        folder = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, folder, True)
        return pathlib.Path(folder)

    def a_real_library(self):
        """A compiled library to test against, from wherever one exists."""
        for folder in (PACKAGE_ROOT / "native" / "lib",
                       REPOSITORY / "rust" / "target" / "release",
                       REPOSITORY / "rust" / "target" / "debug"):
            for name in library.LIBRARY_NAMES:
                candidate = folder / name
                if candidate.is_file():
                    return candidate
        return None

    # --- with nothing there ----------------------------------------------

    def test_an_empty_directory_means_no_library(self):
        self.look_in(self.empty_directory())
        self.assertFalse(library.loaded())
        self.assertIsNone(library.version())
        self.assertIsNone(library.library_path())
        self.assertIn("no native library found", library.problem())

    def test_nothing_is_available_then(self):
        self.look_in(self.empty_directory())
        for name in MODULES:
            with self.subTest(system=name):
                self.assertFalse(registry.system(name).native_available())

    def test_auto_falls_back_and_explicit_rust_does_not(self):
        self.look_in(self.empty_directory())
        self.assertEqual(registry.system("rendering").resolve(), PYTHON)
        rendering.engine = RUST
        with self.assertRaises(EngineError):
            registry.system("rendering").resolve()

    def test_a_directory_that_does_not_exist_is_harmless(self):
        self.look_in(self.empty_directory() / "nowhere")
        self.assertFalse(library.loaded())
        self.assertIn("no native library found", library.problem())

    # --- with something broken there --------------------------------------

    def test_a_file_that_is_not_a_library_is_refused(self):
        folder = self.empty_directory()
        (folder / library.LIBRARY_NAMES[0]).write_bytes(b"not a shared object")
        self.look_in(folder)
        self.assertFalse(library.loaded())
        self.assertIn("could not be loaded", library.problem())

    def test_an_empty_file_is_refused(self):
        folder = self.empty_directory()
        (folder / library.LIBRARY_NAMES[0]).write_bytes(b"")
        self.look_in(folder)
        self.assertFalse(library.loaded())
        self.assertIsNotNone(library.problem())

    def test_a_broken_library_does_not_pretend_rust_is_there(self):
        folder = self.empty_directory()
        (folder / library.LIBRARY_NAMES[0]).write_bytes(b"rubbish")
        self.look_in(folder)
        self.assertFalse(library.implements("rendering"))
        rendering.engine = RUST
        with self.assertRaises(EngineError):
            registry.system("rendering").resolve()

    # --- with a real one there --------------------------------------------

    def test_a_real_library_loads(self):
        found = self.a_real_library()
        if found is None:
            self.skipTest("no compiled library anywhere; run cargo build")
        self.look_in(found.parent)
        self.assertTrue(library.loaded(), library.problem())
        self.assertEqual(library.version(), library.ABI_VERSION)
        self.assertIsNone(library.problem())
        self.assertEqual(library.library_path(), found)

    #: The subsystems that have actually been migrated, in order.
    MIGRATED = ("rendering", "image")

    def test_a_real_library_implements_only_what_has_been_migrated(self):
        found = self.a_real_library()
        if found is None:
            self.skipTest("no compiled library anywhere; run cargo build")
        self.look_in(found.parent)
        for name in self.MIGRATED:
            with self.subTest(system=name):
                self.assertTrue(library.implements(name))
        for name in MODULES:
            if name in self.MIGRATED:
                continue
            with self.subTest(system=name):
                self.assertFalse(
                    library.implements(name),
                    f"the native library claims to implement {name}, but it "
                    f"has not been migrated",
                )

    def test_a_real_library_puts_auto_on_rust_for_rendering(self):
        found = self.a_real_library()
        if found is None:
            self.skipTest("no compiled library anywhere; run cargo build")
        self.look_in(found.parent)
        renderer.forget()
        self.assertEqual(registry.system("rendering").resolve(), RUST)

    def test_auto_takes_rust_for_image_too(self):
        found = self.a_real_library()
        if found is None:
            self.skipTest("no compiled library anywhere; run cargo build")
        self.look_in(found.parent)
        from trjoludus.native import imaging

        imaging.forget()
        self.assertEqual(registry.system("image").resolve(), RUST)

    def test_auto_still_leaves_unmigrated_systems_on_python(self):
        found = self.a_real_library()
        if found is None:
            self.skipTest("no compiled library anywhere; run cargo build")
        self.look_in(found.parent)
        self.assertEqual(registry.system("animation").resolve(), PYTHON)

    def test_explicit_rust_for_an_unmigrated_system_says_so(self):
        found = self.a_real_library()
        if found is None:
            self.skipTest("no compiled library anywhere; run cargo build")
        self.look_in(found.parent)
        physics.engine = RUST
        with self.assertRaises(EngineError) as caught:
            registry.system("physics").resolve()
        message = str(caught.exception)
        self.assertIn("does not implement it yet", message)
        self.assertNotIn("not built", message)

    # --- where it looks ----------------------------------------------------

    def test_it_looks_inside_the_package(self):
        import os

        os.environ.pop(library.DIRECTORY_VARIABLE, None)
        self.assertEqual(library.search_directory(),
                         PACKAGE_ROOT / "native" / "lib")

    def test_that_place_does_not_depend_on_the_working_directory(self):
        import os
        import tempfile

        os.environ.pop(library.DIRECTORY_VARIABLE, None)
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        with tempfile.TemporaryDirectory() as elsewhere:
            os.chdir(elsewhere)
            self.assertEqual(library.search_directory(),
                             PACKAGE_ROOT / "native" / "lib")

    def test_it_looks_for_every_platform_name(self):
        self.assertEqual(
            set(library.LIBRARY_NAMES),
            {"libtrjoludus_native.so", "trjoludus_native.dll",
             "libtrjoludus_native.dylib"},
        )

    def test_the_signatures_are_declared_with_both_types(self):
        """The rule that keeps 64-bit handles from being truncated."""
        for name, (argtypes, restype) in library.FUNCTION_SIGNATURES.items():
            with self.subTest(function=name):
                self.assertIsNotNone(restype)
                self.assertIsInstance(argtypes, list)

    def test_the_abi_version_matches_the_rust_side(self):
        import re

        source = (REPOSITORY / "rust" / "trjoludus-native" / "src"
                  / "lib.rs")
        if not source.is_file():
            self.skipTest("no Rust source here (installed package)")
        found = re.search(r"ABI_VERSION: u32 = (\d+)", source.read_text())
        self.assertIsNotNone(found, "the Rust crate declares no ABI version")
        self.assertEqual(int(found.group(1)), library.ABI_VERSION)

    def test_the_rust_crate_implements_only_what_was_migrated(self):
        """Rendering in 3.1, image in 3.2. Nothing else has moved."""
        source = (REPOSITORY / "rust" / "trjoludus-native" / "src"
                  / "lib.rs")
        if not source.is_file():
            self.skipTest("no Rust source here (installed package)")
        self.assertIn(
            'pub const IMPLEMENTED: &[&str] = &["rendering", "image"];',
            source.read_text())


class TestThePublicApiIsUnchanged(BackendTestCase):
    def test_no_rust_concept_reaches_the_public_names(self):
        import trjoludus

        for name in trjoludus.__all__:
            with self.subTest(name=name):
                lowered = name.lower()
                self.assertNotIn("rust", lowered)
                self.assertNotIn("ffi", lowered)
                self.assertNotIn("native", lowered)

    def test_the_subsystem_modules_expose_only_engine(self):
        for name, module in MODULES.items():
            if name in ("image", "animation", "collision"):
                continue      # these are real modules with real contents
            with self.subTest(system=name):
                self.assertEqual(module.__all__, ["engine"])

    def test_the_written_subsystems_still_offer_what_they_offer(self):
        self.assertEqual(collision.__all__,
                         ["CollisionError", "collide", "colliding"])

    def test_image_and_animation_keep_everything_they_had(self):
        self.assertTrue(hasattr(image, "Image"))
        self.assertTrue(hasattr(image, "load_image"))
        self.assertTrue(hasattr(image, "decode_png"))
        self.assertTrue(hasattr(animation, "Animator"))
        self.assertTrue(hasattr(animation, "AnimationError"))

    def test_a_game_can_be_written_without_importing_anything_new(self):
        """The Milestone 2 import line still covers all a game needs."""
        from trjoludus import (  # noqa: F401
            Game,
            GameObject,
            color,
            create,
            draw,
            keyboard,
            mouse,
            run,
            time,
        )

    def test_the_examples_mention_no_backend(self):
        import pathlib

        examples = pathlib.Path(__file__).parent.parent / "examples"
        for path in sorted(examples.glob("*.py")):
            with self.subTest(example=path.name):
                source = path.read_text()
                self.assertNotIn(".engine", source)
                self.assertNotIn("rust", source.lower())


class TestImportsWithoutTheNativeBackend(BackendTestCase):
    def test_importing_trjoludus_does_not_load_a_library(self):
        import subprocess
        import sys
        from pathlib import Path

        import trjoludus

        script = (
            "import trjoludus, sys;"
            "from trjoludus.native import library;"
            "print(int(library._library is library._UNSEARCHED))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=60,
            env={"PYTHONPATH": str(Path(trjoludus.__file__).parent.parent),
                 "PATH": "/usr/bin:/bin"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1",
                         "importing TrjoLudus went looking for a library")

    def test_every_subsystem_module_imports_alone(self):
        import importlib

        for name in MODULES:
            with self.subTest(system=name):
                module = importlib.import_module(f"trjoludus.{name}")
                self.assertEqual(module.engine, AUTO)

    def test_the_engine_runs_with_nothing_native(self):
        self.pretend_nothing()
        frames = []

        class G(Game):
            count = 0

            def on_update(self, dt):
                self.count += 1
                frames.append(self.count)
                if self.count >= 3:
                    self.quit()

        Application(G(), size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        self.assertEqual(frames, [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
