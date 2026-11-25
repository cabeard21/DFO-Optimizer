"""Replay mechanical observations from fourteen public, individually hashed class files."""

import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "dhargo"


def test_dhargo_corpus_is_complete():
    corpus = json.loads((FIXTURES / "observations.json").read_text(encoding="utf-8"))
    assert corpus["source_sha"] == "a3eb1605ea1dc391b691fe314377458a7e63e483"
    cases = corpus["cases"]
    assert len(cases) == len({case["id"] for case in cases}) == 14
    assert all(len(bytes.fromhex(case["source_sha256"])) == 32 for case in cases)
    assert all(len(bytes.fromhex(case["normalized_sha256"])) == 32 for case in cases)


def test_dhargo_round_trips():
    from dfo_optimizer.classes import export_class, validate_class

    corpus = json.loads((FIXTURES / "observations.json").read_text(encoding="utf-8"))
    for case in corpus["cases"]:
        document = mechanical_document(case)
        report = validate_class(document)
        assert report["parsed"] and report["create_legal"], case["id"]
        assert report["skipped"] == [], case["id"]
        assert report["difficulty_points"] == case["points"] == -12, case["id"]
        assert report["advancement_multiplier"] == case["advancement"] == 0.3
        # Upstream writes canonical skill names when the input supplies numeric IDs.
        exported = export_class(document)
        encoded = json.dumps(exported, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        assert hashlib.sha256(encoded).hexdigest() == case["normalized_sha256"], case["id"]


def mechanical_document(case):
    attrs = ("strength", "intelligence", "willpower", "agility",
             "endurance", "personality", "speed", "luck")
    reps = ("merchants", "peasants", "scholars", "nobility", "underworld")
    skills = case["skill_ids"]
    def picks(keys):
        return [dict(zip(("primary", "secondary"), key)) for key in keys]
    return {
        "format": "daggerfall-enhanced/custom-class", "version": 1, "name": case["id"],
        "hitPointsPerLevel": case["hp"], "attributes": dict(zip(attrs, case["stats"], strict=True)),
        "skills": {"primary": skills[:3], "major": skills[3:6], "minor": skills[6:]},
        "reputations": dict(zip(reps, case["reps"], strict=True)),
        "advantages": picks(case["advantage_keys"]), "disadvantages": picks(case["disadvantage_keys"]),
    }
