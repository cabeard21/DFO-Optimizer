import copy
import json

import pytest

from dfo_optimizer.ruleset import load_ruleset
from dfo_optimizer.search import optimize_classes


TINY = {
    "trait_ids": [], "magicka_multiplier": None, "hp_values": [8],
    "difficulty_points": 0, "race_ids": [1, 2], "exact": True,
}


def test_reduced_domain_exhaustion_and_stable_replay():
    request = copy.deepcopy(TINY)
    first = optimize_classes(request)
    assert request == TINY
    assert first["status"] == "optimal_proven"
    assert first["termination"] == "exhausted"
    assert first["counters"]["nodes"] > 0
    assert first["counters"]["leaves"] == 2
    assert {c["race_id"] for c in first["candidates"]} == {1, 2}
    assert len({c["class_id"] for c in first["candidates"]}) == 2
    assert first["result_hash"] == optimize_classes({**TINY, "race_ids": [2, 1]})["result_hash"]
    assert first["ruleset_hash"] == load_ruleset()["content_hash"]
    assert json.loads(json.dumps(first))["candidates"] == first["candidates"]


def test_intelligence_objective_and_skill_slot_conflict():
    req = {**TINY, "attribute_domains": {"strength": [49, 50], "intelligence": [50, 51]},
           "objective": "max_intelligence", "top_k": 1}
    ranked = optimize_classes(req)
    assert ranked["status"] == "optimal_proven"
    assert ranked["candidates"][0]["class_doc"]["attributes"]["intelligence"] == 51
    assert ranked["counters"]["leaves"] >= 1
    invalid = optimize_classes({**TINY, "skill_domains": [[0]] * 12})
    assert invalid["status"] == "infeasible_proven"
    assert invalid["candidates"] == []


def test_budgets_and_censored_examples():
    cut = optimize_classes({**TINY, "max_nodes": 1})
    assert cut["termination"] == "node_limit"
    assert cut["status"] == "no_feasible_found"
    result = optimize_classes({**TINY, "top_k": 1, "exact": False})
    assert result["status"] == "best_found_bounded"
    assert len(result["candidates"]) == 1


def test_defaults_can_return_a_verified_floor_example():
    r = optimize_classes({"top_k": 1})
    c = r["candidates"][0]
    assert (c["difficulty_points"], c["advancement_multiplier"]) == (-12, 0.30)
    assert c["class_doc"]["hitPointsPerLevel"] == 30
    assert c["class_doc"]["advantages"].count(
        {"primary": "increasedMagery", "secondary": "intInSpellPoints3"}) == 1
    assert r["validation"]["finalists_checked"] == 1
    assert r["proof_scope"]["profile"] == "dhargo_pve"
    assert r["unsupported_mechanics"]
    assert "gear.eligibility" in c["unsupported_mechanics"]


def test_required_lock_outside_catalog_is_proven_empty():
    r = optimize_classes({**TINY, "magicka_multiplier": 3.0})
    assert r["status"] == "infeasible_proven"
    assert r["candidates"] == []
    assert r["termination"] == "constraint_conflict"


def test_order_sensitive_trait_picks_have_both_source_effects():
    ids = [t["id"] for t in load_ruleset()["traits"]
           if t["primary"] == "rapidHealing" and t["secondary"] in ("general", "inLight")]
    r = optimize_classes({**TINY, "trait_ids": ids, "required_trait_ids": ids, "race_ids": [1],
                          "difficulty_points": 6})
    assert r["status"] == "optimal_proven"
    assert len(r["candidates"]) == 2
    assert len({c["effective_flags"]["rapidHealing"] for c in r["candidates"]}) == 2
    assert {c["class_doc"]["advantages"][-1]["secondary"] for c in r["candidates"]} == {"general", "inLight"}


def test_hazard_exclusion_and_separate_explicit_sensitivity():
    trait = next(t for t in load_ruleset()["traits"]
                 if t["primary"] == "damage" and t["secondary"] == "fromSunlight")
    request = {**TINY, "trait_ids": [trait["id"]], "required_trait_ids": [trait["id"]],
               "difficulty_points": -10, "race_ids": [1]}
    excluded = optimize_classes(request)
    assert excluded["termination"] == "constraint_conflict"
    assert excluded["proof_scope"]["excluded_traits"] == [{"id": trait["id"], "reason": "high_risk_disadvantage"}]
    relaxed = optimize_classes({**request, "allow_high_risk_disadvantages": True})
    assert relaxed["status"] == "optimal_proven"
    assert relaxed["candidates"][0]["difficulty_points"] == -10


def test_explicit_independent_locks_and_empty_domains():
    zero = optimize_classes({**TINY, "attribute_domains": {"endurance": []}})
    assert zero["status"] == "infeasible_proven"
    # 0.5x INT is the base career encoding before a Magery selection.
    base = optimize_classes({**TINY, "magicka_multiplier": 0.5})
    assert base["status"] == "optimal_proven"
    with pytest.raises(ValueError):
        optimize_classes([])
    with pytest.raises(ValueError):
        optimize_classes({"profile": "campaign"})


def test_magic_school_lock_can_be_relaxed_for_a_declared_martial_class():
    req = {**TINY, "skill_domains": [[i] for i in range(12)]}
    assert optimize_classes(req)["status"] == "infeasible_proven"
    r = optimize_classes({**req, "require_magic_school": False})
    assert r["status"] == "optimal_proven"
    assert all(c["starting_spell_set_index"] is None for c in r["candidates"])


def test_cancel_memory_and_timeout_do_not_prove_infeasibility():
    from dfo_optimizer.native import require_native
    token = require_native().CancelToken()
    token.cancel()
    assert optimize_classes(TINY, cancel=token)["status"] == "cancelled"
    out = optimize_classes({**TINY, "memory_bytes": 1})
    assert (out["status"], out["termination"]) == ("no_feasible_found", "memory_limit")
    cut = optimize_classes({**TINY, "wall_seconds": 1e-12})
    assert (cut["status"], cut["termination"]) == ("no_feasible_found", "time_limit")


@pytest.mark.parametrize("change", [
    {"workers": 2}, {"typo": 3}, {"schema_version": True}, {"top_k": 0},
    {"race_ids": [True]}, {"race_ids": [9]}, {"trait_ids": [1000]}, {"max_nodes": -1},
    {"exact": 1}, {"objective": "damage"}, {"attribute_domains": {"str": [2]}},
    {"hp_values": [4, 4]}, {"skill_domains": [[0]]}, {"magicka_multiplier": True},
    {"wall_seconds": float("nan")}, {"require_magic_school": "false"},
])
def test_malformed_request_fails_before_native(change):
    with pytest.raises(ValueError):
        optimize_classes({**TINY, **change})
