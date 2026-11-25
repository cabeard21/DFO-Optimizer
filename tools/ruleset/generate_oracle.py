"""Regenerate source oracle vectors using only locked public JS, with no game assets."""
import argparse
import json
from pathlib import Path

from dfo_optimizer.ruleset import run_adapter

HERE = Path(__file__).resolve().parent
DEFAULT_FIXTURE = HERE.parents[1] / "tests" / "fixtures" / "oracle_classes.json"


def generate(source):
    return run_adapter(source, HERE / "oracle-lock.json", HERE / "oracle.mjs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--check", action="store_true", help="Compare against the checked-in vectors")
    options = parser.parse_args()
    result = generate(options.source)
    if options.check:
        if result != json.loads(options.out.read_text(encoding="utf-8")):
            raise SystemExit("Oracle vectors differ from the checked-in fixture")
    else:
        options.out.parent.mkdir(parents=True, exist_ok=True)
        options.out.write_bytes((json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(f"Verified {len(result['cases'])} class vectors and {len(result['numeric'])} numeric vectors")
