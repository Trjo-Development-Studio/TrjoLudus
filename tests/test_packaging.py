"""Tests for what a built package actually contains.

Two kinds. The cheap ones read the build configuration and run always. The
real one builds a wheel and looks inside it, which takes a minute and needs a
Rust toolchain, so it runs when asked:

    TRJOLUDUS_PACKAGING_TESTS=1 python -m unittest tests.test_packaging

That gate is not there to let the slow test rot. It is there because a suite a
contributor runs fifty times a day should not compile Rust fifty times, and
because a suite that silently skipped without saying why would be worse than
one that says exactly what turns it on.

What is being checked is the thing that went wrong before: a wheel whose name
and whose contents disagree.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import trjoludus

PACKAGE_ROOT = Path(trjoludus.__file__).parent
REPOSITORY = PACKAGE_ROOT.parent

#: Set to run the tests that build a wheel.
GATE = "TRJOLUDUS_PACKAGING_TESTS"

#: Files no wheel should ever carry.
NEVER_PACKAGED = (
    "__pycache__", ".pyc", ".pyo", ".git", ".pytest_cache", ".ruff_cache",
    "rust/", "target/", ".gitignore", "tests/", "examples/", ".venv",
)


def in_a_checkout() -> bool:
    return (REPOSITORY / "setup.py").is_file()


def cargo() -> "str | None":
    found = shutil.which("cargo")
    if found:
        return found
    fallback = Path.home() / ".cargo" / "bin" / "cargo"
    return str(fallback) if fallback.is_file() else None


class TestTheBuildConfiguration(unittest.TestCase):
    """Read the build files. Cheap, and always run."""

    def setUp(self):
        if not in_a_checkout():
            self.skipTest("not a source checkout")

    def source(self, name):
        return (REPOSITORY / name).read_text(encoding="utf-8")

    def test_no_binary_is_declared_as_package_data(self):
        """The library is built, not copied out of the source tree."""
        pyproject = self.source("pyproject.toml")
        self.assertNotIn("lib/*.so", pyproject)
        self.assertNotIn("lib/*.dll", pyproject)
        self.assertNotIn("lib/*.dylib", pyproject)

    def test_the_build_clears_whatever_was_there_first(self):
        setup = self.source("setup.py")
        self.assertIn("stale.unlink()", setup)

    def test_the_wheel_is_told_it_is_not_pure_when_it_is_not(self):
        setup = self.source("setup.py")
        self.assertIn("root_is_pure = not NATIVE", setup)
        self.assertIn("def has_ext_modules", setup)

    def test_the_tag_is_python_agnostic_and_platform_specific(self):
        setup = self.source("setup.py")
        self.assertIn('return "py3", "none", platform', setup)

    def test_the_source_distribution_carries_the_rust_source(self):
        manifest = self.source("MANIFEST.in")
        self.assertIn("graft rust", manifest)
        self.assertIn("prune rust/target", manifest)

    def test_the_source_distribution_carries_no_binaries(self):
        manifest = self.source("MANIFEST.in")
        for pattern in ("*.so", "*.dll", "*.dylib"):
            with self.subTest(pattern=pattern):
                self.assertIn(f"global-exclude {pattern}", manifest)

    def test_there_are_no_runtime_dependencies(self):
        self.assertIn("dependencies = []", self.source("pyproject.toml"))

    def test_nothing_asks_the_user_for_a_rust_toolchain(self):
        """A game developer installs a wheel; wheels do not run cargo."""
        pyproject = self.source("pyproject.toml")
        build_requires = pyproject.split("requires = ")[1].split("\n")[0]
        for tool in ("rust", "cargo", "setuptools-rust", "maturin"):
            with self.subTest(tool=tool):
                self.assertNotIn(tool, build_requires.lower())


class TestABuiltWheel(unittest.TestCase):
    """Build a wheel and look inside it. Slow; gated."""

    wheel = None
    built_native = False

    @classmethod
    def setUpClass(cls):
        if not os.environ.get(GATE):
            raise unittest.SkipTest(
                f"set {GATE}=1 to build and inspect a wheel")
        if not in_a_checkout():
            raise unittest.SkipTest("not a source checkout")

        cls._folder = tempfile.TemporaryDirectory()
        environment = dict(os.environ)
        tool = cargo()
        if tool:
            environment["PATH"] = (str(Path(tool).parent) + os.pathsep
                                   + environment.get("PATH", ""))
        # Build whatever this machine can: native if there is a toolchain.
        result = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", str(REPOSITORY),
             "--no-deps", "--no-build-isolation", "-w", cls._folder.name],
            capture_output=True, text=True, timeout=900, env=environment,
        )
        if result.returncode != 0:
            raise unittest.SkipTest(
                f"could not build a wheel:\n{result.stdout}\n{result.stderr}"
            )
        wheels = list(Path(cls._folder.name).glob("*.whl"))
        assert len(wheels) == 1, wheels
        cls.wheel = wheels[0]
        cls.built_native = tool is not None

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "_folder", None) is not None:
            cls._folder.cleanup()

    def names(self):
        with zipfile.ZipFile(self.wheel) as archive:
            return archive.namelist()

    def binaries(self):
        return [name for name in self.names()
                if name.endswith((".so", ".dll", ".dylib"))]

    def test_the_name_and_the_contents_agree(self):
        """The whole point: a wheel must not lie about what it carries."""
        pure = self.wheel.name.endswith("-py3-none-any.whl")
        if pure:
            self.assertEqual(self.binaries(), [],
                             "a py3-none-any wheel carries a binary")
        else:
            self.assertTrue(self.binaries(),
                            "a platform wheel carries no binary")

    def test_a_native_wheel_is_tagged_for_this_machine(self):
        if not self.built_native:
            self.skipTest("no toolchain, so a pure wheel was built")
        import sysconfig

        expected = sysconfig.get_platform().replace("-", "_").replace(".", "_")
        self.assertIn(expected, self.wheel.name)
        self.assertNotIn("-any.whl", self.wheel.name)

    def test_a_native_wheel_says_py3_none(self):
        """The library is C, so it does not care which Python is running."""
        if not self.built_native:
            self.skipTest("no toolchain, so a pure wheel was built")
        self.assertIn("py3-none-", self.wheel.name)
        with zipfile.ZipFile(self.wheel) as archive:
            metadata = archive.read(
                "trjoludus-0.0.1.dist-info/WHEEL").decode()
        self.assertIn("Root-Is-Purelib: false", metadata)
        self.assertIn("Tag: py3-none-", metadata)

    def test_the_library_is_where_the_loader_looks(self):
        if not self.built_native:
            self.skipTest("no toolchain, so a pure wheel was built")
        from trjoludus.native import library

        expected = {f"trjoludus/native/lib/{name}"
                    for name in library.LIBRARY_NAMES}
        self.assertTrue(set(self.names()) & expected,
                        f"no library at trjoludus/native/lib/: "
                        f"{self.binaries()}")

    def test_the_packaged_library_is_really_compiled(self):
        if not self.built_native:
            self.skipTest("no toolchain, so a pure wheel was built")
        with zipfile.ZipFile(self.wheel) as archive:
            name = self.binaries()[0]
            data = archive.read(name)
        self.assertGreater(len(data), 1000, "the packaged library is a stub")
        # ELF, PE or Mach-O. Whatever this machine builds, not a text file.
        self.assertTrue(
            data[:4] in (b"\x7fELF", b"MZ\x90\x00")
            or data[:2] == b"MZ"
            or data[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"),
            f"{name} does not begin like a compiled library: {data[:8]!r}",
        )

    def test_the_package_itself_is_all_there(self):
        names = set(self.names())
        for needed in ("trjoludus/__init__.py", "trjoludus/app.py",
                       "trjoludus/rendering.py",
                       "trjoludus/rendering_python.py",
                       "trjoludus/native/library.py",
                       "trjoludus/platform/null.py"):
            with self.subTest(name=needed):
                self.assertIn(needed, names)

    def test_no_development_artefact_came_along(self):
        found = [name for name in self.names()
                 if any(bad in name for bad in NEVER_PACKAGED)]
        self.assertEqual(found, [], f"development files in the wheel: {found}")

    def test_the_wheel_is_at_the_root_not_under_data(self):
        """A .data/purelib indirection is legal but odd to hand someone."""
        tops = {name.split("/")[0] for name in self.names()}
        self.assertEqual(tops, {"trjoludus", "trjoludus-0.0.1.dist-info"})


class TestAPureWheel(unittest.TestCase):
    """Building with the native library switched off."""

    @classmethod
    def setUpClass(cls):
        if not os.environ.get(GATE):
            raise unittest.SkipTest(
                f"set {GATE}=1 to build and inspect a wheel")
        if not in_a_checkout():
            raise unittest.SkipTest("not a source checkout")

        cls._folder = tempfile.TemporaryDirectory()
        environment = dict(os.environ)
        environment["TRJOLUDUS_BUILD_NATIVE"] = "0"
        result = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", str(REPOSITORY),
             "--no-deps", "--no-build-isolation", "-w", cls._folder.name],
            capture_output=True, text=True, timeout=900, env=environment,
        )
        if result.returncode != 0:
            raise unittest.SkipTest(
                f"could not build a wheel:\n{result.stdout}\n{result.stderr}"
            )
        cls.wheel = next(Path(cls._folder.name).glob("*.whl"))

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "_folder", None) is not None:
            cls._folder.cleanup()

    def test_it_is_pure_and_says_so(self):
        self.assertTrue(self.wheel.name.endswith("-py3-none-any.whl"),
                        self.wheel.name)

    def test_it_carries_no_binary(self):
        with zipfile.ZipFile(self.wheel) as archive:
            binaries = [name for name in archive.namelist()
                        if name.endswith((".so", ".dll", ".dylib"))]
        self.assertEqual(binaries, [])

    def test_it_is_still_a_complete_engine(self):
        with zipfile.ZipFile(self.wheel) as archive:
            names = set(archive.namelist())
        self.assertIn("trjoludus/__init__.py", names)
        self.assertIn("trjoludus/native/library.py", names)


if __name__ == "__main__":
    unittest.main()
