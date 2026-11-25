"""Reproduce the public-snapshot equipment catalog and independent JS vectors."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from dfo_optimizer.ruleset import DATA, SOURCE_SHA, run_adapter

ROOT = Path(__file__).resolve().parents[2]


def generate_equipment(source, *, oracle=False):
    result = run_adapter(source, DATA / "equipment-lock.json", DATA / "equipment.mjs",
                         ["oracle"] if oracle else [])
    return {"source_sha": SOURCE_SHA, **result}


def verify_theoretical(source):
    from dfo_optimizer.equipment import legal_catalog_items
    rows = list(legal_catalog_items({"gear": {"career": {}}}, theoretical=True))
    with TemporaryDirectory(prefix="dfo-equipment-") as temp:
        path = Path(temp) / "items.json"
        path.write_text(json.dumps(rows), encoding="ascii")
        result = run_adapter(source, DATA / "equipment-lock.json", ROOT / "tools/ruleset/equipment_legality.mjs",
                             [str(path)])
    if result["failures"]:
        raise ValueError(f"Pinned item law rejected {len(result['failures'])} generated rows: {result['failures'][:3]}")
    print(f"Replayed {result['count']} theoretical item copies through the pinned item law")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, oracle in [(ROOT / "src/dfo_optimizer/data/equipment.json", False),
                         (ROOT / "tests/fixtures/equipment_oracle.json", True)]:
        result = generate_equipment(args.source, oracle=oracle)
        if args.check:
            if json.loads(path.read_bytes()) != result:
                raise SystemExit(f"Source replay mismatch in {path.name}")
        else:
            path.write_bytes((json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode())
        print(f"Verified {path.name}")
    if args.check:
        verify_theoretical(args.source)


if __name__ == "__main__":
    main()
