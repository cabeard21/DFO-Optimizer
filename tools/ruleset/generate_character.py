"""Reproduce the synthetic two-slot DFO export using the upstream snapshot and ZIP writers."""
import argparse
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from dfo_optimizer.ruleset import run_adapter

HERE = Path(__file__).resolve().parent
EXTRA = {
    "src/buildTag.js": "de450623df1be89b4a3b1702a1b765337cec30f9",
    "src/systems/save/base64Bytes.js": "f61ce0e84198bb33b8bb747d0b6b4e6f93b50dd4",
    "src/systems/save/saveSlots.js": "104ca293b066c4a32893ccf881c83ae7b2916050",
    "src/systems/save/saveTransfer.js": "2c5f8619002c28b0dd90187bbfebaddc31fc0197",
}


def generate(source):
    with TemporaryDirectory() as work:
        lock = Path(work) / "lock.json"
        blobs = json.loads((HERE / "oracle-lock.json").read_text(encoding="utf-8"))
        lock.write_text(json.dumps({**blobs, **EXTRA}), encoding="utf-8")
        result = run_adapter(source, lock, HERE / "character.mjs")
    return base64.b64decode(result["zip"], validate=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", type=Path, default=HERE.parents[1] / "tests/fixtures/character/export.zip")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = generate(args.source)
    if args.check:
        if args.out.read_bytes() != data:
            raise SystemExit("Save export differs from the checked-in fixture")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(data)
    print(f"Verified {len(data)} upstream-exported bytes")
