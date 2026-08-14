"""Tests that enforce the architectural rules from ARCHITECTURE.md.

1. ``ctypes`` is imported only where TrjoLudus meets code that is not Python:
   ``trjoludus/platform/`` for the operating system, and
   ``trjoludus/native/`` for the engine's own native library.
2. No module outside ``trjoludus/platform/`` branches on the host OS.

These are the rules that keep the engine portable, and they are the easy ones
to break by accident, so they are checked mechanically rather than by review.
"""

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

import trjoludus

PACKAGE_ROOT = Path(trjoludus.__file__).parent
PLATFORM_ROOT = PACKAGE_ROOT / "platform"
NATIVE_ROOT = PACKAGE_ROOT / "native"

#: The only two places allowed to load foreign code. Both are boundaries to
#: something that is not Python -- the operating system, and the engine's own
#: native library -- and everything else is written as if neither existed.
FOREIGN_CODE_ROOTS = (PLATFORM_ROOT, NATIVE_ROOT)

#: Attribute accesses that reveal the host operating system.
OS_PROBES = {("sys", "platform"), ("os", "name"), ("platform", "system")}


def modules_outside_platform_layer() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if not path.is_relative_to(PLATFORM_ROOT)
    )


def modules_outside_the_foreign_code_layers() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if not any(path.is_relative_to(root) for root in FOREIGN_CODE_ROOTS)
    )


def imported_module_names(tree: ast.AST) -> set[str]:
    """Return the top-level names of every module imported by ``tree``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def os_probe_attributes(tree: ast.AST) -> set[str]:
    """Return ``module.attribute`` accesses that reveal the host OS."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and (node.value.id, node.attr) in OS_PROBES
        ):
            found.add(f"{node.value.id}.{node.attr}")
    return found


class TestArchitecturalRules(unittest.TestCase):
    def test_there_are_modules_to_check(self):
        """Guard against the checks below silently passing on an empty set."""
        self.assertGreater(len(modules_outside_platform_layer()), 0)

    def test_ctypes_is_confined_to_the_boundary_layers(self):
        for path in modules_outside_the_foreign_code_layers():
            with self.subTest(module=path.relative_to(PACKAGE_ROOT).as_posix()):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                self.assertNotIn(
                    "ctypes",
                    imported_module_names(tree),
                    "ctypes may only be imported under trjoludus/platform/ "
                    "or trjoludus/native/",
                )

    def test_only_the_loader_opens_a_library(self):
        """One file opens libraries, as one module per platform does.

        Other modules under native/ may *call* into the library -- that is
        what a subsystem binding is -- but they ask the loader for the handle
        rather than finding one themselves, so there is one place that knows
        where libraries come from.
        """
        openers = []
        for path in sorted(NATIVE_ROOT.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if "CDLL(" in source or "LoadLibrary" in source:
                openers.append(path.name)
        self.assertEqual(
            openers, ["library.py"],
            "opening a native library belongs in native/library.py alone",
        )

    def test_the_native_layer_is_not_reached_from_the_public_api(self):
        """A game never imports the boundary; subsystems register with it."""
        import trjoludus

        self.assertNotIn("native", trjoludus.__all__)

    def test_host_os_is_not_inspected_outside_the_platform_layer(self):
        for path in modules_outside_platform_layer():
            with self.subTest(module=path.relative_to(PACKAGE_ROOT).as_posix()):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    os_probe_attributes(tree),
                    set(),
                    "only trjoludus/platform/ may branch on the host OS",
                )

    def test_platform_base_is_itself_platform_neutral(self):
        """base.py defines the layer's shape; it must not touch an OS."""
        tree = ast.parse((PLATFORM_ROOT / "base.py").read_text(encoding="utf-8"))
        self.assertNotIn("ctypes", imported_module_names(tree))
        self.assertEqual(os_probe_attributes(tree), set())

    def test_win32_backend_is_confined_to_the_platform_layer(self):
        """Win32 declarations live under platform/ like every other backend."""
        self.assertTrue((PLATFORM_ROOT / "windows" / "_user32.py").exists())
        self.assertTrue((PLATFORM_ROOT / "windows" / "win32.py").exists())

    def test_null_backend_is_platform_neutral(self):
        """The null backend lives under platform/ but must touch no OS."""
        tree = ast.parse((PLATFORM_ROOT / "null.py").read_text(encoding="utf-8"))
        self.assertNotIn("ctypes", imported_module_names(tree))
        self.assertEqual(os_probe_attributes(tree), set())

    def test_null_backend_imports_only_stdlib_and_trjoludus(self):
        """No third-party dependencies, and no other backend."""
        tree = ast.parse((PLATFORM_ROOT / "null.py").read_text(encoding="utf-8"))
        allowed = set(sys.stdlib_module_names) | {"trjoludus"}
        self.assertEqual(imported_module_names(tree) - allowed, set())

    def test_backends_import_only_stdlib_and_trjoludus(self):
        """No backend may add a third-party dependency."""
        allowed = set(sys.stdlib_module_names) | {"trjoludus"}
        for subpackage in ("linux", "windows"):
            for path in sorted((PLATFORM_ROOT / subpackage).rglob("*.py")):
                with self.subTest(module=f"{subpackage}/{path.name}"):
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                    self.assertEqual(imported_module_names(tree) - allowed, set())

    def test_raw_declaration_modules_hold_no_backend_behaviour(self):
        """_xlib.py and _user32.py declare; the backends decide.

        Checked structurally: a declaration module defines types, constants
        and prototypes, so it should contain no classes beyond ctypes
        Structure/Union subclasses.
        """
        for relative in ("linux/_xlib.py", "windows/_user32.py"):
            path = PLATFORM_ROOT / relative
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    bases = {
                        base.id if isinstance(base, ast.Name) else
                        getattr(base, "attr", "")
                        for base in node.bases
                    }
                    with self.subTest(module=relative, cls=node.name):
                        self.assertTrue(
                            bases & {"Structure", "Union"},
                            f"{node.name} is not a ctypes structure",
                        )

    def test_importing_trjoludus_does_not_load_a_real_backend(self):
        """Importing the engine must not open a display or load Xlib."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, trjoludus\n"
                "loaded = [m for m in sys.modules\n"
                "          if 'platform.linux' in m or 'platform.windows' in m\n"
                "          or m.split('.')[0] == 'ctypes']\n"
                "assert not loaded, loaded\n"
                "print('ok')\n",
            ],
            env={**os.environ, "PYTHONPATH": str(PACKAGE_ROOT.parent)},
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


class TestCheckerItself(unittest.TestCase):
    """The checks above are only worth having if they can actually fail."""

    def test_detects_a_ctypes_import(self):
        tree = ast.parse("import ctypes.util")
        self.assertIn("ctypes", imported_module_names(tree))

    def test_detects_a_ctypes_from_import(self):
        tree = ast.parse("from ctypes import CDLL")
        self.assertIn("ctypes", imported_module_names(tree))

    def test_detects_an_os_probe(self):
        tree = ast.parse("import sys\nif sys.platform == 'win32':\n    pass\n")
        self.assertEqual(os_probe_attributes(tree), {"sys.platform"})

    def test_ignores_unrelated_attributes(self):
        tree = ast.parse("import sys\nsys.exit(0)\n")
        self.assertEqual(os_probe_attributes(tree), set())


if __name__ == "__main__":
    unittest.main()
