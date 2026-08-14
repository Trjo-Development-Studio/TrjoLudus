"""Building TrjoLudus, including its native library.

Everything about the package is declared in ``pyproject.toml`` except one
thing that cannot be: whether this build compiles the Rust library, and what
the resulting wheel should therefore call itself.

**Two kinds of wheel, and the difference is honest.**

``py3-none-any``
    Pure Python, any platform, no native library. What you get when there is
    no Rust toolchain. TrjoLudus runs entirely on Python this way, which is
    the ordinary case today.

``py3-none-linux_x86_64`` (or whatever this machine is)
    Contains a native library built here, and says so in its name. ``py3``
    and ``none`` because the library is loaded through ``ctypes`` over a C
    ABI: it does not care which Python is running, only which machine.

A wheel calling itself ``any`` while carrying an x86-64 shared object would
be a lie that installs on a Mac and fails there.

**The library is built here, from source.** Nothing is copied out of
``trjoludus/native/lib/`` in the source tree: a developer's leftover build
from last week must never end up in a release. The freshly built file is put
straight into the build directory, and anything already sitting there is
removed first.

Set ``TRJOLUDUS_BUILD_NATIVE`` to control it:

===========  ==================================================
unset        build the library if a Rust toolchain is there
``1``        require one; fail the build if it is missing
``0``        skip it and produce a pure-Python wheel
===========  ==================================================
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from setuptools import Distribution, setup
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.build_py import build_py

HERE = Path(__file__).parent.resolve()
RUST = HERE / "rust"
MANIFEST = RUST / "Cargo.toml"

#: Where the loader looks, inside the package.
LIBRARY_DIRECTORY = Path("trjoludus") / "native" / "lib"

#: What cargo produces, by platform. Only one will exist after a build.
ARTEFACTS = (
    "libtrjoludus_native.so",
    "trjoludus_native.dll",
    "libtrjoludus_native.dylib",
)


def find_cargo() -> "str | None":
    """Where cargo is, or ``None``.

    ``PATH`` first. Then rustup's default location, because rustup installs
    to ``~/.cargo/bin`` and only adds it to ``PATH`` through a shell profile
    -- which a build running under ``pip`` has usually not read.
    """
    found = shutil.which("cargo")
    if found:
        return found
    fallback = Path.home() / ".cargo" / "bin" / "cargo"
    return str(fallback) if fallback.is_file() else None


def wanted() -> str:
    """What this build was asked to do about the native library."""
    setting = os.environ.get("TRJOLUDUS_BUILD_NATIVE", "").strip().lower()
    if setting in ("0", "no", "never", "false"):
        return "never"
    if setting in ("1", "yes", "always", "true"):
        return "always"
    return "auto"


def building_native() -> bool:
    """Whether this build will compile and package the native library."""
    choice = wanted()
    if choice == "never":
        return False
    if not MANIFEST.is_file():
        if choice == "always":
            raise SystemExit(
                f"TRJOLUDUS_BUILD_NATIVE=1 was set, but there is no Rust "
                f"source at {MANIFEST}. A source distribution carries it; a "
                f"bare package directory does not."
            )
        return False
    if find_cargo() is None:
        if choice == "always":
            raise SystemExit(
                "TRJOLUDUS_BUILD_NATIVE=1 was set, but cargo was not found. "
                "Install the Rust toolchain (https://rustup.rs), or unset it "
                "to build a pure-Python wheel."
            )
        return False
    return True


#: Decided once, so that the wheel's name and its contents cannot disagree.
NATIVE = building_native()


def build_library() -> Path:
    """Compile the native library and return where cargo put it."""
    cargo = find_cargo()
    print(f"TrjoLudus: building the native library with {cargo}")
    subprocess.run(
        [cargo, "build", "--release", "--manifest-path", str(MANIFEST)],
        check=True,
    )
    release = RUST / "target" / "release"
    for name in ARTEFACTS:
        candidate = release / name
        if candidate.is_file():
            return candidate
    raise SystemExit(
        f"TrjoLudus: cargo reported success but produced none of "
        f"{', '.join(ARTEFACTS)} in {release}."
    )


class BuildPy(build_py):
    """Copy the package, then put a freshly built library inside it."""

    def run(self) -> None:
        super().run()

        target = Path(self.build_lib) / LIBRARY_DIRECTORY
        target.mkdir(parents=True, exist_ok=True)

        # Whatever is in there came from somewhere else. A developer's old
        # build must not ride along in a release, so the directory is emptied
        # before anything is put in it.
        for stale in target.iterdir():
            if stale.is_file():
                stale.unlink()

        if not NATIVE:
            print("TrjoLudus: building without a native library "
                  "(pure-Python wheel)")
            return

        built = build_library()
        shutil.copy2(built, target / built.name)
        print(f"TrjoLudus: packaged {built.name} "
              f"({(target / built.name).stat().st_size} bytes)")


class NativeDistribution(Distribution):
    """A distribution that knows whether it carries compiled code.

    Setuptools decides a wheel's shape from this. Saying yes puts the package
    at the wheel's root as a platform distribution, which is the ordinary
    layout for a wheel with a binary in it; saying no would file the whole
    package under ``.data/purelib/`` instead, which works but is an odd thing
    to hand someone.
    """

    def has_ext_modules(self) -> bool:
        return NATIVE


class BDistWheel(bdist_wheel):
    """Name the wheel after what is actually in it."""

    def finalize_options(self) -> None:
        super().finalize_options()
        # An impure wheel gets a platform in its name. A pure one does not,
        # and must not: it would claim to need this machine when it does not.
        self.root_is_pure = not NATIVE

    def get_tag(self):
        python, abi, platform = super().get_tag()
        if not NATIVE:
            return python, abi, platform
        # The library is C, loaded through ctypes, so it works on any Python
        # on this machine. Saying cp314 would refuse to install on 3.13 for
        # no reason. The platform is the only part that genuinely constrains.
        return "py3", "none", platform


setup(
    distclass=NativeDistribution,
    cmdclass={"build_py": BuildPy, "bdist_wheel": BDistWheel},
)
