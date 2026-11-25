"""Regenerate the spell rules and test vectors from reviewed upstream Git objects."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from dfo_optimizer.ruleset import run_adapter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURE = ROOT / "tests/fixtures/spell-oracle.json"
FACTS = ROOT / "src/dfo_optimizer/data/spell-rules.json"
DATA = FACTS.parent


def generate(source):
    base = json.loads((DATA / "spell-lock.json").read_text(encoding="utf-8"))
    extra = json.loads((HERE / "spell-extra-lock.json").read_text(encoding="utf-8"))
    if base.keys() & extra.keys():
        raise ValueError("The spell extension lock overlaps the base oracle lock")
    with TemporaryDirectory() as directory:
        lock = Path(directory) / "combined.json"
        lock.write_text(json.dumps({**base, **extra}), encoding="utf-8")
        return run_adapter(source, lock, HERE / "spell_oracle.mjs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    oracle = generate(args.source)
    facts = run_adapter(args.source, DATA / "spell-lock.json", DATA / "spell-rules.mjs")
    for path, document in ((FIXTURE, oracle), (FACTS, facts)):
        serialized = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
        if args.check:
            if path.read_bytes() != serialized:
                raise SystemExit(f"Regenerated content differs from {path.name}")
        else:
            path.write_bytes(serialized)
    print(f"Verified {len(oracle['casts'])} spell distributions and "
          f"{len(oracle['host'])} cast host scenarios")


if __name__ == "__main__":
    main()
