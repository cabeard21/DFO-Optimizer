"""Recreate the bounded physical combat tables and independent upstream vectors."""
import argparse
import json
from pathlib import Path

from dfo_optimizer.ruleset import run_adapter

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "src/dfo_optimizer/data"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = run_adapter(args.source, DATA / "progression-lock.json", Path(__file__).with_suffix(".mjs"))
    law = result.pop("law")
    for path, content in ((DATA / "physical-laws.json", law), (ROOT / "tests/fixtures/physical-oracle.json", result)):
        data = (json.dumps(content, separators=(",", ":"), sort_keys=True) + "\n").encode()
        if args.check:
            if data != path.read_bytes():
                raise SystemExit(f"{path.name} differs from the authenticated source oracle")
        else:
            path.write_bytes(data)
    blows=len(result["rows"])+sum(len(case["outputs"]) for case in result["varied"])
    print(f"Verified {blows} physical blows and {len(result['timing'])} swing schedules.")


if __name__ == "__main__":
    main()
