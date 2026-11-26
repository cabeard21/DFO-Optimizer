"""Conditional scenario assumptions, finite offers and shared opportunity binding."""

from copy import deepcopy

import pytest

from dfo_optimizer.build_baselines import resolve_family_baseline
from dfo_optimizer.discovery_presets import (
    bind_itinerary,
    discovery_preset,
    preset_catalog,
)
from dfo_optimizer.ruleset import load_ruleset


def test_all_guided_presets_are_distinct_editable_build_requests():
    ids = [r["id"] for r in preset_catalog()]
    assert ids == [
        "early",
        "midgame",
        "endgame",
        "dungeon",
        "enemy_caster",
        "high_resistance",
        "multiple_targets",
        "creation_to_cap",
        "theoretical_endgame",
    ]
    queries = [discovery_preset(i) for i in ids]
    assert len({q["description"] for q in queries}) == len(ids)
    for q in queries:
        assert q["class_search"]["profile"] == "spellcaster_discovery_v1"
        assert q["class_admission_strategy"] == "adaptive"
        assert q["search"]["wall_seconds"] == 120
        if q["progression"]["goal"]["level"] == 45:
            assert q["roll_seeds"] == [42, 43] and q["search"]["max_nodes"] == 4_000_000
        else:
            assert q["roll_seeds"] == list(range(42, 50))
        assert "class" not in q["class_search"]
    queries[0]["equipment"]["offers"].clear()
    assert discovery_preset("early")["equipment"]["offers"]


def test_broad_access_never_assumes_acquisition_and_theoretical_is_explicit():
    practical = discovery_preset("early")
    ideal = discovery_preset("theoretical_endgame")
    for q in (practical, ideal):
        offers = q["equipment"]["offers"]
        assert offers and len({r["instance_id"] for r in offers}) == len(offers)
        assert all(r["acquisition"]["owned"] is False for r in offers)
        assert all("hypothetical" in r["acquisition"]["source"].lower() for r in offers)
    assert all(r["acquisition"]["price"]["gold"] > 0 for r in practical["equipment"]["offers"])
    assert "theoretical" in ideal["description"].lower()
    assert all(r["acquisition"]["price"]["gold"] == 0 for r in ideal["equipment"]["offers"])
    assert {r["item"]["group"] for r in practical["equipment"]["offers"]} >= {"Jewellery", "Weapons"}


def test_itinerary_uses_starter_records_and_orders_remaining_school_purchases():
    rules = load_ruleset()
    start = {**resolve_family_baseline("m1-breton-caster", rules), "roll_seed": 42}
    mage = deepcopy(start)
    mage["class"]["skills"] = {"primary": [22, 24, 26], "major": [23, 25, 14], "minor": [27, 1, 2, 3, 4, 5]}
    q = discovery_preset("creation_to_cap")["progression"]
    saved = deepcopy(q)
    first = bind_itinerary(q, mage, rules)
    assert q == saved
    flat = [a for c in first["cycles"] for w in c["windows"] for a in w]
    assert {a["skill"] for a in flat if a["kind"] == "master"} == set(range(22, 28))
    buys = [a for a in flat if a["kind"] == "buy"]
    assert any(
        a["record"]["name"] == "Practice Knock" and a["record"]["custom"] and a["record"]["index"] < 0
        for a in buys
    )
    assert sum(a["kind"] == "collect_gold" for a in flat) == 1
    assert 991 not in {a["spell"] for a in buys}
    assert all(a["gold_cost"] > 0 for a in buys)
    assert any(a.get("recovery") == "full_bed" for a in flat)
    assert first["project_creation_vitals"] and not first["require_starting_damage"]
    assert first["goal"]["level"] == 45
    other = bind_itinerary(q, start, rules)
    assert other["cycles"] != first["cycles"]


def test_invalid_or_contradictory_itinerary_rejected():
    with pytest.raises(ValueError, match="preset"):
        discovery_preset("imaginary")
    raw = discovery_preset("early")["progression"]
    raw["itinerary"]["unknown"] = True
    with pytest.raises(ValueError, match="unknown"):
        bind_itinerary(raw, {}, load_ruleset())


@pytest.mark.parametrize("preset_id", ["dungeon", "enemy_caster", "multiple_targets", "high_resistance"])
def test_encounter_presets_score_and_replay_real_births(preset_id):
    from dfo_optimizer.lifecycle import optimize_build, replay_build

    query = discovery_preset(preset_id)
    query.pop("class_search")
    query.pop("class_admission_strategy")
    query.update(families=[{"id": "reference", "baseline_id": "m1-breton-caster"}], roll_seeds=[42])
    result = optimize_build(query)
    assert result["candidates"] and not result["gaps"]
    assert all(r["checkpoints"][-1]["encounter"]["casts"] > 0 for r in result["candidates"])
    assert replay_build(result)["validated"]


def test_progression_preset_buys_missing_school_and_can_reach_first_earned_level():
    from dfo_optimizer.lifecycle import optimize_build, replay_build

    rules = load_ruleset()
    start = resolve_family_baseline("m1-breton-caster", rules)
    start["class"]["skills"] = {"primary": [24, 26, 23], "major": [27, 25, 14], "minor": [22, 1, 2, 3, 4, 5]}
    query = discovery_preset("early")
    query.pop("class_search")
    query.pop("class_admission_strategy")
    query.update(families=[{"id": "Destruction minor", "start": start}], roll_seeds=[42])
    result = optimize_build(query)
    assert result["candidates"] and result["candidates"][0]["final_level"] >= 2
    route = result["candidates"][0]
    assert any(a["kind"] == "buy" and a["record"]["custom"] for a in route["actions"])
    assert any(a["kind"] == "collect_gold" and a["amount"] == 160 for a in route["actions"])
    assert route["checkpoints"][-1]["dps"] > 0
    assert replay_build(result)["validated"]


def test_coherent_allocator_and_named_mastery_priorities_build_finite_alternatives():
    rules = load_ruleset()
    start = {**resolve_family_baseline("m1-breton-caster", rules), "roll_seed": 42}
    q = discovery_preset("early")["progression"]
    q["itinerary"]["mastery_priority"] = ["Stealth", "Restoration", "Lockpicking"]
    bound = bind_itinerary(q, start, rules)
    picks = bound["cycles"][-1]["windows"][-1]
    assert [a["allocation_policy"] for a in picks] == [0, 1]
    assert len({tuple(a["allocation_order"]) for a in picks}) == 2
    q["itinerary"]["alternate_allocation_orders"] = [q["itinerary"]["allocation_order"]]
    with pytest.raises(ValueError, match="distinct"):
        bind_itinerary(q, start, rules)


def test_explicit_path_selection_and_signature_purchase_are_separate_opportunities():
    rules = load_ruleset()
    start = {**resolve_family_baseline("m1-breton-caster", rules), "roll_seed": 42}
    path = next(p for p in rules["progression_rules"]["paths"] if p["family"] == "arcane")
    query = discovery_preset("creation_to_cap")["progression"]
    query["itinerary"]["specialization"] = {"path": path["id"], "after_circuit": 100}
    a = bind_itinerary(query, start, rules)
    assert a["goal"]["arcane_path"] == path["id"] and "known" not in a["goal"]
    assert any(row[0]["kind"] == "choose" for cycle in a["cycles"] for row in cycle["windows"])
    query["itinerary"]["specialization"]["signature_offer"] = {
        "gold_cost": 25,
        "evidence": "Conditional quote",
    }
    bound = bind_itinerary(query, start, rules)
    bought = next(
        row[0]
        for c in bound["cycles"]
        for row in c["windows"]
        if row[0].get("path") and row[0]["kind"] == "buy"
    )
    law = next(p for p in rules["encounter_paths"] if p["id"] == path["id"])
    assert bought["record"]["index"] == law["index"] and bought["record"]["name"] == law["name"]
    assert bought["record"]["effects"][0]["type"] == law["slots"][0]["type"]
    bad = {"gold_cost": 25, "evidence": "Quoted signature", "record": {"index": 0}}
    query["itinerary"]["specialization"]["signature_offer"] = bad
    with pytest.raises(ValueError, match="signature"):
        bind_itinerary(query, start, rules)
