"""Regenerate source-backed birth-pack weights, weapon skills and manual creator witnesses."""

import argparse
import hashlib
import json
from pathlib import Path

from dfo_optimizer.ruleset import DATA, SOURCE_SHA, adapter_directory, run_adapter

HERE = Path(__file__).resolve().parent


def generate(source):
    lock = {}
    for path in (
        DATA / "progression-lock.json",
        HERE / "progression-extra-lock.json",
        HERE / "oracle-lock.json",
    ):
        lock.update(json.loads(path.read_bytes()))
    with adapter_directory() as scratch:
        path = scratch / "beginner-lock.json"
        path.write_text(json.dumps(lock), encoding="utf8")
        inputs = (DATA / "progression-rules.json", DATA / "beginner-manual.json")
        doc = run_adapter(source, path, HERE / "beginner_classes.mjs", inputs)
    return {
        **doc,
        "source_sha": SOURCE_SHA,
        "input_sha256": {
            p.name: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in inputs
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = json.dumps(generate(args.source), indent=2, sort_keys=True) + "\n"
    target = DATA / "beginner-creation-v1.json"
    if args.check:
        if target.read_text(encoding="utf8") != content:
            raise SystemExit("Beginner class source fixtures differ")
    else:
        target.write_bytes(content.encode())
    print("Verified beginner class source fixtures")
