from copy import deepcopy

from dfo_optimizer.beginner_classes import manual_classes
from dfo_optimizer.beginner_progression import CheckpointCache
from dfo_optimizer.beginner_refined_paths import variants
from dfo_optimizer.beginner_scenario_catalog import scenario_matrix
from dfo_optimizer.beginner_scenario_trials import make_request
from dfo_optimizer.beginner_scenarios import evaluate_matrix
from dfo_optimizer.encounter_request import freeze_encounter
from dfo_optimizer.ruleset import _progression_service_rules


def _cap():
    return {
        "stage": "cap", "level": 45, "status": "attained", "effort": {"minutes": 0, "spent": 0},
        "state": {"level": 45, "mastered": list(range(22, 28)), "known": [], "arcane_path": None,
                  "martial_path": None, "gold": 500, "minutes": 0, "skills": [100] * 35,
                  "hp": 500, "max_hp": 500, "sp": 300, "max_sp": 300, "attributes": [100] * 8},
        "actor": {"level": 45, "mastered": list(range(22, 28)), "path": "none", "martial_path": "none",
                  "gold": 500, "destruction_live": 100, "destruction_trained": 100, "destruction_mastered": True,
                  "hp": 500, "max_hp": 500, "current_sp": 300, "max_sp": 300, "speed": 100,
                  "has_spellbook": True, "power_pct": 0, "pierce": 0, "focus_pct": 0, "cast_speed_pct": 0,
                  "defense": {"willpower": 100}},
        "spells": [], "career": {}, "acquisitions": [], "transactions": [],
    }


def test_variants_hold_cap_state_and_signature_purchase_is_separate():
    rules = _progression_service_rules(None)
    original = _cap()
    frozen = deepcopy(original)
    options = variants(original, rules)
    assert original == frozen
    assert set(options) == {"none", "battlemage", "battlemage_aegis", "soulbinder", "spellbreaker", "riftwalker"}
    aegis = options["battlemage_aegis"]
    assert aegis["state"]["arcane_path"] == "battlemage"
    assert "real_ms" not in aegis["state"]
    assert aegis["state"]["known"] == [-46101]
    assert -46101 not in options["battlemage"]["state"]["known"]
    assert aegis["state"]["gold"] == 482
    assert aegis["actor"]["gold"] == aegis["state"]["gold"]
    assert aegis["transactions"][-1]["delta_gold"] == aegis["state"]["gold"] - 500
    assert not options["soulbinder"]["spells"]


def test_paths_require_earned_school_pair_and_cap_and_gold():
    rules = _progression_service_rules(None)
    cap = _cap()
    cap["state"]["mastered"] = [22, 25]
    cap["state"]["gold"] = cap["actor"]["gold"] = 0
    assert set(variants(cap, rules)) == {"none", "battlemage"}
    assert variants({**cap, "stage": "midgame", "level": 15}, rules)["none"]["level"] == 15


def test_aegis_is_authenticated_in_shared_encounter_request():
    rules = _progression_service_rules(None)
    aegis = variants(_cap(), rules)["battlemage_aegis"]
    case = next(row for row in scenario_matrix() if row["id"] == "enemy_caster")
    frozen = freeze_encounter(make_request(aegis, case, "baseline", [101]))
    assert frozen["blockers"] == []
    assert frozen["spells"][0]["signature"]
    assert frozen["scenario"]["path_id"] > 0


def test_soulbinder_restores_points_in_replayed_capped_physical_encounters():
    rules = _progression_service_rules(None)
    start = manual_classes(ruleset=rules)[0]["start"]
    reached = CheckpointCache(rules).project({**start, "roll_seed": 42})
    options = variants(reached["checkpoints"][-1], rules)
    control, active = (
        evaluate_matrix([options[label]], ["sustained"], (101, 202), ruleset=rules)
        for label in ("none", "soulbinder")
    )
    assert control["coverage"] == active["coverage"] == {
        "required": 2, "replayed": 2, "unsupported": 0, "unvisited": 0,
    }
    assert sum(r["restored_sp"] for r in active["rows"]) > sum(r["restored_sp"] for r in control["rows"])
