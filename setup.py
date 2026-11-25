"""PEP 517 extension configuration for a mandatory platform wheel."""
import os
from pathlib import Path

from Cython.Build import cythonize
from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext


class NativeBuild(build_ext):
    def build_extensions(self):
        if self.compiler.compiler_type == "msvc":
            flags = ["/std:c++17", "/O2", "/fp:strict"]
        else:
            flags = ["-std=c++17", "-O3", "-fno-fast-math", "-ffp-contract=off"]
        for extension in self.extensions:
            extension.extra_compile_args = flags
            extension.define_macros.append(("DFO_NATIVE_FLAGS", '"' + " ".join(flags) + '"'))
        super().build_extensions()


package = Path("src/dfo_optimizer")
headers = sorted(str(path) for pattern in ("*.hpp", "*.pxi") for path in package.glob(pattern))
extensions = [
    Extension(
        f"dfo_optimizer.{name}", [str(package / f"{name}.pyx")], language="c++",
        include_dirs=[str(package)], depends=headers,
    )
    for name in ("_native", "_spells", "_gear")
]
setup(
    cmdclass={"build_ext": NativeBuild},
    ext_modules=cythonize(
        extensions,
        build_dir="build/cython",
        annotate=bool(os.environ.get("DFO_ANNOTATE")),
        compiler_directives={"language_level": 3},
    ),
)
