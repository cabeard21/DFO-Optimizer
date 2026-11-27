"""Regenerate Firmament geometry and caster witnesses from authenticated game source."""

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from dfo_optimizer.ruleset import SOURCE_SHA, run_adapter


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "src/dfo_optimizer/data"
CASES = [
    {"tree": {"start": "mg.start", "keys": [
        "mg.s1", "mg.s2", "mg.g", "mg.r1", "mg.r2", "mg.k1", "mg.k", "mg.bt",
        "mg.c3.0", "mg.c3.1", "mg.c3.2", "mg.c4.0", "mg.c4.1", "mg.c4.2", "mg.c4.3", "mg.c4.4",
        "mg.c2.0", "mg.c2.1", "mg.c2.2", "mg.c2.4", "mg.c1.0", "mg.c1.6", "mg.c1.5", "mg.c1.4",
    ]}, "stars": 24, "craft": 2, "speed": 93, "intelligence": 98, "destruction": 60},
    {"tree": {"start": "rt.start", "keys": [
        "rt.s1", "rt.s2", "rt.g", "rt.r1", "rt.r2", "rt.k1", "rt.k",
    ]}, "stars": 8, "craft": 0, "speed": 100, "intelligence": 73, "destruction": 26},
    {"tree": {"start": None, "keys": []},
     "stars": 8, "craft": 0, "speed": 70, "intelligence": 73, "destruction": 34},
]


def _write(path, content, check):
    if check:
        if path.read_bytes() != content:
            raise SystemExit(f"Regenerated Firmament data differs: {path.name}")
    else:
        path.write_bytes(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(os.environ.get("DFO_SOURCE", ROOT / "vendor/dfo-source")))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    adapter = DATA / "firmament-rules.mjs"
    catalog = run_adapter(args.source, DATA / "progression-lock.json", adapter)
    lock = {}
    for path in (*sorted(DATA.glob("*lock.json")), HERE / "oracle-lock.json", HERE / "spell-extra-lock.json"):
        for key, value in json.loads(path.read_text(encoding="utf-8")).items():
            if key in lock and lock[key] != value:
                raise ValueError(f"Conflicting pinned source hashes for {key}")
            lock[key] = value
    with TemporaryDirectory(prefix="firmament-source-lock-") as temp:
        lock_path = Path(temp) / "lock.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        observed = run_adapter(args.source, lock_path, adapter, [json.dumps(CASES)])
    if any(case["fault"] for case in observed):
        raise ValueError("A Firmament fixture is outside the pinned game rules")
    data = {"source_sha": SOURCE_SHA, **catalog}
    _write(DATA / "firmament-rules.json",
           (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(), args.check)
    fixture = {"source_sha": SOURCE_SHA, "cases": [{"input": q, "expected": o} for q, o in
                                                   zip(CASES, observed, strict=True)]}
    _write(ROOT / "tests/fixtures/firmament-oracle.json",
           (json.dumps(fixture, indent=2, sort_keys=True) + "\n").encode(), args.check)
    print(f"Firmament source {SOURCE_SHA}: {len(catalog['nodes'])} nodes and {len(observed)} caster witnesses")


if __name__ == "__main__":
    main()
