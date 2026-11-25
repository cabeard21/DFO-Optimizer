"""PEP 517 extension configuration for a mandatory platform wheel."""
import os

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


extension = Extension(
    "dfo_optimizer._native",
    ["src/dfo_optimizer/_native.pyx"],
    language="c++",
    include_dirs=["src/dfo_optimizer"],
    depends=["src/dfo_optimizer/native_build.hpp", "src/dfo_optimizer/class_search.hpp"],
)
setup(
    cmdclass={"build_ext": NativeBuild},
    ext_modules=cythonize(
        [extension],
        build_dir="build/cython",
        annotate=bool(os.environ.get("DFO_ANNOTATE")),
        compiler_directives={"language_level": 3},
    ),
)
