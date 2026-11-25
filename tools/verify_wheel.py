"""Qualify a platform wheel in isolation, including source replays and serial benchmarks."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import venv

ROOT = Path(__file__).resolve().parents[1]


def run(command, directory, env):
    subprocess.run([str(x) for x in command], check=True, cwd=directory, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf8"))["project"]["version"]
    wheels = sorted((ROOT / "dist").glob(f"dfo_optimizer-{version}-*.whl"))
    if args.wheel is None and len(wheels) != 1:
        parser.error("specify --wheel when dist does not contain exactly one wheel")
    wheel = (args.wheel or wheels[0]).resolve(strict=True)
    output = ROOT / "build" / "acceptance"
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env.setdefault("DFO_SOURCE", str(ROOT / "vendor" / "dfo-source"))
    with tempfile.TemporaryDirectory(prefix="dfo-wheel-test-") as directory:
        work = Path(directory)
        venv.EnvBuilder(with_pip=True).create(work / "venv")
        bindir = work / "venv" / ("Scripts" if os.name == "nt" else "bin")
        python = bindir / ("python.exe" if os.name == "nt" else "python")
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        run([python, "-m", "pip", "install", "-r", ROOT / "requirements-dev.txt", wheel], work, env)
        run([python, "-m", "pip", "check"], work, env)
        for script in ("generate_oracle.py", "generate_character.py", "spell_oracle.py", "equipment.py",
                       "progression_oracle.py", "spellbook_oracle.py"):
            run([python, ROOT / "tools" / "ruleset" / script, "--source", env["DFO_SOURCE"], "--check"], work, env)
        run([python, "-m", "pytest", ROOT / "tests", "--cov=dfo_optimizer",
             "--cov-config", ROOT / "pyproject.toml", "--cov-report=term-missing"], work, env)
        for suite in ("smoke", "combat", "progression", "lifecycle"):
            run([bindir / ("dfo.exe" if os.name == "nt" else "dfo"), "benchmark",
                 "--suite", suite, "--workers", "1", "--output", output / f"{suite}.json"], work, env)


if __name__ == "__main__":
    main()
