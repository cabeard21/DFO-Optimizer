"""Common, attained-state encounters and fixed-policy paired outcomes."""

import json
from copy import deepcopy

import pytest

from dfo_optimizer.project_data import shared_data


def stage():
    row = json.loads((shared_data("examples") / "encounter-dungeon.json").read_text())
    return {
        "stage": "birth",
        "level": 1,
        "family": "observed",
        "roll_seed": 42,
        "actor": {
            **row["actor"],
            "level": 1,
            "current_sp": 45,
            "max_sp": 45,
            "defense": {"willpower": 50},
        },
        "spells": row["spells"],
        "loadout": {},
        "career": {"spellAbsorptionFlags": 0},
    }


def test_manifest_covers_common_cases_with_frozen_authored_conditions():
    from dfo_optimizer.beginner_scenarios import CASE_IDS, scenario_matrix

    cases = scenario_matrix()
    assert tuple(c["id"] for c in cases) == CASE_IDS
    assert len(cases) == 8 and all(c["evidence"] for c in cases)
    assert all(e["kind"] != "blow" for c in cases for e in c["scene"]["incoming"])
    assert {e["kind"] for c in cases for e in c["scene"]["incoming"]} == {
        "melee",
        "bundle",
    }
    assert any(c["id"] == "sustained" and len(c["scene"]["rooms"]) >= 2 for c in cases)
    cases[0]["scene"]["enemies"].clear()
    assert scenario_matrix()[0]["scene"]["enemies"]


def test_shared_draws_fixed_policy_and_reproduction_with_resolved_hostile():
    from dfo_optimizer.beginner_scenarios import evaluate_matrix, verify_matrix

    checkpoint = stage()
    original = deepcopy(checkpoint)
    out = evaluate_matrix([checkpoint], ["enemy_caster"], [1, 17])
    assert checkpoint == original
    assert out["coverage"] == {
        "required": 2,
        "replayed": 2,
        "unsupported": 0,
        "unvisited": 0,
    }
    assert out["counters"]["events"] > 0 and out["counters"]["encounter_batches"] == 1
    assert [r["seed"] for r in out["rows"]] == [1, 17]
    assert len({r["policy_id"] for r in out["rows"]}) == 1
    assert all(
        r["damage"] >= 0 and r["censored_clear_us"] <= r["horizon_us"]
        for r in out["rows"]
    )
    assert verify_matrix(out, [checkpoint])["verified"]
    out["rows"][0]["ending_hp"] += 1
    with pytest.raises(ValueError, match="replay"):
        verify_matrix(out, [checkpoint])


def test_equal_acquisition_forks_reuse_replayed_fight_not_reassign_another_seed():
    from dfo_optimizer.beginner_scenarios import evaluate_matrix

    checkpoint = stage()
    checkpoint["variants"] = {"owned_only": {}, "no_spell_purchase": {}}
    result = evaluate_matrix(
        [checkpoint],
        ["enemy_caster"],
        [41, 42],
        variants=["baseline", "owned_only", "no_spell_purchase"],
    )
    assert result["coverage"]["replayed"] == 6
    assert result["counters"]["encounter_batches"] == 1
    assert result["counters"]["reused_batches"] == 2
    assert len({r["trial_hash"] for r in result["rows"] if r["seed"] == 42}) == 1


def test_missing_variant_is_a_gap_and_event_budget_counts_once():
    from dfo_optimizer.beginner_scenarios import evaluate_matrix

    checkpoint = stage()
    missing = evaluate_matrix([checkpoint], ["ordinary"], [42], variants=["owned_only"])
    assert missing["coverage"]["unsupported"] == 1 and missing["rows"][0]["reason"]
    stopped = evaluate_matrix(
        [checkpoint], ["enemy_caster", "ordinary"], [42], max_events=1
    )
    assert (
        stopped["counters"]["events"] <= 1
        and stopped["first_unvisited"]["scenario"] == "enemy_caster"
    )
    assert stopped["coverage"]["unvisited"] == 2 and not stopped["rows"]


def test_cancelled_panel_has_constant_missing_suffix_and_replay_only_checks_attested_prefix(
    monkeypatch,
):
    from dfo_optimizer import beginner_scenario_trials as trials
    from dfo_optimizer.beginner_scenarios import (
        VARIANTS,
        evaluate_matrix,
        verify_matrix,
    )

    class Cancelled:
        def cancelled(self):
            return True

    stages = [{**stage(), "roll_seed": birth} for birth in range(12)]
    result = evaluate_matrix(
        stages,
        seeds=list(range(32)),
        variants=VARIANTS,
        memory_bytes=65_536,
        cancel=Cancelled(),
    )
    assert result["coverage"]["unvisited"] == result["coverage"]["required"] == 11_904
    assert result["rows"] == [] and result["first_unvisited"]["seed"] == 0
    assert result["counters"]["encounter_batches"] == 0
    monkeypatch.setattr(
        trials.Budget, "evaluate", lambda *_: pytest.fail("replayed an unvisited fight")
    )
    assert verify_matrix(result, stages)["rows_checked"] == 0


def test_matrix_caps_retained_outputs_and_checked_receipt_cache_together():
    from dfo_optimizer.beginner_scenarios import evaluate_matrix, verify_matrix

    stages = [{**stage(), "roll_seed": birth} for birth in range(40)]
    result = evaluate_matrix(stages, ["enemy_caster"], [42], memory_bytes=128_000)
    assert result["termination"] == "memory_limit"
    assert 0 < len(result["rows"]) < 40 and result["first_unvisited"][
        "roll_seed"
    ] == len(result["rows"])
    assert result["counters"]["peak_matrix_work_bytes"] <= 128_000
    assert verify_matrix(result, stages)["rows_checked"] == len(result["rows"])


def test_malformed_checkpoint_does_not_become_a_gameplay_coverage_gap(monkeypatch):
    from dfo_optimizer import beginner_equipment
    from dfo_optimizer.beginner_scenarios import evaluate_matrix
    from dfo_optimizer.physical_encounter import PhysicalGap

    def malformed(_stage):
        raise ValueError("Ambiguous duplicate physical copy in checkpoint")

    def missing_evidence(_stage):
        raise PhysicalGap("Unresolved socketed physical effect")

    monkeypatch.setattr(beginner_equipment, "bind_physical_player", malformed)
    with pytest.raises(ValueError, match="duplicate physical copy"):
        evaluate_matrix([stage()], ["physical"], [42])
    monkeypatch.setattr(beginner_equipment, "bind_physical_player", missing_evidence)
    matrix = evaluate_matrix([stage()], ["physical"], [42])
    assert (
        matrix["coverage"]["unsupported"] == 1
        and "socketed" in matrix["rows"][0]["reason"]
    )


def test_finite_preparation_debits_actual_casts_then_carries_remaining_pool():
    from dfo_optimizer.beginner_scenario_trials import prepare_low_sp

    checkpoint = stage()
    prep = prepare_low_sp(checkpoint, 42)
    assert prep["casts"] > 0 and 0 <= prep["ending_sp"] < 6
    assert (
        prep["initial_sp"] - prep["spent_sp"] + prep["restored_sp"] == prep["ending_sp"]
    )
    assert checkpoint["actor"]["current_sp"] == 45


def test_known_empty_book_waits_under_incoming_fire_and_low_start_needs_no_prelude():
    from dfo_optimizer.beginner_scenario_trials import prepare_low_sp
    from dfo_optimizer.beginner_scenarios import evaluate_matrix

    checkpoint = stage()
    checkpoint.update(spells=[], unsupported_spells=[])
    checkpoint["actor"].update(has_spellbook=False, current_sp=2)
    outcome = evaluate_matrix([checkpoint], ["enemy_caster"], [42])["rows"][0]
    assert outcome["status"] == "replayed" and not outcome["cleared"]
    assert (
        outcome["casts"] == outcome["damage"] == 0
        and outcome["ending_hp"] < outcome["initial_hp"]
    )
    prep = prepare_low_sp(checkpoint, 42)
    assert (
        prep["casts"] == prep["spent_sp"] == prep["elapsed_us"] == 0
        and prep["ending_sp"] == 2
    )
    checkpoint["unsupported_spells"].append(
        {"index": 123, "reason": "unresolved source record"}
    )
    missing = evaluate_matrix([checkpoint], ["enemy_caster"], [42])["rows"][0]
    assert missing["status"] == "unsupported" and "unresolved" in missing["reason"]


def test_one_owned_heal_in_room_transition_debits_sp_and_carries_recovery_lock():
    from dfo_optimizer.encounter import evaluate_encounter

    row = json.loads((shared_data("examples") / "encounter-dungeon.json").read_text())
    row["actor"].update(hp=31, max_hp=64, current_sp=60, max_sp=60)
    scene = row["scenario"]
    scene["rooms"][1] = {
        "id": "second",
        "enemies": [1],
        "delay_us": 2_000_000,
        "heal_spell": "heal",
        "evidence": "A safe two-second opening to cast an actually owned heal.",
    }
    scene["incoming"] = []
    for target in scene["enemies"]:
        target["hp"] = 1
    row["policies"] = [{"id": "attack", "rules": [{"spell": "touch"}]}]
    row["seeds"] = [42]
    result = evaluate_encounter(row)
    winner = result["winner"]
    assert (
        winner["first_trial"]["healing"] > 0 and winner["first_trial"]["rest_us"] == 0
    )
    actions = [event for event in winner["trace"] if event[1] == "click"]
    heals = [event for event in actions if event[2] == -1]
    assert len(heals) == 1 and heals[0][4] > 0
    second = next(event for event in actions if event[2] == 1)
    assert second[0] >= heals[0][0] + 700_000
    assert sum(event[4] for event in actions) == winner["first_trial"]["spent_sp"]


def test_manual_reference_has_real_stage_threats_dry_melee_and_paired_gear_spending():
    from dfo_optimizer.beginner_classes import manual_classes
    from dfo_optimizer.beginner_progression import CheckpointCache
    from dfo_optimizer.beginner_scenarios import (
        VARIANTS,
        evaluate_matrix,
        verify_matrix,
    )
    from dfo_optimizer.ruleset import load_ruleset

    rules = load_ruleset()
    family = manual_classes(ruleset=rules)[0]
    route = CheckpointCache(rules).project(
        {**family["start"], "roll_seed": 42}, family=family["id"]
    )
    assert route["status"] == "complete"
    checkpoints = route["checkpoints"]
    from dfo_optimizer.beginner_scenario_catalog import scenario_matrix
    from dfo_optimizer.beginner_scenario_trials import make_request

    case = next(r for r in scenario_matrix() if r["id"] == "resistant")
    request = make_request(checkpoints[0], case, "baseline", [101])
    assert (
        request["scenario"]["physical"]["enemies"][0]["attributes"][2]
        == request["scenario"]["enemies"][0]["willpower"]
    )
    unarmed = {
        **checkpoints[0],
        "spells": [],
        "unsupported_spells": [],
        "actor": {**checkpoints[0]["actor"], "has_spellbook": False},
    }
    defense = evaluate_matrix([unarmed], ["defensive"], [42])["rows"][0]
    assert (
        defense["status"] == "replayed"
        and defense["melee_swings"] > 0
        and not defense["casts"]
    )
    plan = evaluate_matrix(checkpoints, seeds=[101], variants=VARIANTS)
    rows = plan["rows"]
    assert plan["coverage"]["replayed"] == plan["coverage"]["required"] == 93
    assert any(r["scenario"] == "physical" and r["incoming_swings"] > 0 for r in rows)
    assert any(
        r["scenario"] == "low_sp"
        and r["melee_swings"] > 0
        and r["prelude"]["spent_sp"] > 0
        for r in rows
    )
    assert all(
        r["physical_damage"] <= r["damage"] and r["max_hp"] >= r["ending_hp"]
        for r in rows
    )
    assert all(r["rest_us"] == 0 for r in rows)
    assert all(r["status"] == "replayed" for r in rows)
    assert verify_matrix(plan, checkpoints)["rows_checked"] == 93
