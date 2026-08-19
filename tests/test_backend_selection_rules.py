"""The backend-selection rules, exhaustively.

Three questions, kept apart, and one rule that uses all three:

    recommendation  what TrjoLudus thinks a subsystem should use
    availability    what can actually be used here and now, in each language
    selection       what a game gets, from those and what it asked for

These drive every combination rather than the happy path: both backends
available, one, the other, neither -- for a subsystem that recommends the
native implementation and for one that recommends Python.

Availability is simulated through the seams the architecture provides:
``_python_check`` for Python, and the library controls for native. Nothing
here removes a module from the running interpreter.
"""

import unittest

from trjoludus import ai, animation, audio, collision, image, physics
from trjoludus import pathfinding, rendering
from trjoludus.native import AUTO, PYTHON, RUST, EngineError, library, registry
from trjoludus.native import imaging
from trjoludus.native import renderer as native_renderer

MODULES = {
    "rendering": rendering, "image": image, "collision": collision,
    "physics": physics, "ai": ai, "pathfinding": pathfinding,
    "animation": animation, "audio": audio,
}


class SelectionTestCase(unittest.TestCase):
    def setUp(self):
        registry.reset()
        library.forget()
        native_renderer.forget()
        imaging.forget()
        self.addCleanup(imaging.forget)
        self.addCleanup(native_renderer.forget)
        self.addCleanup(library.forget)
        self.addCleanup(registry.reset)

    def arrange(self, system, *, python, native):
        """Say which implementations exist, without breaking anything real.

        Through the seams the architecture provides, so that nothing has to
        remove a module from the interpreter or delete a library from under a
        process that has already loaded it.
        """
        found = registry.system(system)
        found._python_check = lambda: python
        found._native_check = lambda: native
        return found


class TestTheThreeConceptsAreSeparate(SelectionTestCase):
    def test_a_recommendation_is_not_an_availability(self):
        rendering_system = self.arrange("rendering", python=True, native=False)
        self.assertEqual(rendering_system.recommends, RUST)
        self.assertFalse(rendering_system.native_available())

    def test_availability_is_asked_per_language(self):
        found = self.arrange("rendering", python=True, native=False)
        self.assertTrue(found.available(PYTHON))
        self.assertFalse(found.available(RUST))

    def test_asking_about_something_that_is_not_a_backend(self):
        with self.assertRaises(ValueError):
            registry.system("rendering").available("c++")

    def test_selection_uses_all_three(self):
        found = self.arrange("rendering", python=True, native=True)
        self.assertEqual(found.recommends, RUST)
        self.assertTrue(found.available(RUST))
        self.assertEqual(found.resolve(), RUST)


class TestPythonAvailabilityIsChecked(SelectionTestCase):
    def test_a_subsystem_with_no_python_module_has_none(self):
        for name in ("physics", "ai", "pathfinding", "audio"):
            with self.subTest(system=name):
                self.assertFalse(
                    registry.system(name).python_available())

    def test_a_subsystem_with_one_has_it(self):
        for name in ("rendering", "image", "animation", "collision"):
            with self.subTest(system=name):
                self.assertTrue(registry.system(name).python_available())

    def test_it_is_not_simply_assumed_true(self):
        """The whole point: Python is a capability, not a given."""
        found = registry.system("rendering")
        found._python_check = lambda: False
        self.assertFalse(found.python_available())

    def test_a_missing_module_reads_as_unavailable(self):
        found = registry.System("pretend", recommends=PYTHON,
                                python_implementation="trjoludus.nowhere")
        self.assertFalse(found.python_available())

    def test_a_present_module_reads_as_available(self):
        found = registry.System("pretend", recommends=PYTHON,
                                python_implementation="trjoludus.clock")
        self.assertTrue(found.python_available())


class TestExplicitPython(SelectionTestCase):
    def test_available_gives_python(self):
        found = self.arrange("rendering", python=True, native=True)
        found.engine = PYTHON
        self.assertEqual(found.resolve(), PYTHON)

    def test_unavailable_is_an_error_not_rust(self):
        found = self.arrange("rendering", python=False, native=True)
        found.engine = PYTHON
        with self.assertRaises(EngineError) as caught:
            found.resolve()
        message = str(caught.exception)
        self.assertIn("rendering.engine is 'python'", message)
        self.assertNotIn("rust", message.replace("rust/README", ""))

    def test_it_never_falls_back_even_when_rust_is_the_recommendation(self):
        found = self.arrange("image", python=False, native=True)
        found.engine = PYTHON
        with self.assertRaises(EngineError):
            found.resolve()

    def test_it_does_not_look_at_native_at_all(self):
        found = self.arrange("rendering", python=True, native=True)
        found.engine = PYTHON
        asked = []
        found._native_check = lambda: asked.append(1) or True
        self.assertEqual(found.resolve(), PYTHON)
        self.assertEqual(asked, [], "choosing Python consulted the library")


class TestExplicitRust(SelectionTestCase):
    def test_available_gives_rust(self):
        found = self.arrange("rendering", python=True, native=True)
        found.engine = RUST
        self.assertEqual(found.resolve(), RUST)

    def test_unavailable_is_an_error_not_python(self):
        found = self.arrange("rendering", python=True, native=False)
        found.engine = RUST
        with self.assertRaises(EngineError) as caught:
            found.resolve()
        message = str(caught.exception)
        self.assertIn("rendering.engine is 'rust'", message)
        self.assertIn("no native implementation", message)

    def test_it_never_falls_back_for_any_subsystem(self):
        for name in MODULES:
            with self.subTest(system=name):
                registry.reset()
                found = self.arrange(name, python=True, native=False)
                found.engine = RUST
                with self.assertRaises(EngineError):
                    found.resolve()


class TestAutoWhenRustIsRecommended(SelectionTestCase):
    """rendering and image both recommend the native implementation."""

    def outcome(self, python, native, system="rendering"):
        found = self.arrange(system, python=python, native=native)
        found.engine = AUTO
        try:
            return found.resolve()
        except EngineError:
            return "error"

    def test_both_available_gives_the_recommendation(self):
        self.assertEqual(self.outcome(python=True, native=True), RUST)

    def test_rust_unavailable_falls_back_to_python(self):
        self.assertEqual(self.outcome(python=True, native=False), PYTHON)

    def test_python_unavailable_still_gives_rust(self):
        self.assertEqual(self.outcome(python=False, native=True), RUST)

    def test_neither_available_is_an_error(self):
        self.assertEqual(self.outcome(python=False, native=False), "error")

    def test_the_same_four_for_image(self):
        self.assertEqual(self.outcome(True, True, "image"), RUST)
        self.assertEqual(self.outcome(True, False, "image"), PYTHON)
        self.assertEqual(self.outcome(False, True, "image"), RUST)
        self.assertEqual(self.outcome(False, False, "image"), "error")

    def test_the_error_says_why_neither_could_be_used(self):
        found = self.arrange("rendering", python=False, native=False)
        found.engine = AUTO
        with self.assertRaises(EngineError) as caught:
            found.resolve()
        message = str(caught.exception)
        self.assertIn("rendering.engine is 'auto'", message)
        self.assertIn("no implementation", message)

    def test_falling_back_is_not_reported_as_a_failure(self):
        found = self.arrange("rendering", python=True, native=False)
        found.engine = AUTO
        self.assertEqual(found.resolve(), PYTHON)   # no exception at all


class TestAutoWhenPythonIsRecommended(SelectionTestCase):
    """animation recommends Python: the rule is the same, mirrored."""

    def outcome(self, python, native):
        found = self.arrange("animation", python=python, native=native)
        found.engine = AUTO
        try:
            return found.resolve()
        except EngineError:
            return "error"

    def test_animation_recommends_python(self):
        self.assertEqual(registry.system("animation").recommends, PYTHON)

    def test_both_available_gives_the_recommendation(self):
        self.assertEqual(self.outcome(python=True, native=True), PYTHON)

    def test_python_unavailable_falls_back_to_rust(self):
        self.assertEqual(self.outcome(python=False, native=True), RUST)

    def test_rust_unavailable_still_gives_python(self):
        self.assertEqual(self.outcome(python=True, native=False), PYTHON)

    def test_neither_available_is_an_error(self):
        self.assertEqual(self.outcome(python=False, native=False), "error")


class TestAutoWithNoRecommendation(SelectionTestCase):
    """Subsystems nobody has written yet recommend nothing."""

    def test_they_recommend_nothing(self):
        for name in ("physics", "ai", "pathfinding", "audio"):
            with self.subTest(system=name):
                self.assertIsNone(registry.system(name).recommends)

    def test_auto_is_an_error_when_neither_exists(self):
        found = self.arrange("physics", python=False, native=False)
        found.engine = AUTO
        with self.assertRaises(EngineError):
            found.resolve()

    def test_auto_takes_whatever_appears(self):
        found = self.arrange("physics", python=True, native=False)
        found.engine = AUTO
        self.assertEqual(found.resolve(), PYTHON)


class TestPerSubsystemIndependence(SelectionTestCase):
    def test_rust_for_one_and_python_for_another(self):
        rendering.engine = RUST
        image.engine = PYTHON
        self.assertEqual(rendering.engine, RUST)
        self.assertEqual(image.engine, PYTHON)

    def test_and_the_other_way_round(self):
        rendering.engine = PYTHON
        image.engine = RUST
        self.assertEqual(rendering.engine, PYTHON)
        self.assertEqual(image.engine, RUST)

    def test_they_resolve_independently(self):
        self.arrange("rendering", python=True, native=True)
        self.arrange("image", python=True, native=True)
        rendering.engine = RUST
        image.engine = PYTHON
        self.assertEqual(registry.system("rendering").resolve(), RUST)
        self.assertEqual(registry.system("image").resolve(), PYTHON)

    def test_setting_one_moves_nothing_else(self):
        for name, module in MODULES.items():
            with self.subTest(system=name):
                registry.reset()
                module.engine = RUST
                for other, other_module in MODULES.items():
                    if other == name:
                        continue
                    self.assertEqual(other_module.engine, AUTO,
                                     f"{name} moved {other}")

    def test_availability_of_one_does_not_decide_another(self):
        self.arrange("rendering", python=True, native=True)
        found = registry.system("image")
        found._python_check = lambda: True
        found._native_check = lambda: False
        rendering.engine = AUTO
        image.engine = AUTO
        self.assertEqual(registry.system("rendering").resolve(), RUST)
        self.assertEqual(registry.system("image").resolve(), PYTHON)

    def test_there_is_no_global_switch(self):
        """Nothing public sets every subsystem at once.

        ``trjoludus.engine`` exists but is the engine *state* module, not a
        setting -- it has no ``engine`` attribute of its own to set.
        """
        import trjoludus

        for name in trjoludus.__all__:
            with self.subTest(name=name):
                self.assertNotIn(name, ("engine", "backend", "backends"))

        from trjoludus import engine as engine_state

        self.assertFalse(hasattr(engine_state, "engine"))

    def test_every_subsystem_has_its_own_setting(self):
        for name, module in MODULES.items():
            with self.subTest(system=name):
                self.assertEqual(module.engine, AUTO)
                self.assertIsNot(registry.system(name),
                                 registry.system("rendering")
                                 if name != "rendering" else None)


class TestConfigurationOutlivesRuns(SelectionTestCase):
    def play(self, game):
        from trjoludus.app import Application
        from trjoludus.platform.null import NullBackend

        Application(game, size=(20, 20), max_fps=None,
                    backend=NullBackend()).run()

    def test_it_survives_creating_a_game(self):
        from trjoludus import Game

        rendering.engine = PYTHON
        Game()
        self.assertEqual(rendering.engine, PYTHON)

    def test_it_survives_creating_an_application(self):
        from trjoludus import Game
        from trjoludus.app import Application
        from trjoludus.platform.null import NullBackend

        image.engine = PYTHON
        Application(Game(), size=(20, 20), max_fps=None,
                    backend=NullBackend())
        self.assertEqual(image.engine, PYTHON)

    def test_it_survives_a_run(self):
        from trjoludus import Game

        class G(Game):
            def on_update(self, dt):
                self.quit()

        rendering.engine = PYTHON
        image.engine = PYTHON
        self.play(G())
        self.assertEqual((rendering.engine, image.engine), (PYTHON, PYTHON))

    def test_it_survives_a_run_that_raised(self):
        from trjoludus import Game

        class Breaking(Game):
            def on_update(self, dt):
                raise RuntimeError("boom")

        image.engine = PYTHON
        with self.assertRaises(RuntimeError):
            self.play(Breaking())
        self.assertEqual(image.engine, PYTHON)

    def test_it_survives_several_runs(self):
        from trjoludus import Game

        class G(Game):
            def on_update(self, dt):
                self.quit()

        rendering.engine = PYTHON
        game = G()
        for _ in range(3):
            self.play(game)
        self.assertEqual(rendering.engine, PYTHON)

    def test_it_is_not_part_of_the_engine_state(self):
        from trjoludus import engine

        self.assertNotIn("engine", engine.EngineState.__slots__)
        self.assertNotIn("backends", engine.EngineState.__slots__)
        self.assertNotIn("registry", engine.EngineState.__slots__)


class TestNothingLeaksIntoThePublicApi(SelectionTestCase):
    def star(self):
        namespace = {}
        exec("from trjoludus import *", namespace)
        namespace.pop("__builtins__", None)
        return namespace

    def test_the_machinery_is_not_exported(self):
        names = self.star()
        for hidden in ("registry", "library", "System", "BackendResolver",
                       "RustBackend", "PythonBackend", "native", "imaging",
                       "renderer", "ctypes", "ABI_VERSION"):
            with self.subTest(name=hidden):
                self.assertNotIn(hidden, names)

    def test_the_wildcard_is_still_exactly_all(self):
        import trjoludus

        self.assertEqual(set(self.star()), set(trjoludus.__all__))

    def test_the_subsystem_modules_still_offer_only_engine(self):
        for name in ("rendering", "physics", "ai", "pathfinding", "audio"):
            with self.subTest(system=name):
                self.assertEqual(MODULES[name].__all__, ["engine"])


if __name__ == "__main__":
    unittest.main()
