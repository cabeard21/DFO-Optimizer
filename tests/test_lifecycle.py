"""Exercise lifecycle admissions, paired starts, resource accounting and replay."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def example():
    return json.loads((ROOT / "examples/build-lifecycle.json").read_bytes())


def test_build_paired_rolls_and_replay_are_reproducible():
    from dfo_optimizer.lifecycle import optimize_build, replay_build

    req = example()
    frozen = deepcopy(req)
    result = optimize_build(req)
    assert req == frozen
    assert result["engine"] == "native-cython-cpp17"
    assert result["status"] == "optimal_proven", result.get("gaps")
    assert result["paired_rolls"] == req["roll_seeds"]
    assert all(len(s["rolls"]) == len(req["roll_seeds"]) for s in result["families"])
    assert result["counters"]["evaluations"] > 0
    assert result["timings"]["first_validated_seconds"] >= 0
    assert result["candidates"] and all(p["validated"] for p in result["candidates"])
    assert replay_build(result)["validated"]
    assert optimize_build(req)["result_hash"] == result["result_hash"]
    assert any(step["new_purchases"] for p in result["candidates"] for step in p["checkpoints"])


def test_forged_recommendation_and_incomparable_scenarios_rejected():
    from dfo_optimizer.lifecycle import optimize_build, replay_build, compare_builds

    result = optimize_build(example())
    changed = deepcopy(result)
    changed["candidates"][0]["checkpoints"][0]["dps"] += 1
    with pytest.raises(ValueError):
        replay_build(changed)
    assert compare_builds([result, result])["same_comparison"]
    req = example()
    req["target"]["hp"] += 1
    with pytest.raises(ValueError, match="comparison"):
        compare_builds([result, optimize_build(req)])


def test_replan_rejects_mutating_current_character():
    from dfo_optimizer.lifecycle import replan_build

    with pytest.raises(ValueError, match="current"):
        replan_build(example())


def test_impossible_early_purchase_cannot_leak():
    from dfo_optimizer.lifecycle import optimize_build

    req = example()
    req["budget_gold"] = 0
    plan = optimize_build(req)
    assert plan["candidates"]
    assert all(s["spent_gold"] == 0 for p in plan["candidates"] for s in p["checkpoints"])


def test_mixed_roll_policies_cannot_be_called_paired():
    from dfo_optimizer.lifecycle import optimize_build

    req = example()
    req["roll_seeds"] = [1, 1]
    with pytest.raises(ValueError, match="roll"):
        optimize_build(req)


def test_sp_remains_spent_until_verified_rest():
    from dfo_optimizer.lifecycle import optimize_build, replay_build

    req = example()
    req["families"] = req["families"][:1]
    req["roll_seeds"] = [42]
    req["checkpoints"] = [0, 1]
    req["progression"]["stages"] = [[{"kind": "skip"}]]
    req["equipment"] = {"loadouts": [{}]}
    req["spellbook"] = {"mode": "fixed_spellbook", "policies": [["known/990"]]}
    stage = optimize_build(req)["candidates"][0]["checkpoints"][0]
    casts = stage["sp_available"] // (2 * stage["policy_sp"]) + 1
    req["spellbook"]["policies"][0] *= casts
    assert optimize_build(req)["status"] == "infeasible_proven"
    req["progression"]["stages"] = [
        [
            {
                "kind": "rest",
                "site": "bed",
                "refill_sp": 192,
                "evidence": "Uninterrupted eight-hour sleep at a confirmed bed",
            }
        ]
    ]
    result = optimize_build(req)
    assert result["status"] == "optimal_proven", result["gaps"]
    first, second = result["candidates"][0]["checkpoints"]
    assert second["policy_sp"] > first["sp_after_policy"]
    assert second["sp_available"] == max(first["sp_after_policy"], 192)
    assert replay_build(result)["validated"]


def test_current_import_observations_and_joint_training_budget():
    from dfo_optimizer.lifecycle import replan_build, replay_build

    req = json.loads((ROOT / "examples/build-replan-current.json").read_bytes())
    plan = replan_build(req, base_dir=ROOT / "examples")
    assert plan["candidates"], plan["gaps"]
    assert replay_build(plan)["validated"]
    assert any(p["effort"]["spent"] for p in plan["candidates"])
    restricted = replan_build({**req, "budget_gold": 0}, base_dir=ROOT / "examples")
    assert restricted["candidates"] and all(not r["effort"]["spent"] for r in restricted["candidates"])


def test_compare_rejects_different_access_and_realized_rolls():
    from dfo_optimizer.lifecycle import compare_builds, optimize_build

    req = example()
    req["families"] = req["families"][:1]
    first = optimize_build(req)
    for changes in [{"budget_gold": 0}, {"equipment": {"loadouts": [{}]}}]:
        with pytest.raises(ValueError, match="comparison"):
            compare_builds([first, optimize_build({**req, **changes})])


def test_early_and_final_ranking_reverse_at_fixed_total_cost():
    from dfo_optimizer.lifecycle import optimize_build, replay_build

    raw = json.loads((ROOT / "examples/build-checkpoint-reversal.json").read_bytes())
    plan = optimize_build(raw)
    assert plan["exact"] and replay_build(plan)["validated"]
    ranks = [(r["total_spent_gold"], tuple(s["dps"] for s in r["checkpoints"])) for r in plan["candidates"]]
    cost, (early, late) = next((p, v) for p, v in ranks if v[0] > v[1])
    assert (cost, (late, early)) in ranks
    assert all(row["early_dps"] == late and row["final_dps"] == early for row in plan["final_checkpoint_only"])


def test_generated_class_search_replays_frozen_admissions(monkeypatch):
    from dfo_optimizer.lifecycle import optimize_build, replay_build
    from dfo_optimizer import search

    req = example()
    del req["families"]
    req["roll_seeds"] = [42]
    req["class_search"] = json.loads((ROOT / "examples/max-intelligence.json").read_bytes())
    p = optimize_build(req)
    admission = p["frozen_request"]["class_admission"]
    assert admission["counters"]["nodes"] > 0 and admission["families"]
    assert admission["limits"]["top_k"] == 3 and not p["exact"]
    monkeypatch.setattr(search, "optimize_classes", lambda *a, **kw: pytest.fail("reran class generation"))
    assert replay_build(p)["validated"]
    with pytest.raises(ValueError, match="class_search"):
        optimize_build({**req, "class_search": None})


def test_tracking_disintegrate_signed_and_exceptional_stock_cost():
    from dfo_optimizer.lifecycle_domain import record_recipe

    record = {
        "rangeType": 1,
        "element": 2,
        "effects": [{"type": 5, "subType": -1, "chanceBase": 20, "chanceMod": 1, "chancePerLevel": 1}],
    }
    assert record_recipe(record)["effects"][0]["effect_id"] == "5,255"
    assert record_recipe({**record, "minimumCastingCost": 250}) is None
    with pytest.raises(ValueError, match="spell"):
        record_recipe({**record, "effects": [1]})


def test_replay_rejects_malformed_envelopes_and_forged_proof_flags():
    from dfo_optimizer.lifecycle import _id, optimize_build, replay_build

    plan = optimize_build(example())
    with pytest.raises(ValueError):
        replay_build({"kind": "lifecycle", "ruleset_hash": plan["ruleset_hash"]})
    for patch in ({"exact": False}, {"stopping_reasons": ["time_limit"]}):
        with pytest.raises(ValueError):
            replay_build({**plan, **patch})
    broken = {**plan, "candidates": [None]}
    broken["result_hash"] = _id(broken)
    with pytest.raises(ValueError):
        replay_build(broken)


def test_sensitivity_imports_immutable_panel_once(monkeypatch):
    from dfo_optimizer import lifecycle
    from dfo_optimizer.lifecycle import replan_build, replay_build

    raw = json.loads((ROOT / "examples/build-replan-current.json").read_bytes())
    raw["sensitivity"] = {"budget_gold": [0, 100]}
    freeze = lifecycle._freeze
    calls = []

    def once(*args):
        calls.append(args)
        assert len(calls) == 1
        return freeze(*args)

    monkeypatch.setattr(lifecycle, "_freeze", once)
    p = replan_build(raw, base_dir=ROOT / "examples")
    assert [row["value"] for row in p["sensitivity"]] == [0, 100]
    assert replay_build(p)["optimality_reproved"] is False


def test_explicit_custom_creator_legal_start_and_unreviewed_environment():
    from dfo_optimizer.build_baselines import resolve_family_baseline
    from dfo_optimizer.lifecycle import _rules, optimize_build, replay_build

    raw = example()
    start = resolve_family_baseline("m1-breton-caster", _rules(None))
    career = {**start["class"], "hitPointsPerLevel": 25, "disadvantages": start["class"]["disadvantages"][2:]}
    custom = {**start, "class": career, "profile": "custom"}
    raw["families"] = [{"id": "25 HP caster", "start": custom}]
    raw["roll_seeds"] = [42]
    result = optimize_build(raw)
    assert result["exact"] and result["candidates"], result["gaps"]
    assert replay_build(result)["valid"]
    blocked = deepcopy(raw)
    blocked["families"][0]["start"]["class"]["disadvantages"].append(
        {"primary": "darknessPoweredMagery", "secondary": "lowerMagicAbilityDaylight"}
    )
    result = optimize_build(blocked)
    assert not result["exact"] and not result["candidates"]
    assert "environmental_magery" in result["gaps"][0]["reasons"]
