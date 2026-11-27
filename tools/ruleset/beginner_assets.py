"""Regenerate stage equipment and defensive Spell Maker prices from pinned source."""

import argparse
import json
from pathlib import Path

from dfo_optimizer.ruleset import DATA, SOURCE_SHA, adapter_directory, run_adapter

HERE = Path(__file__).resolve().parent


def generate(source):
    paths = [*sorted(DATA.glob("*-lock.json")), HERE / "progression-extra-lock.json", HERE / "oracle-lock.json"]
    lock = {name: value for path in paths for name, value in json.loads(path.read_bytes()).items()}
    with adapter_directory() as scratch:
        path = scratch / "asset-lock.json"
        path.write_text(json.dumps(lock), encoding="utf8")
        doc = run_adapter(source, path, HERE / "beginner_assets.mjs")
    return {**doc, "source_sha": SOURCE_SHA}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = json.dumps(generate(args.source), sort_keys=True, separators=(",", ":")) + "\n"
    target = DATA / "beginner-assets-v2.json"
    if args.check:
        if target.read_text(encoding="utf8") != content:
            raise SystemExit("Beginner asset source fixtures differ")
    else:
        target.write_bytes(content.encode("utf8"))
