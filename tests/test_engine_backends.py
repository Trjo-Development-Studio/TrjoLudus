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
from trjoludus.native import AUTO, PYTHON, RUST, EngineError, library, registry
from trjoludus.platform.null import NullBackend

#: The subsystems that must run natively once they can.
ALWAYS_NATIVE = ("rendering", "image", "collision", "physics", "ai",
                 "pathfinding")

#: The ones that stay on Python until there is a reason not to.
FLEXIBLE = ("animation", "audio")

MODULES = {
    "rendering": rendering, "image": image, "collision": collision,
    "physics": physics, "ai": ai, "pathfinding": pathfinding,
    "animation": animation, "audio": audio,
}


class PretendLibrary:
    """Answers the two discovery functions, and implements nothing.

    Not a stub subsystem: it cannot render or collide anything. It exists so
    that the *decision* "a native implementation is available" can be tested
    without a Rust toolchain, which is the only part of the architecture that
    otherwise could not be reached from Python.
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
        self.addCleanup(library.forget)
        self.addCleanup(registry.reset)

    def pretend(self, *names):
        """Answer as though a library implementing these names existed."""
        library._library = PretendLibrary(names)
        library._problem = None

    def pretend_nothing(self):
        """Make the loader answer as if there were no library at all."""
        library._library = None
        library._problem = "no native library found (test)"


class TestDefaults(BackendTestCase):
    def test_every_subsystem_defaults_to_auto(self):
        for name, module in MODULES.items():
            with self.subTest(system=name):
                self.assertEqual(module.engine, AUTO)

    def test_the_registry_knows_every_subsystem(self):
        self.assertEqual(
            {found.name for found in registry.systems()},
            set(ALWAYS_NATIVE) | set(FLEXIBLE),
        )

    def test_the_always_native_list_is_what_it_should_be(self):
        native = {found.name for found in registry.systems()
                  if found.always_native}
        self.assertEqual(native, set(ALWAYS_NATIVE))

    def test_the_flexible_systems_are_not_forced_native(self):
        for name in FLEXIBLE:
            with self.subTest(system=name):
                self.assertFalse(registry.system(name).always_native)

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
                self.assertFalse(registry.system(name).available())

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
        for name in ("collision", "physics", "ai", "pathfinding", "audio"):
            with self.subTest(system=name):
                with self.assertRaises(EngineError) as caught:
                    registry.system(name).resolve()
                self.assertIn("no implementation yet", str(caught.exception))

    def test_asking_such_a_system_for_python_says_so_too(self):
        collision.engine = PYTHON
        with self.assertRaises(EngineError) as caught:
            registry.system("collision").resolve()
        self.assertIn("no Python implementation", str(caught.exception))


class TestWithANativeLibrary(BackendTestCase):
    def test_auto_prefers_the_native_one_for_always_native_systems(self):
        self.pretend("rendering")
        self.assertEqual(registry.system("rendering").resolve(), RUST)

    def test_auto_leaves_flexible_systems_on_python(self):
        """"auto" must not sweep a system into Rust just because it can."""
        self.pretend("animation")
        self.assertTrue(registry.system("animation").available())
        self.assertEqual(registry.system("animation").resolve(), PYTHON)

    def test_a_flexible_system_can_still_be_asked_for_rust(self):
        self.pretend("animation")
        animation.engine = RUST
        self.assertEqual(registry.system("animation").resolve(), RUST)

    def test_python_is_honoured_even_when_rust_is_there(self):
        self.pretend("rendering")
        rendering.engine = PYTHON
        self.assertEqual(registry.system("rendering").resolve(), PYTHON)

    def test_availability_is_per_system(self):
        self.pretend("rendering")
        self.assertTrue(registry.system("rendering").available())
        self.assertFalse(registry.system("physics").available())

    def test_a_system_the_library_does_not_implement_still_errors(self):
        self.pretend("rendering")
        physics.engine = RUST
        with self.assertRaises(EngineError) as caught:
            registry.system("physics").resolve()
        self.assertIn("does not implement it yet", str(caught.exception))

    def test_auto_is_not_a_coin_toss(self):
        """The same question must give the same answer every time."""
        self.pretend("rendering")
        answers = {registry.system("rendering").resolve() for _ in range(50)}
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
            registry.register("rendering", always_native=True,
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
        self.pretend("rendering")
        self.assertEqual(registry.system("rendering").resolve(), RUST)
        self.pretend_nothing()
        self.assertEqual(registry.system("rendering").resolve(), PYTHON)


class TestSettingsPersist(BackendTestCase):
    """A choice lasts until the developer changes it, and no longer."""

    def test_a_new_game_instance_does_not_reset_it(self):
        rendering.engine = RUST

        class First(Game):
            def on_update(self, dt):
                self.quit()

        class Second(Game):
            def on_update(self, dt):
                self.quit()

        Application(First(), size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        self.assertEqual(rendering.engine, RUST)
        Application(Second(), size=(40, 30), max_fps=None,
                    backend=NullBackend()).run()
        self.assertEqual(rendering.engine, RUST,
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
        animation.engine = RUST
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
        self.pretend("rendering")
        self.assertTrue(registry.system("rendering").available())
        self.pretend_nothing()
        self.assertFalse(registry.system("rendering").available())
        self.pretend("rendering")
        self.assertTrue(registry.system("rendering").available())


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
    """The real loader, against whatever this checkout actually has.

    A contributor who has run ``cargo build`` has a library; one who has not
    does not, and both must pass. So these assert that the loader is
    *consistent* with what is on disk rather than assuming either state --
    which is also the only way to notice a library that half-loads.
    """

    def test_the_loader_agrees_with_what_is_on_disk(self):
        library.forget()
        built = [name for name in library.LIBRARY_NAMES
                 if (library.search_directory() / name).is_file()]

        if built:
            self.assertTrue(library.loaded(),
                            f"{built} is on disk but did not load: "
                            f"{library.problem()}")
            self.assertEqual(library.version(), library.ABI_VERSION)
            self.assertIsNone(library.problem())
            self.assertEqual(library.library_path().parent,
                             library.search_directory())
        else:
            self.assertFalse(library.loaded())
            self.assertIsNone(library.version())
            self.assertIsNone(library.library_path())
            self.assertIn("no native library found", library.problem())

    def test_a_built_library_implements_nothing_yet(self):
        """Milestone 3.0.1 builds the crate; it still implements nothing."""
        library.forget()
        if not library.loaded():
            self.skipTest("no native library built in this checkout")
        for name in MODULES:
            with self.subTest(system=name):
                self.assertFalse(
                    library.implements(name),
                    f"the native library claims to implement {name}, but no "
                    f"subsystem has been migrated",
                )

    def test_auto_still_chooses_python_with_the_real_library(self):
        library.forget()
        if not library.loaded():
            self.skipTest("no native library built in this checkout")
        self.assertEqual(registry.system("rendering").resolve(), PYTHON)

    def test_explicit_rust_still_fails_with_the_real_library(self):
        library.forget()
        if not library.loaded():
            self.skipTest("no native library built in this checkout")
        rendering.engine = RUST
        with self.assertRaises(EngineError) as caught:
            registry.system("rendering").resolve()
        self.assertIn("does not implement it yet", str(caught.exception))

    def test_it_looks_beside_the_package(self):
        self.assertEqual(library.search_directory().name, "lib")
        self.assertEqual(library.search_directory().parent.name, "native")

    def test_it_looks_for_every_platform_name(self):
        self.assertEqual(
            set(library.LIBRARY_NAMES),
            {"libtrjoludus_native.so", "trjoludus_native.dll",
             "libtrjoludus_native.dylib"},
        )

    def test_implements_is_false_with_no_library(self):
        self.pretend_nothing()
        for name in MODULES:
            with self.subTest(system=name):
                self.assertFalse(library.implements(name))

    def test_a_file_that_is_not_a_library_is_refused(self):
        """Now testable for real: something that is not a shared object."""
        import tempfile

        folder = library.search_directory()
        already = [name for name in library.LIBRARY_NAMES
                   if (folder / name).is_file()]
        if already:
            self.skipTest("a real library is built here")

        folder.mkdir(parents=True, exist_ok=True)
        broken = folder / library.LIBRARY_NAMES[0]
        broken.write_bytes(b"this is not a shared object")
        self.addCleanup(broken.unlink)

        library.forget()
        self.assertFalse(library.loaded())
        self.assertIn("could not be loaded", library.problem())

    def test_the_signatures_are_declared_with_both_types(self):
        """The rule that keeps 64-bit handles from being truncated."""
        for name, (argtypes, restype) in library.FUNCTION_SIGNATURES.items():
            with self.subTest(function=name):
                self.assertIsNotNone(restype)
                self.assertIsInstance(argtypes, list)

    def test_the_abi_version_matches_the_rust_side(self):
        import pathlib
        import re

        source = (pathlib.Path(__file__).parent.parent / "rust"
                  / "trjoludus-native" / "src" / "lib.rs").read_text()
        found = re.search(r"ABI_VERSION: u32 = (\d+)", source)
        self.assertIsNotNone(found, "the Rust crate declares no ABI version")
        self.assertEqual(int(found.group(1)), library.ABI_VERSION)

    def test_the_rust_crate_implements_nothing_yet(self):
        """Milestone 3.0 is architecture; nothing has been migrated."""
        import pathlib

        source = (pathlib.Path(__file__).parent.parent / "rust"
                  / "trjoludus-native" / "src" / "lib.rs").read_text()
        self.assertIn("pub const IMPLEMENTED: &[&str] = &[];", source)


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
            if name in ("image", "animation"):
                continue      # these are real modules with real contents
            with self.subTest(system=name):
                self.assertEqual(module.__all__, ["engine"])

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
