"""Regenerate pinned progression constants and independent gameplay observations."""
import argparse
import json
from pathlib import Path

from dfo_optimizer.ruleset import run_adapter, adapter_directory

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "src/dfo_optimizer/data"


def generate(source):
    facts = run_adapter(source, DATA / "progression-lock.json", DATA / "progression-rules.mjs")
    base = json.loads((DATA / "progression-lock.json").read_text())
    extra = json.loads((HERE / "progression-extra-lock.json").read_text())
    with adapter_directory() as directory:
        lock = Path(directory) / "combined.json"
        lock.write_text(json.dumps({**base, **extra}), encoding="utf-8")
        oracle = run_adapter(source, lock, HERE / "progression_oracle.mjs")
    return facts, oracle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    facts, oracle = generate(args.source)
    for path, doc in [(DATA / "progression-rules.json", facts), (ROOT / "tests/fixtures/progression-oracle.json", oracle)]:
        payload = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode()
        if args.check:
            if path.read_bytes() != payload:
                raise SystemExit(f"Regenerated content differs from {path.name}")
        else:
            path.write_bytes(payload)
    print(f"Verified {len(facts['paths'])} specialization pairs, {len(oracle['events'])} gameplay cases, and a source-created character.")


if __name__ == "__main__":
    main()

