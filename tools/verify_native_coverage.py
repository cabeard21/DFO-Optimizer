"""Exercise the production class, spell and gear kernels in an instrumented Linux build."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "dfo_optimizer"
EXTENSIONS = ("_native", "_spells", "_gear")
HEADERS = ("class_search.hpp", "spell_kernel.hpp", "gear_search.hpp", "native_build.hpp")
FLAGS = ["-std=c++17", "-O0", "-fPIC", "-fno-fast-math", "-ffp-contract=off",
         "--coverage", "-fprofile-abs-path"]
MINIMUM_PERCENT = 80


def run(args, cwd, **options):
    subprocess.run([str(value) for value in args], cwd=cwd, check=True, **options)


def compile_module(directory, package, name):
    generated = directory / f"{name}.cpp"
    run([sys.executable, "-m", "cython", "--cplus", "-3", PACKAGE / f"{name}.pyx",
         "--module-name", f"dfo_optimizer.{name}", "-o", generated], directory)
    run(["g++", *FLAGS, '-DDFO_NATIVE_FLAGS="gcov -O0"', "-I", PACKAGE,
         "-I", sysconfig.get_path("include"), "-c", generated, "-o", f"{name}.o"], directory)
    binary = package / (name + sysconfig.get_config_var("EXT_SUFFIX"))
    run(["g++", "-shared", "--coverage", f"{name}.o", "-o", binary], directory)


def native_tests(directory):
    # Only Python service modules and frozen data are copied. Every imported
    # extension must belong to this build, even if a release wheel is installed.
    package = directory / "dfo_optimizer"
    package.mkdir()
    for module in PACKAGE.glob("*.py"):
        shutil.copy2(module, package)
    shutil.copytree(PACKAGE / "data", package / "data")
    for name in EXTENSIONS:
        compile_module(directory, package, name)
    env = {**os.environ, "PYTHONPATH": str(directory)}
    check_imports = (
        "import importlib, pathlib; "
        f"modules = [importlib.import_module('dfo_optimizer.' + n) for n in {EXTENSIONS!r}]; "
        "assert all(pathlib.Path(m.__file__).parent == pathlib.Path.cwd()/'dfo_optimizer' for m in modules); "
        "assert modules[0].build_info()['flags'] == 'gcov -O0'"
    )
    run([sys.executable, "-c", check_imports], directory, env=env)
    tests = sorted({p for pattern in ("test_native.py", "test_spell*.py", "test_gear*.py")
                    for p in (ROOT / "tests").glob(pattern)})
    run([sys.executable, "-m", "pytest", "-q", *tests], directory, env=env)
    for name in EXTENSIONS:
        if not (directory / f"{name}.gcda").is_file():
            raise RuntimeError(f"The instrumented {name} module produced no GCC execution counts")
        run(["gcov", "--json-format", f"{name}.gcno"], directory, stdout=subprocess.DEVNULL)
    return [p.relative_to(ROOT).as_posix() for p in tests]


def header_lines(directory):
    # gcov can report the same physical line several times (inlined bodies).
    # A source line is executed if any of those counters is positive.
    # spell_kernel.hpp is compiled into two extensions. Union the counters
    # across both translation units, without double-counting source lines.
    executed = {(PACKAGE / name).resolve(): {} for name in HEADERS}
    for report in directory.glob("*.gcov.json.gz"):
        with gzip.open(report, "rt", encoding="utf-8") as stream:
            files = json.load(stream)["files"]
        for source in files:
            lines = executed.get(Path(source["file"]).resolve())
            if lines is None:
                continue
            for row in source["lines"]:
                n = row["line_number"]
                lines[n] = lines.get(n, False) or row["count"] > 0
    for path, lines in executed.items():
        if not lines:
            raise RuntimeError(f"gcov reported no executable lines in {path}")
    return executed


def report_header(path, lines):
    covered = sum(lines.values())
    return {"file": path.relative_to(ROOT).as_posix(),
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "executable_lines": len(lines), "covered_lines": covered,
            "line_percent": 100 * covered / len(lines),
            "uncovered_lines": sorted(i for i, hit in lines.items() if not hit)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("run on Linux with g++, gcov, Python headers, Cython and pytest")
    with TemporaryDirectory(prefix="dfo-native-coverage-") as temporary:
        directory = Path(temporary)
        tests = native_tests(directory)
        executed = header_lines(directory)
    headers = [report_header(path, rows) for path, rows in executed.items()]
    total = sum(row["executable_lines"] for row in headers)
    covered = sum(row["covered_lines"] for row in headers)
    report = {
        "headers": headers, "modules": list(EXTENSIONS),
        "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
        "gcov": subprocess.check_output(["gcov", "--version"], text=True).splitlines()[0],
        "flags": FLAGS, "tests": tests, "executable_lines": total,
        "covered_lines": covered, "line_percent": 100 * covered / total,
        "minimum_percent": MINIMUM_PERCENT,
    }
    output = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    failed = [row["file"] for row in headers
              if row["covered_lines"] * 100 < MINIMUM_PERCENT * row["executable_lines"]]
    if failed:
        raise SystemExit("Insufficient native line coverage in " + ", ".join(failed))


if __name__ == "__main__":
    main()
