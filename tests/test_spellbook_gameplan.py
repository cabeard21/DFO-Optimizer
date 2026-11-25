"""Policy prices stop at each retained cast and remain fixed throughout a native variation."""
from itertools import combinations_with_replacement
from pathlib import Path

import pytest

from dfo_optimizer import _spellbook, spellbook

REQUEST = dict(
    caster=dict(level=10, speed=50, destruction_live=90, destruction_trained=90,
                destruction_mastered=False, current_sp=200, max_sp=200, gold=1000,
                has_spellbook=True),
    target=dict(id="finite_target", hp=40, willpower=50),
    price_factor=1, exact=True, max_casts=3, maker_access=True,
    spells=[
        dict(id="Warm", route="known", spell=dict(element=4, range_type=1, effects=[
            dict(effect_id="4,0", base_low=3, base_high=4, plus_low=1, plus_high=1, per_level=3)])),
        dict(id="Wave", route="maker", spell=dict(element=0, range_type=2, effects=[
            dict(effect_id="5,255", chance_base=7, chance_increment=1, chance_per_level=5)])),
        dict(id="Paired", route="maker", spell=dict(element=2, range_type=3, effects=[
            dict(effect_id="5,255", chance_base=1, chance_increment=1, chance_per_level=5),
            dict(effect_id="4,0", base_low=6, base_high=8, plus_low=1, plus_high=1, per_level=4)])),
    ])


def tradeoff(curves):
    return {(round(s, 7), p, g) for s, p, g in curves
            if not any(v>=s and sp<=p and gp<=g and (v>s or sp<p or gp<g)
                       for v, sp, gp in curves)}


def test_each_proposed_spell_costs_once_through_moving_prices():
    books = spellbook.optimize_spellbook(REQUEST)
    assert books["status"] == "optimal_proven"
    pts = [entry["id"] for entry in REQUEST["spells"]]
    offered = []
    for fixed in combinations_with_replacement(pts, 3):
        a = spellbook.evaluate_spellbook({**REQUEST, "policy": list(fixed)})
        if a["candidates"]:
            v = a["candidates"][0]
            offered.append((v["expected_damage"], v["sp_spent"], v["gold_spent"]))
    seen = {(round(v["expected_damage"], 7), v["sp_spent"], v["gold_spent"]) for v in books["candidates"]}
    assert seen == tradeoff(offered)
    both = spellbook.evaluate_spellbook({**REQUEST, "policy": ["Wave", "Wave", "Wave"]})["candidates"][0]
    assert both["gold_spent"] == 840


def test_limit_affordability_loadout_and_immutable_spend():
    limits = dict(REQUEST, search={"max_nodes": 1})
    assert spellbook.optimize_spellbook(limits)["termination"] == "node_limit"
    with pytest.raises(ValueError, match="unknown spell"):
        spellbook.evaluate_spellbook(dict(REQUEST, policy=["Bogus"]))
    poor = dict(REQUEST, caster={**REQUEST["caster"], "current_sp":1}, policy=["Warm"])
    assert spellbook.evaluate_spellbook(poor)["status"] == "infeasible_proven"
    deficit = dict(REQUEST, unknown_field=1)
    with pytest.raises(ValueError, match="fields"):
        spellbook.optimize_spellbook(deficit)
    token = _spellbook.CancelToken()
    token.cancel()
    assert spellbook.optimize_spellbook(REQUEST, cancel=token)["termination"] == "cancelled"


def test_stationary_price_is_conditioned_on_a_real_spellmaker_hypothesis():
    trial = {**REQUEST, "price_factor": None, "max_casts":1}
    blocked = spellbook.optimize_spellbook(trial)
    assert blocked["status"] == "supported_subset"
    assert all(r["sp_spent"] == 5 for r in blocked["candidates"])
    assert any("maker" in i for i in blocked["unsupported_mechanics"])
    none = spellbook.evaluate_spellbook({**trial, "policy":["Wave"]})
    assert none["status"] == "unsupported"
    for key in ("search", "caster", "catalog"):
        if key == "search":
            with pytest.raises(ValueError):
                spellbook.optimize_spellbook({**REQUEST, "search":{"wall_seconds":float("nan")}})
        if key == "caster":
            cold = {**REQUEST, "caster":{**REQUEST["caster"],"current_sp":None}}
            assert spellbook.optimize_spellbook(cold)["status"] == "unsupported"
        if key == "catalog":
            with pytest.raises(ValueError, match="Duplicate"):
                spellbook.optimize_spellbook({**REQUEST, "spells":[*REQUEST["spells"],
                    {**REQUEST["spells"][0], "id":"Ember"}]})


def test_native_economy_rejects_unresolved_need_for_future_spellmakers():
    from dfo_optimizer.character import import_character
    target = Path(__file__).resolve().parent / "fixtures/character/export.zip"
    source = import_character(target, slot=0)
    base = {"id":"Ember", "route":"known", "spell":{"element":0,"range_type":1,"effects":[
             {"effect_id":"4,0","base_low":4,"base_high":6,"plus_low":1,"plus_high":1,"per_level":1}]}}
    spectator = {"id":"side", "route":"known", "spell":{"element":0,"range_type":1,"effects":[
             {"effect_id":"5,255","chance_base":4,"chance_increment":1,"chance_per_level":1}]}}
    elapsed = {"current_sp":{"value":42,"observed_at_ms":1780000000000,"source":"fixture"}}
    both = dict(character=source, live_observations=elapsed, target=REQUEST["target"], spells=[base,spectator])
    view = spellbook.optimize_spellbook(both)
    assert view["status"] == "supported_subset"
    assert view["candidates"][0]["policy"] == ["Ember"]
    assert any("side" in v for v in view["unsupported_mechanics"])
    assert not spellbook.evaluate_spellbook({**both,"policy":["side"]})["candidates"]


def test_safe_integer_gold_and_finite_cast_timing():
    rich = {**REQUEST, "caster": {**REQUEST["caster"], "gold": 2**53 - 1},
            "policy": ["Warm", "Warm", "Warm"]}
    output = spellbook.evaluate_spellbook(rich)
    row = output["candidates"][0]
    assert row["gold_spent"] == 0
    assert row["last_release_seconds"] == pytest.approx(1.6)
    assert row["ready_again_seconds"] == pytest.approx(2.1)
    assert {"spell.cadence", "spell.native_spellbook", "spell.multi_effect"} <= set(output["mechanic_ids"])
