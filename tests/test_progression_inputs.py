"""Frozen starts retain both source evidence and legitimate missing information."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from dfo_optimizer.character import normalize_character
from dfo_optimizer.progression_inputs import resolve_start

ROOT = Path(__file__).resolve().parents[1]
STATS = ("strength", "intelligence", "willpower", "agility", "endurance", "personality", "speed", "luck")


def birth():
    return {"type": "new_character", "profile": "custom", "race_id": 1, "roll_seed": 42,
            "class": {"name": "Source fixture", "format": "daggerfall-enhanced/custom-class",
                      "version": 1, "hitPointsPerLevel": 8, "attributes": dict.fromkeys(STATS, 50),
                      "skills": {"primary": [22, 23, 24], "major": [25, 26, 27],
                                 "minor": [0, 1, 2, 3, 4, 5]}}}


def test_born_and_observed_rolls_replay_source():
    source = json.loads((ROOT / "tests/fixtures/progression-oracle.json").read_text())["birth"]
    initial = birth()
    state, missing = resolve_start(initial)
    for key in ("skills", "attributes", "starting_sum", "current_sum", "sp", "hp", "fatigue", "last_check"):
        assert state[key] == source[key]
    assert state["known"] == source["known"]
    assert {"Arcane Arrow", "Minor Shock"} <= {r["name"] for r in state["spell_records"]}
    assert set(state["unresolved_indices"]) == {i for i in state["known"] if i < 990}
    assert state["gold"] == source["gold"] and state["has_spellbook"] == source["has_spellbook"]
    assert state["max_fatigue"] == state["fatigue"]
    assert [row["item"] for row in state["inventory"]] == source["inventory"]
    realized = {k: v for k, v in initial.items() if k != "roll_seed"}
    observed, _ = resolve_start({**realized, "rolls": source["rolls"]})
    assert observed["skills"] == state["skills"]
    assert observed["attributes"] == state["attributes"]


def test_retain_partial_save_and_legacy_portable():
    fractions = [0.] * 35
    fractions[22] = .75
    save = {"v": 1, "skills": [52] * 35, "skillUses": [2] * 35, "skillUseFrac": fractions,
            "skillProgress": None, "masteredSkills": [], "stats": dict.fromkeys(STATS, 55),
            "classicMinutes": 1234.5, "lastSkillCheckTime": 1100, "timeOfLastSkillTraining": 751,
            "startingLevelUpSkillSum": 150, "currentLevelUpSkillSum": 500,
            "readyToLevelUp": True, "pendingLevel": 12, "pendingBonusPool": 5,
            "reflexes": 2, "level": 11, "career": {"primarySkills": [2, 3, 4]}}
    snap = normalize_character(save)
    assert snap["schema_version"] == 2
    state, missing = resolve_start({"type": "current_character", "character": snap})
    assert state["fractions"][22] == .75 and state["progress"] == [0.] * 35
    assert state["minutes"] == 1234 and state["current_sum"] == 500
    assert state["pending_pool"] == 5 and state["last_training"] == 751
    assert state["sp"] is None and "sp" in missing
    old = normalize_character({"kind": "character", "schema_version": 1, "caster": {}})
    legacy, missing = resolve_start({"type": "current_character", "character": old})
    assert normalize_character(old) == old and legacy["snapshot_hash"] == old["snapshot_hash"]
    assert {"last_check", "starting_sum", "progress"} <= set(missing)
    tampered = deepcopy(old)
    tampered["caster"]["level"] = 1
    with pytest.raises(ValueError, match="hash"):
        resolve_start({"type": "current_character", "character": tampered})


@pytest.mark.parametrize("change", [{"roll_seed": True}, {"race_id": 999}, {"attribute_allocation": [1]*8},
                                    {"skill_allocation": [1]*12}, {"reflexes": 5}, {"rolls": {}}])
def test_reject_bad_creation(change):
    with pytest.raises(ValueError):
        resolve_start({**birth(), **change})


def test_unknown_never_becomes_trained_or_bought():
    start = birth()
    state, _ = resolve_start({**start, "spell_records": [{"index": 2, "name": "Owned stock", "effects": []},
                                                          {"index": 99, "name": "Other stock", "effects": []}]})
    assert 2 in [row["index"] for row in state["spell_records"]]
    assert 99 not in state["known"]
    with pytest.raises(ValueError):
        resolve_start({**start, "profile": "dhargo_pve"})


def test_supplemental_attestation_and_conflicts():
    from dfo_optimizer.character import _hash
    record = {"index": 2, "name": "Stock record", "effects": []}
    fact = {"record": record, "record_sha256": _hash(record), "source_sha256": "d"*64, "source_format":"SPELLS.STD"}
    state, _ = resolve_start({**birth(), "spell_records": {"2":fact}})
    assert state["spell_record_evidence"]["2"]["source_sha256"] == "d"*64
    with pytest.raises(ValueError, match="hash"):
        resolve_start({**birth(), "spell_records": {"2":{**fact,"record_sha256":"e"*64}}})
    with pytest.raises(ValueError, match="conflicts"):
        resolve_start({**birth(), "spell_records": [{"index":990,"effects":[]}]})


def test_invalid_save_field_cannot_reach_native():
    with pytest.raises(ValueError, match="fractions"):
        resolve_start({"type": "current_character",
                       "character": {"v": 1, "skillUseFrac": [.2]*34+[1.]}})


def test_missing_and_unusable_save_evidence():
    state, gaps = resolve_start({"type": "current_character", "character": {"v": 1, "classicMinutes": 2**31}})
    assert {"minutes", "pending_level", "pending_pool", "chargen_done", "known"} <= set(gaps)
    state, gaps = resolve_start({"type": "current_character", "character": {"v": 1, "readyToLevelUp": False,
                                                                          "chargenDone": False, "spells": []}})
    assert state["chargen_done"] is False and state["known"] == []
    assert state["pending_level"] == state["pending_pool"] == -1
    state, gaps = resolve_start({"type": "current_character", "character": {"v": 1, "readyToLevelUp": True}})
    assert state["pending_level"] is None and state["pending_pool"] == -1


def test_online_boot_consolidates_legacy_bank_gold():
    accounts = [{"accountGold": -10, "loanTotal": 500}, {"accountGold": 75}] + [{} for _ in range(15)]
    accounts.append({"accountGold": 50})
    state, _ = resolve_start({"type": "current_character", "character": {"v": 1, "bankAccounts": accounts}})
    assert state["bank_gold"] == 115
    assert accounts[0]["accountGold"] == -10
    accounts[0]["accountGold"] = -200
    state, _ = resolve_start({"type": "current_character", "character": {"v": 1, "bankAccounts": accounts}})
    assert state["bank_gold"] == 0


def test_legacy_range_and_live_fatigue_observations():
    from dfo_optimizer.character import apply_request_observations
    save = {"v": 1, "level": 50, "stats": {**dict.fromkeys(STATS, 55), "strength": 113},
            "currentLevelUpSkillSum": 999}
    portable = normalize_character(save)
    state, missing = resolve_start({"type": "current_character", "character": portable})
    assert {"level", "attributes", "current_sum", "max_fatigue"} <= set(missing)
    assert state["unsupported_legacy_values"]["level"] == 50
    assert state["unsupported_legacy_values"]["attributes"][0] == 113
    attested = apply_request_observations({"character": portable, "live_observations": {
        "max_fatigue": {"value": 6400, "source": "character sheet", "observed_at_ms": 1234}}})
    updated, _ = resolve_start({"type": "current_character", **attested})
    assert updated["max_fatigue"] == 6400
    assert updated["snapshot_hash"] != state["snapshot_hash"]


@pytest.mark.parametrize("portion", [{"gear": {"career": ["invalid"]}},
                                     {"observations": {"resources": 3}},
                                     {"observations": {"stats": [3]}}])
def test_corrupt_portable_fields_have_boundaries(portion):
    with pytest.raises(ValueError):
        resolve_start({"type": "current_character",
                       "character": {"kind": "character", "schema_version": 1, "caster": {}, **portion}})


def test_legacy_single_skill_observation_remains_partial():
    doc = {"kind": "character", "schema_version": 1, "caster": {"destruction_trained": 36},
           "observations": {"trained_skills": 36}}
    state, missing = resolve_start({"type": "current_character", "character": doc})
    assert state["skills"] is None and "skills" in missing

