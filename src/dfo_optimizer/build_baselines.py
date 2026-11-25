"""Reconstruct the observed comparison classes without distributing the original documents."""
from hashlib import sha256
import json

from .class_document import ATTRIBUTES, FORMAT, REPUTATIONS
from .classes import validate_class_snapshot
from .project_data import shared_data
from .ruleset import DATA, SOURCE_SHA


_CASTERS = {"m1-breton-caster": 1, "comparison-high-elf-caster": 5}


def _corpus():
    corpus = json.loads((shared_data("baselines") / "observations.json").read_text(encoding="utf-8"))
    if corpus["source_sha"] != SOURCE_SHA:
        raise ValueError("Dhargo observations belong to a different source revision")
    return corpus["cases"]


def _martial_document(row):
    skills = row["skill_ids"]
    def traits(key):
        return [dict(zip(("primary", "secondary"), pick)) for pick in row[key]]
    return {
        "format": FORMAT, "version": 1, "name": row["id"], "hitPointsPerLevel": row["hp"],
        "attributes": dict(zip(ATTRIBUTES, row["stats"], strict=True)),
        "skills": {"primary": skills[:3], "major": skills[3:6], "minor": skills[6:]},
        "reputations": dict(zip(REPUTATIONS, row["reps"], strict=True)),
        "advantages": traits("advantage_keys"), "disadvantages": traits("disadvantage_keys"),
    }


def _baseline(baseline_id, ruleset):
    if not isinstance(baseline_id, str) or not baseline_id:
        raise ValueError("Comparison baseline ID must be a nonempty string")
    if baseline_id in _CASTERS:
        document = json.loads((DATA / "m1-caster.json").read_text(encoding="utf-8"))
        race = _CASTERS[baseline_id]
        origin = {"origin": "M1 exact max-intelligence example", "race_source": "M1 candidate" if race == 1
                  else "explicit alternate race for the same M1 class"}
    else:
        row = next((r for r in _corpus() if baseline_id == "dhargo/" + r["id"]), None)
        if row is None:
            raise ValueError(f"Unknown comparison baseline {baseline_id!r}")
        document = _martial_document(row)
        race_label = row["id"].split("-")[0]
        race = next(r["id"] for r in ruleset["races"] if r["key"].lower() == race_label)
        origin = {"origin": "Dhargo martial class observation", "race_source": "sample title",
                  "source_sha256": row["source_sha256"], "normalized_sha256": row["normalized_sha256"]}
    report = validate_class_snapshot(document, ruleset=ruleset, race=race)
    if not report["create_legal"] or report["skipped"]:
        raise ValueError(f"Comparison baseline failed source construction checks: {baseline_id}")
    if "normalized_sha256" in origin:
        canonical = json.dumps(report["normalized"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if sha256(canonical.encode()).hexdigest() != origin["normalized_sha256"]:
            raise ValueError(f"Comparison baseline differs from audited source: {baseline_id}")
    return {"type": "new_character", "race_id": race, "class": report["normalized"]}, {
        **origin, "id": baseline_id, "race_id": race,
        **{k: report[k] for k in ("create_legal", "profile_legal", "profile_errors",
                                   "difficulty_points", "advancement_multiplier")}}


def resolve_family_baseline(baseline_id, ruleset):
    return _baseline(baseline_id, ruleset)[0]


def baseline_catalog(ruleset):
    ids = [*_CASTERS, *("dhargo/" + row["id"] for row in _corpus())]
    return {"ruleset_hash": ruleset["content_hash"], "baselines": [_baseline(name, ruleset)[1] for name in ids],
            "unavailable": [{"id": name, "reason": "original class specifications unavailable"}
                            for name in ("historical-high-elf-mage", "historical-breton-mage")]}
