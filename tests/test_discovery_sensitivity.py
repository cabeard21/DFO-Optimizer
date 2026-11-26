"""Paired scenario sensitivity changes a single explicit world assumption per run."""

from copy import deepcopy

import pytest

from dfo_optimizer.discovery_presets import discovery_preset
from dfo_optimizer.discovery_sensitivity import run_variants, vary


def test_variants_change_only_the_requested_input():
    req = discovery_preset("midgame")
    orig = deepcopy(req)
    variant = vary(req, "gear_access", "owned")
    assert variant["equipment"].get("offers", []) == []
    assert "loadouts" not in variant["equipment"]
    assert variant["class_search"] == orig["class_search"]
    assert vary(req, "practice_cadence_ms", 12_000)["progression"]["itinerary"]["cadence_ms"] == 12_000
    assert vary(req, "cache_gold", 90)["progression"]["itinerary"]["cache_gold"] == 90
    scene = vary(discovery_preset("enemy_caster"), "horizon_us", 21_000_000)
    assert scene["encounter"]["scenario"]["horizon_us"] == 21_000_000
    assert req == orig
    with pytest.raises(ValueError, match="encounter"):
        vary(req, "horizon_us", 77)
    with pytest.raises(ValueError, match="itinerary"):
        vary(scene, "cache_gold", 9)


def test_sensitivity_reexecutes_current_admission_and_shares_total_work():
    req = discovery_preset("early")
    req["sensitivity"] = {"gear_access": ["owned"], "cache_gold": [20]}
    req["search"]["max_nodes"] = 29
    observed = []

    def run(query, **kw):
        observed.append(query)
        nodes = query["search"]["max_nodes"]
        return {
            "status": "best_found_bounded",
            "counters": {"nodes": nodes},
            "result_hash": str(nodes),
            "candidates": [{"family": "one"}],
            "roll_spread": [],
            "timings": {},
        }

    plan = run_variants(req, run, None)
    assert sum(q["search"]["max_nodes"] for q in observed) == 29
    assert len(observed) == 3 and all("class_admission" not in q and "sensitivity" not in q for q in observed)
    assert all(q["roll_seeds"] == req["roll_seeds"] for q in observed)
    assert plan["sensitivity_budget"]["nodes_used"] == 29
    assert len(plan["sensitivity"]) == 2
    assert all(row["retained_families"] == ["one"] for row in plan["sensitivity"])
