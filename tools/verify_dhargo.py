"""Replay Dhargo's original class documents through the installed wheel."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from dfo_optimizer.classes import export_class, validate_class


MANIFEST = Path(__file__).resolve().parents[1] / "tests/fixtures/dhargo/observations.json"


def fetch_sample(case, directory):
    if directory is not None:
        return (directory / (case["id"] + ".dfclass.json")).read_bytes()
    url = "https://drive.usercontent.google.com/download?export=download&id=" + case["drive_id"]
    with urlopen(url, timeout=20) as response:
        return response.read(64 * 1024)


def verify(case, raw):
    if hashlib.sha256(raw).hexdigest() != case["source_sha256"]:
        raise ValueError(f"{case['id']} differs from the independently audited document")
    document = json.loads(raw.decode("utf-8-sig"))
    report = validate_class(document)
    if (not report["create_legal"] or report["skipped"]
            or report["difficulty_points"] != case["points"]
            or report["advancement_multiplier"] != case["advancement"]):
        raise ValueError(f"{case['id']} differs from the source oracle on class validation")
    exported = export_class(document)
    if exported["name"] != document["name"]:
        raise ValueError(f"{case['id']} lost its class name")
    mechanics = {**exported, "name": case["id"]}
    encoded = json.dumps(mechanics, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != case["normalized_sha256"]:
        raise ValueError(f"{case['id']} differs from the source oracle on normalized export")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--directory", type=Path, help="Use locally downloaded original JSON files")
    source.add_argument("--download", action="store_true", help="Read the official public samples online")
    args = parser.parse_args()
    corpus = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for case in corpus["cases"]:
        verify(case, fetch_sample(case, args.directory))
        print(f"{case['id']} passed")
    print(f"{len(corpus['cases'])} original documents passed")


if __name__ == "__main__":
    main()
