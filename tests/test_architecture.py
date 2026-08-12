"""Tests that enforce the two architectural rules from ARCHITECTURE.md.

1. ``ctypes`` is imported only under ``trjoludus/platform/``.
2. No module outside ``trjoludus/platform/`` branches on the host OS.

These are the rules that keep the engine portable, and they are the easy ones
to break by accident, so they are checked mechanically rather than by review.
"""

import ast
import sys
import unittest
from pathlib import Path

import trjoludus

PACKAGE_ROOT = Path(trjoludus.__file__).parent
PLATFORM_ROOT = PACKAGE_ROOT / "platform"

#: Attribute accesses that reveal the host operating system.
OS_PROBES = {("sys", "platform"), ("os", "name"), ("platform", "system")}


def modules_outside_platform_layer() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if not path.is_relative_to(PLATFORM_ROOT)
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

    def test_ctypes_is_confined_to_the_platform_layer(self):
        for path in modules_outside_platform_layer():
            with self.subTest(module=path.relative_to(PACKAGE_ROOT).as_posix()):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                self.assertNotIn(
                    "ctypes",
                    imported_module_names(tree),
                    "ctypes may only be imported under trjoludus/platform/",
                )

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
