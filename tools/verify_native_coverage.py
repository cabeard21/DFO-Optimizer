"""Qualify the production C++ search header using a disposable Linux GCC build."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "dfo_optimizer"
HEADER = PACKAGE / "class_search.hpp"
FLAGS = ["-std=c++17", "-O0", "-fPIC", "-fno-fast-math", "-ffp-contract=off",
         "--coverage", "-fprofile-abs-path"]
MINIMUM_PERCENT = 80


def run(args, cwd, **options):
    subprocess.run([str(value) for value in args], cwd=cwd, check=True, **options)


def native_tests(directory):
    # A separate import root prevents a previously installed release wheel from
    # satisfying the tests. The untouched release binary remains available for timings.
    package = directory / "dfo_optimizer"
    package.mkdir()
    (package / "__init__.py").touch()
    generated = directory / "_native.cpp"
    run([sys.executable, "-m", "cython", "--cplus", "-3", PACKAGE / "_native.pyx",
         "--module-name", "dfo_optimizer._native", "-o", generated], directory)
    run(["g++", *FLAGS, '-DDFO_NATIVE_FLAGS="gcov -O0"', "-I", PACKAGE,
         "-I", sysconfig.get_path("include"), "-c", generated, "-o", "kernel.o"], directory)
    binary = package / ("_native" + sysconfig.get_config_var("EXT_SUFFIX"))
    run(["g++", "-shared", "--coverage", "kernel.o", "-o", binary], directory)
    env = {**os.environ, "PYTHONPATH": str(directory)}
    run([sys.executable, "-m", "pytest", "-q", ROOT / "tests" / "test_native.py"], directory, env=env)
    if not (directory / "kernel.gcda").is_file():
        raise RuntimeError("The instrumented extension did not produce GCC execution counts")
    run(["gcov", "--json-format", "kernel.gcno"], directory, stdout=subprocess.DEVNULL)


def header_lines(directory):
    # gcov can report the same physical line several times (inlined bodies).
    # A source line is executed if any of those counters is positive.
    executed = {}
    for report in directory.glob("*.gcov.json.gz"):
        with gzip.open(report, "rt", encoding="utf-8") as stream:
            files = json.load(stream)["files"]
        for source in files:
            if Path(source["file"]).resolve() != HEADER:
                continue
            for row in source["lines"]:
                n = row["line_number"]
                executed[n] = executed.get(n, False) or row["count"] > 0
    if not executed:
        raise RuntimeError(f"gcov reported no executable lines in {HEADER}")
    return executed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("run on Linux with g++, gcov, Python headers, Cython and pytest")
    with TemporaryDirectory(prefix="dfo-native-coverage-") as temporary:
        directory = Path(temporary)
        native_tests(directory)
        executed = header_lines(directory)
    covered = sum(executed.values())
    report = {
        "file": HEADER.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(HEADER.read_bytes()).hexdigest(),
        "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
        "gcov": subprocess.check_output(["gcov", "--version"], text=True).splitlines()[0],
        "flags": FLAGS, "tests": "tests/test_native.py", "executable_lines": len(executed),
        "covered_lines": covered, "line_percent": 100 * covered / len(executed),
        "uncovered_lines": sorted(i for i, hit in executed.items() if not hit),
        "minimum_percent": MINIMUM_PERCENT,
    }
    output = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    if covered * 100 < MINIMUM_PERCENT * len(executed):
        raise SystemExit("C++ search header coverage is below the required line threshold")


if __name__ == "__main__":
    main()
