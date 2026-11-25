"""Independent construction and import edge cases from the pinned creator."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from dfo_optimizer.classes import disallowed_trait, export_class, import_class, validate_class


def game_class():
    materials = ["steel", "elven", "dwarven", "mithril", "silver", "adamantium", "iron"]
    stats = "strength intelligence willpower agility endurance personality speed luck".split()
    return {
        "format": "daggerfall-enhanced/custom-class",
        "version": 1,
        "name": "Material fixture",
        "hitPointsPerLevel": 30,
        "skills": {"primary": [0, 1, 2], "major": [3, 4, "Destruction"], "minor": list(range(6, 12))},
        "attributes": dict.fromkeys(stats, 50),
        "advantages": [{"primary": "increasedMagery", "secondary": "intInSpellPoints3"}],
        "disadvantages": [{"primary": "forbiddenMaterial", "secondary": key} for key in materials],
    }


def test_default_floor_and_canonical_round_trip():
    doc = game_class()
    original = deepcopy(doc)
    r = import_class(json.dumps(doc), race="Breton")
    assert r["parsed"] and r["create_legal"] and r["profile_legal"]
    assert (r["difficulty_points"], r["advancement_multiplier"], r["magicka_multiplier"]) == (-12, 0.3, 3)
    assert r["early_damage_verified"] is None and r["training_route_verified"] is None
    assert r["effective_flags"]["forbiddenMaterialsFlags"] == 127
    assert r["starting_spell_set_index"] == 1
    assert doc == original
    canonical = export_class(doc)
    assert "race" not in canonical and isinstance(canonical["skills"]["primary"][0], str)
    assert export_class(canonical) == canonical == r["normalized"]
    assert not validate_class(doc, race=0)["profile_legal"]


def test_draft_can_import_but_all_create_gates_reported_in_ui_order():
    doc = game_class()
    doc["name"] = None
    doc["skills"]["minor"][4] = None
    doc["attributes"]["intelligence"] += 1
    doc["advantages"] = []
    result = validate_class(doc)
    assert result["parsed"] and not result["create_legal"] and not result["profile_legal"]
    assert result["create_errors"] == ["missing_name", "missing_skills", "unbalanced_attributes", "difficulty_out_of_range"]
    assert result["difficulty_points"] == -22
    with pytest.raises(ValueError):
        export_class(doc)


def test_conflicting_skipped_picks_cannot_be_certified_or_silently_exported():
    doc = game_class()
    doc["advantages"] += [doc["advantages"][0], None, {"primary": "unknown"}]
    doc["disadvantages"].append({"primary": "phobia", "secondary": "animals"})
    r = validate_class(doc)
    assert r["parsed"] and r["create_legal"] and not r["profile_legal"]
    assert r["skipped"] == [doc["advantages"][1], None, {"primary": "unknown"}, doc["disadvantages"][7]]
    with pytest.raises(ValueError):
        export_class(doc)


def test_matching_secondary_blocks_conflict_but_other_secondary_does_not():
    doc = game_class()
    doc["advantages"] = [{"primary": "immunity", "secondary": "toFire"}]
    doc["disadvantages"] = [
        {"primary": "criticalWeakness", "secondary": s} for s in ("toFire", "toFrost")
    ]
    r = validate_class(doc)
    assert r["skipped"] == [doc["disadvantages"][0]]
    assert r["effective_flags"]["immunityFlags"] == 8
    assert r["effective_flags"]["criticalWeaknessFlags"] == 16


def test_order_affects_absorption_while_cost_charges_both():
    doc = game_class()
    doc["advantages"] = [{"primary": "spellAbsorption", "secondary": t} for t in ("inLight", "general")]
    a = validate_class(doc)
    b = validate_class({**doc, "advantages": doc["advantages"][::-1]})
    assert a["difficulty_points"] == b["difficulty_points"] == 0
    assert (a["effective_flags"]["spellAbsorptionFlags"], b["effective_flags"]["spellAbsorptionFlags"]) == (4, 1)


def test_reputation_ledger_is_an_editor_gate_and_carries_a_warning():
    r = validate_class({**game_class(), "reputations": {"merchants": 2}})
    assert r["create_legal"] and r["reputation_ledger"] == -2
    assert "unbalanced_reputation_editor" in r["warnings"]


def test_source_names_null_defaults_and_integral_json_numbers():
    doc = game_class()
    doc["name"] = "\n\u202e" + "X" * 30 + "\U0001f600Z"
    doc["reputations"] = {"scholars": None}
    doc["hitPointsPerLevel"] = 30.0
    doc["skills"]["primary"][0] = "  medical  "
    r = validate_class(doc)
    assert r["parsed"], r
    assert len(r["normalized"]["name"].encode("utf-16-le", "surrogatepass")) == 62
    assert r["normalized"]["skills"]["primary"][0] == "Medical"
    assert r["normalized"]["reputations"]["scholars"] == 0


@pytest.mark.parametrize("value", [False, 3, 31, 5.5, [], None, "8"])
def test_invalid_hp_fails_at_parse(value):
    r = validate_class({**game_class(), "hitPointsPerLevel": value})
    assert not r["parsed"] and not r["profile_legal"] and r["normalized"] is None


@pytest.mark.parametrize("change", [
    {"version": True}, {"version": 2}, {"attributes": {}}, {"format": "bad"},
    {"skills": {}}, {"reputations": {"peasants": -11}},
    {"skills": {"primary": [0, 1, 1], "major": [2, 3, 4], "minor": list(range(5, 11))}},
])
def test_invalid_documents_return_actionable_parse_error(change):
    result = validate_class({**game_class(), **change})
    assert not result["parsed"] and result["errors"]


def test_invalid_json_and_unknown_skill():
    assert not validate_class("{")["parsed"]
    assert not validate_class('{"version":NaN}')["parsed"]
    doc = game_class()
    doc["skills"]["primary"][0] = []
    assert not validate_class(doc)["parsed"]


def test_independently_relaxing_profile_locks():
    doc = {**game_class(), "hitPointsPerLevel": 8, "advantages": [], "disadvantages": []}
    assert not validate_class(doc)["profile_legal"]
    loose = dict(difficulty_target=0, hp_lock=None, magery_lock=None)
    assert validate_class(doc, **loose)["profile_legal"]
    regen = {"primary": "inabilityToRegen"}
    doc["disadvantages"] = [regen]
    doc["hitPointsPerLevel"] = 22
    assert not validate_class(doc, **loose)["profile_legal"]
    assert validate_class(doc, allow_unverified_advantageous_behavior=True, **loose)["profile_legal"]


@pytest.mark.parametrize(("primary", "secondary", "override", "code"), [
    ("lightPoweredMagery", "lowerMagicAbilityDarkness", {"require_day_and_night_casting": False}, "restricted_casting"),
    ("darknessPoweredMagery", "unableToUseMagicInDaylight", {"require_day_and_night_casting": False}, "restricted_casting"),
    ("lowTolerance", "toParalysis", {"allow_high_risk": True}, "high_risk_disadvantage"),
    ("damage", "fromHolyPlaces", {"allow_high_risk": True}, "high_risk_disadvantage"),
    ("criticalWeakness", "toFire", {"allow_high_risk": True}, "high_risk_disadvantage"),
])
def test_trait_exclusions_are_independent_settings(primary, secondary, override, code):
    assert disallowed_trait(primary, secondary) == code
    assert disallowed_trait(primary, secondary, **override) is None


@pytest.mark.parametrize("options", [
    {"profile": "unknown"}, {"difficulty_target": -13}, {"hp_lock": 3},
    {"magery_lock": 2.5}, {"require_day_and_night_casting": 1},
])
def test_invalid_validator_options(options):
    with pytest.raises(ValueError):
        validate_class(game_class(), **options)


def test_magic_primary_has_start_set_and_draft_preserves_skill_assignment():
    doc = game_class()
    doc["skills"]["primary"][2] = "Restoration"
    result = validate_class(doc)
    assert result["profile_legal"] and result["starting_spell_set_index"] == 1
    assert result["normalized"]["skills"]["primary"][2] == "Restoration"


def test_uncertain_effects_always_visible_even_when_the_import_is_legal():
    doc = game_class()
    doc["disadvantages"] = [{"primary": "phobia", "secondary": "animals"},
                            {"primary": "inabilityToRegen"}, {"primary": "forbiddenMaterial", "secondary": "iron"}]
    r = validate_class(doc)
    assert set(r["unsupported_mechanics"]) == {"progression.training", "pve.spell_damage",
                                              "pve.sp_recovery", "pve.phobia", "gear.eligibility"}
    assert r["mode"] == "online_snapshot"


def test_standalone_validator_rejects_changed_rules_catalog():
    from dfo_optimizer.ruleset import load_ruleset
    altered = load_ruleset()
    altered["traits"][0]["cost"] = 123
    with pytest.raises(ValueError, match="content hash"):
        validate_class(game_class(), ruleset=altered)


def test_default_casting_profile_requires_a_starter_set_separately_from_create():
    doc = game_class()
    doc["skills"]["major"][2] = 5
    strict = validate_class(doc)
    assert strict["create_legal"] and not strict["profile_legal"]
    assert strict["profile_errors"] == ["missing_starting_spell_set"]
    assert validate_class(doc, require_magic_school=False)["profile_legal"]


ORACLE = json.loads((Path(__file__).parent / "fixtures" / "oracle_classes.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", ORACLE["cases"], ids=lambda c: c["label"])
def test_headless_creator_oracle(case):
    r = validate_class(case["document"])
    assert r["source_sha"] == ORACLE["source_sha"]
    assert r["parsed"] is case["parsed"]["ok"]
    assert r["create_legal"] is case["create_legal"]
    assert r["normalized"] == case["expected_document"]
    assert r["skipped"] == case["imported"].get("skipped", [])
    assert r["difficulty_points"] == case["difficulty"]
    assert r["advancement_multiplier"] == case["advancement"]
    if case["career"] is not None:
        for field, value in r["effective_flags"].items():
            assert case["career"][field] == value
