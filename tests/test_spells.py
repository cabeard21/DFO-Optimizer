"""Public fixed/auto contracts, independent expectations and provenance."""
from copy import deepcopy
from itertools import product
from math import isclose

import pytest

from dfo_optimizer.ruleset import load_ruleset
from dfo_optimizer.spells import evaluate_spell, optimize_spells
from dfo_optimizer.spell_request import parse_spell_request


def fixed():
    return {"schema_version": 1,
            "caster": {"level": 1, "speed": 50, "destruction_trained": 100,
                       "destruction_mastered": False, "destruction_live": 100, "current_sp": 100,
                       "max_sp": 150, "gold": 40, "has_spellbook": True},
            "target": {"id": "synthetic", "hp": 60, "willpower": 0},
            "price_factor": 0.95,
            "spell": {"effect_id": "4,0", "element": 0, "range_type": 1,
                      "base_low": 1, "base_high": 1, "plus_low": 1, "plus_high": 1,
                      "per_level": 1}}


def auto():
    req = fixed()
    recipe = req.pop("spell")
    req["domain"] = {k: [v] for k, v in recipe.items() if k != "effect_id"}
    req["domain"].update(element=[1, 0], base_low=[1, 2], base_high=[1, 2, 3])
    return req


def test_fixed_metrics_rounding_and_purchase_are_separate():
    req = fixed()
    original = deepcopy(req)
    report = evaluate_spell(req)
    row = report["candidates"][0]
    m = row["metrics"]
    assert req == original and row["spell"] == req["spell"]
    assert (m["gold"], m["purchase_gold"], m["cost_sp"]) == (48, 46, 5)
    assert m["affordable"] and m["purchase_affordable"] is False
    assert (m["release_seconds"], m["recovery_seconds"]) == pytest.approx((0.2, 0.7))
    assert m["expected_damage"] == pytest.approx((51 * 2 + 10) / 100)
    assert m["dps"] == pytest.approx(m["expected_health_loss"] / 0.7)
    assert m["damage_per_sp"] == pytest.approx(m["expected_health_loss"] / 5)
    assert report["validation"]["finalists_checked"] == 1
    assert report["result_hash"] == evaluate_spell(req)["result_hash"]


def test_complete_pareto_matches_independent_pointwise_enumeration():
    req = auto()
    report = optimize_spells(req)
    assert report["status"] == "optimal_proven"
    assert report["counters"]["nodes"] == 10
    metrics = []
    for el, lo, hi in product((0, 1), (1, 2), (1, 2, 3)):
        if lo <= hi:
            one = fixed()
            one["spell"].update(element=el, base_low=lo, base_high=hi)
            m = evaluate_spell(one)["candidates"][0]["metrics"]
            metrics.append((m["dps"], m["damage_per_sp"]))
    frontier = {a for a in metrics if not any(b != a and b[0] >= a[0] and b[1] >= a[1] for b in metrics)}
    assert {(r["metrics"]["dps"], r["metrics"]["damage_per_sp"]) for r in report["candidates"]} == frontier
    assert report["candidates"][0]["multiplicity"] >= 2
    assert report["validation"]["finalists_checked"] == len(frontier)


@pytest.mark.parametrize(("path","bad"), [
    (("spell","range_type"),0), (("spell","plus_low"),True),
    (("spell","base_high"),0), (("spell","base_low"),2),
    (("caster","level"),False), (("target","hp"),0),
    (("target","resist_mods"),[0]), (("caster","unexpected"),5),
    (("target","critical_weakness"),-1),
])
def test_malformed_requests(path,bad):
    req = fixed()
    req[path[0]][path[1]] = bad
    with pytest.raises(ValueError):
        evaluate_spell(req)


def test_unsupported_fixed_recipe_and_unknown_resource():
    req = fixed()
    req["spell"]["effect_id"] = "1,0"
    assert evaluate_spell(req)["status"] == "unsupported"
    req = fixed()
    req["caster"]["current_sp"] = None
    req.pop("price_factor")
    m = evaluate_spell(req)["candidates"][0]["metrics"]
    assert m["affordable"] is None and m["purchase_gold"] is None
    req = auto()
    req["caster"]["current_sp"] = None
    assert optimize_spells(req)["status"] == "unsupported"


def test_full_domain_cardinality_without_enumeration():
    req = fixed()
    req.pop("spell")
    s = parse_spell_request(req, load_ruleset(), auto=True)
    assert s.domain_size == 10_201_000_000


def test_budget_and_explicit_empty_domain():
    req = auto()
    req["search"] = {"max_nodes": 2}
    report = optimize_spells(req)
    assert report["status"] == "best_found_bounded"
    assert report["counters"]["nodes"] == 2
    req["domain"]["element"] = []
    assert optimize_spells(req)["status"] == "infeasible_proven"


def test_capped_health_and_monotonicity_of_cost_floor():
    req = fixed()
    req["target"]["hp"] = 1
    req["caster"]["focus_pct"] = 60
    m = evaluate_spell(req)["candidates"][0]["metrics"]
    assert m["expected_health_loss"] < m["expected_damage"]
    assert isclose(m["expected_health_loss"], m["kill_probability"])
    assert m["cost_sp"] == 4


@pytest.mark.parametrize(("patch", "error"), [
    ({"caster": True}, "caster"),
    ({"other": 0}, "unknown"),
    ({"price_factor": float("inf")}, "price_factor"),
    ({"ruleset_hash": "different"}, "ruleset_hash"),
    ({"character": {}}, "exactly one"),
    ({"search": {"objective": "unspecified"}}, "objective"),
    ({"search": {"workers": 0}}, "workers"),
])
def test_invalid_public_inputs(patch, error):
    with pytest.raises(ValueError, match=error):
        evaluate_spell({**fixed(), **patch})


def test_distinct_legal_axes_and_canonical_identity():
    a = auto()
    b = deepcopy(a)
    b["domain"]["element"].reverse()
    assert optimize_spells(a)["input_hash"] == optimize_spells(b)["input_hash"]
    a["domain"]["element"] = [0, 0]
    with pytest.raises(ValueError, match="duplicate"):
        optimize_spells(a)
    a = fixed()
    a["spell"]["base_low"] = 5
    with pytest.raises(ValueError, match="minimum"):
        evaluate_spell(a)


def test_frozen_trained_skill_and_save_threshold():
    req = fixed()
    req["caster"].update(destruction_trained=200, destruction_mastered=True,
                         destruction_live=150, power_pct=25, pierce=30, cast_speed_pct=200)
    req["target"].update(immune=8, resist_mods=[0] * 5, elemental_resists=[1000] * 5)
    m = evaluate_spell(req)["candidates"][0]["metrics"]
    assert m["immune"] and m["save_chance"] == 100 and m["expected_damage"] == 0
    assert m["potency"] == pytest.approx(1.75) and m["cast_rate"] == 2
    req["target"]["resistant"] = 8
    req["target"]["elemental_resists"] = [0] * 5
    m = evaluate_spell(req)["candidates"][0]["metrics"]
    assert not m["immune"] and m["save_chance"] == 45
    assert m["expected_damage"] > 0


def test_affordability_returns_evaluation_and_proves_empty_search():
    req = fixed()
    req["caster"]["current_sp"] = 0
    assert not evaluate_spell(req)["candidates"][0]["metrics"]["affordable"]
    req = auto()
    req["caster"]["current_sp"] = 0
    report = optimize_spells(req)
    assert report["status"] == "infeasible_proven" and not report["candidates"]
    req["caster"]["current_sp"] = 151
    with pytest.raises(ValueError, match="max_sp"):
        optimize_spells(req)


def test_ranked_search_keeps_top_k_and_proves_only_declared_scope():
    req = auto()
    req["search"] = {"objective": "dps", "top_k": 2}
    report = optimize_spells(req)
    assert report["status"] == "optimal_proven"
    assert len(report["candidates"]) == 2
    assert not report["proof_scope"]["frontier_complete"]
    assert report["candidates"][0]["metrics"]["dps"] >= report["candidates"][1]["metrics"]["dps"]


def test_missing_rank_relevant_fields_and_resource_metadata():
    req = fixed()
    req["caster"].update(destruction_trained=125, destruction_mastered=None)
    report = evaluate_spell(req)
    assert "unknown caster.climb" in report["unsupported_mechanics"]
    req["caster"].update(destruction_mastered=False, has_spellbook=None, gold=None)
    assert evaluate_spell(req)["candidates"][0]["metrics"]["purchase_affordable"] is None


def test_portable_character_known_custom_spell_and_observation_override():
    from dfo_optimizer.character import normalize_character

    req = fixed()
    current = req.pop("caster")
    current["current_sp"] = None
    raw = {"type": 4, "subType": 0, "magnitudeBaseLow": 1, "magnitudeBaseHigh": 1,
           "magnitudeLevelBase": 1, "magnitudeLevelHigh": 1, "magnitudePerLevel": 1}
    doc = {"kind": "character", "schema_version": 1, "caster": current,
           "observations": {"spells": {"records": [{"custom": True, "rangeType": 1, "element": 0,
                                                    "effects": [raw, {"type": -1}]}],
                                      "unresolved_indices": [5]}}}
    req["character"] = normalize_character(doc)
    original = deepcopy(req)
    m = evaluate_spell(req)["candidates"][0]["metrics"]
    assert m["spell_known"] is True and m["actual_sp_charged"] is None
    req["live_observations"] = {"current_sp": {"value": 3, "source": "sheet", "observed_at_ms": 100}}
    result = evaluate_spell(req)
    m = result["candidates"][0]["metrics"]
    assert m["spell_known"] is True and m["actual_sp_charged"] == 0
    assert m["damage_per_sp"] is None and m["damage_per_sp_if_cast"] > 0
    assert req["character"] == original["character"]
    assert req["character"]["snapshot_hash"] != result["proof_scope"]["caster_snapshot_hash"]


def test_cancellation_and_memory_are_incomplete_searches():
    from dfo_optimizer import _spells

    req = auto()
    token = _spells.CancelToken()
    token.cancel()
    result = optimize_spells(req, cancel=token)
    assert result["status"] == "cancelled"
    assert not result["proof_scope"]["frontier_complete"]
    req["search"] = {"memory_bytes": 1}
    result = optimize_spells(req)
    assert result["status"] == "no_feasible_found" and result["termination"] == "memory_limit"


def test_unknown_cast_timing_does_not_hide_evaluable_damage_per_sp():
    req = fixed()
    req["caster"]["speed"] = None
    report = evaluate_spell(req)
    assert report["status"] == "evaluated_partial"
    m = report["candidates"][0]["metrics"]
    assert m["dps"] is None and m["release_seconds"] is None
    assert m["damage_per_sp"] > 0 and m["cost_sp"] == 5
    req = auto()
    req["caster"]["cast_speed_pct"] = None
    assert optimize_spells(req)["status"] == "unsupported"
    req["search"] = {"objective": "damage_per_sp", "top_k": 2}
    report = optimize_spells(req)
    assert report["status"] == "optimal_proven"
    assert all(r["metrics"]["cast_rate"] is None and r["metrics"]["dps"] is None for r in report["candidates"])


def test_spent_service_deadline_preserves_partial_status():
    req = auto()
    req["search"] = {"wall_seconds": 1e-12}
    result = optimize_spells(req)
    assert result["termination"] == "time_limit"
    assert result["status"] == "no_feasible_found"
    assert result["counters"]["service_seconds"] >= result["counters"]["preparation_seconds"]
