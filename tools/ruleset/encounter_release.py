"""Generate the release data for review from authenticated source objects and the encounter oracle."""
import argparse
import json
from pathlib import Path
import sys

# Release generation always uses the reviewed code in this checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import encounter_oracle
from dfo_optimizer import ruleset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="workspace directory for generated review files")
    args = parser.parse_args()
    out = args.out.resolve()
    if out.is_relative_to(args.source.resolve()):
        raise ValueError("Choose an output directory outside the pinned source checkout")
    out.mkdir(parents=True, exist_ok=True)
    scratch = encounter_oracle.ROOT / "build" / "encounter-oracle"
    scratch.mkdir(parents=True, exist_ok=True)
    # Registry text and the expected values must both match the actual source trace.
    trace = encounter_oracle.generate(args.source)
    expected = json.loads((encounter_oracle.ROOT / "tests/fixtures/encounter-oracle.json").read_text(encoding="utf8"))
    paths = json.loads((ruleset.DATA / "encounter-paths.json").read_text(encoding="utf8"))
    if trace != expected or trace["paths"] != paths or encounter_oracle.registry(trace) != json.loads(
        (ruleset.DATA / "encounter-mechanics.json").read_text(encoding="utf8")
    ):
        raise ValueError("Regenerate and review the encounter oracle before updating the ruleset")
    bundle = ruleset._extract(args.source, compare_permanent=False, scratch_dir=scratch)
    for name, data in [("permanent-rules.json", bundle["permanent_rules"]), ("ruleset.json", bundle)]:
        (out / name).write_bytes((json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf8"))
    (out / "encounter-release.sha256").write_bytes((bundle["content_hash"] + "\n").encode("ascii"))
    print(bundle["content_hash"])


if __name__ == "__main__":
    main()
