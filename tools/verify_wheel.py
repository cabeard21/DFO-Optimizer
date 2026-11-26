"""Qualify a platform wheel in isolation, including source replays and serial benchmarks."""
import argparse
from contextlib import nullcontext
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
import venv
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def run(command, directory, env):
    subprocess.run([str(x) for x in command], check=True, cwd=directory, env=env)


def verify_installed(wheel):
    """Verify the selected interpreter loads the exact package and shared data in the wheel."""
    import dfo_optimizer
    package = Path(sysconfig.get_path("platlib"))
    if Path(dfo_optimizer.__file__).resolve().parent != (package / "dfo_optimizer").resolve():
        raise RuntimeError("The product was imported outside the isolated wheel environment")
    checked = 0
    with ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith("dfo_optimizer/") or ".dist-info/" in name and not name.endswith("/RECORD"):
                target = package / name
            elif ".data/data/" in name:
                target = Path(sysconfig.get_path("data")) / name.split(".data/data/",1)[1]
            else:
                continue
            if not name.endswith("/"):
                if not target.is_file() or sha256(target.read_bytes()).digest() != sha256(archive.read(name)).digest():
                    raise ValueError("Wheel and installed artifact differ at " + name)
                checked += 1
    print(f"Verified {checked} installed files from {wheel}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--installed-env", type=Path, help="qualify an already prepared isolated wheel environment")
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "acceptance")
    parser.add_argument("--work-dir", type=Path, help="use an existing private working directory")
    parser.add_argument("--browser", action="store_true", help="qualify the offline browser workflow in the installed environment")
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf8"))["project"]["version"]
    wheels = sorted((ROOT / "dist").glob(f"dfo_optimizer-{version}-*.whl"))
    if args.wheel is None and len(wheels) != 1:
        parser.error("specify --wheel when dist does not contain exactly one wheel")
    wheel = (args.wheel or wheels[0]).resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env.setdefault("DFO_SOURCE", str(ROOT / "vendor" / "dfo-source"))
    if args.work_dir:
        if not args.work_dir.is_dir():
            parser.error("--work-dir must be an existing private directory")
        env.setdefault("DFO_TEST_SCRATCH", str(args.work_dir.resolve()))
        env.setdefault("DFO_ORACLE_SCRATCH", str(args.work_dir.resolve()))
    scope = nullcontext(args.work_dir.resolve()) if args.work_dir else tempfile.TemporaryDirectory(prefix="dfo-wheel-test-")
    with scope as directory:
        work = Path(directory)
        destination = args.installed_env.resolve() if args.installed_env else work / "venv"
        if not args.installed_env:
            venv.EnvBuilder(with_pip=True).create(destination)
        bindir = destination / ("Scripts" if os.name == "nt" else "bin")
        python = bindir / ("python.exe" if os.name == "nt" else "python")
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        if not args.installed_env:
            run([python, "-m", "pip", "install", "-r", ROOT / "requirements-dev.txt", wheel], work, env)
        if args.browser:
            if not args.installed_env:
                run([python, "-m", "pip", "install", "playwright==1.63.0"], work, env)
            if not args.installed_env and not env.get("DFO_BROWSER_EXECUTABLE"):
                run([python, "-m", "playwright", "install", "chromium"], work, env)
            env["DFO_BROWSER_TEST"] = "1"
            env.setdefault("DFO_BROWSER_REPORT", str(output / "browser-timings.json"))
        run([python, "-c", "import runpy,sys; runpy.run_path(sys.argv[1])['verify_installed'](sys.argv[2])",
             Path(__file__).resolve(),wheel], work, env)
        run([python, "-m", "pip", "check"], work, env)
        commands = []
        for script in ("generate_oracle.py", "generate_character.py", "spell_oracle.py", "equipment.py",
                       "progression_oracle.py", "spellbook_oracle.py", "encounter_oracle.py"):
            commands.append([python, ROOT / "tools" / "ruleset" / script, "--source", env["DFO_SOURCE"], "--check"])
        commands.append([python, "-m", "pytest", ROOT / "tests", "--cov=dfo_optimizer",
                         "--cov-config", ROOT / "pyproject.toml", "--cov-report=term-missing"])
        for suite in ("smoke", "combat", "progression", "lifecycle", "encounter", "discovery"):
            commands.append([bindir / ("dfo.exe" if os.name == "nt" else "dfo"), "benchmark",
                             "--suite", suite, "--workers", "1", "--output", output / f"{suite}.json"])
        failed = []
        for command in commands:
            try:
                run(command, work, env)
            except subprocess.CalledProcessError as error:
                failed.append(subprocess.list2cmdline([str(x) for x in command]) + f" (exit {error.returncode})")
        if failed:
            raise SystemExit("Qualification failed:\n" + "\n".join(failed))


if __name__ == "__main__":
    main()
