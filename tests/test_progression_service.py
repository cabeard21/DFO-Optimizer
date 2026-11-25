"""Independent legality replay, finite graph parity and frozen-route workflows."""
import copy
import itertools
import json
from pathlib import Path

import pytest

from dfo_optimizer.progression_replay import initial_effort, transition, goal_met
from dfo_optimizer.progression import (_freeze, _identity, _prepare, _route, digest,
                                       plan_progression, replay_progression)
from dfo_optimizer.ruleset import load_ruleset


def example(name):
    path = Path(__file__).resolve().parents[1] / "examples" / f"progression-{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def lake():
    return {
        "skills": [20] * 35, "uses": [0] * 35, "progress": [0.] * 35,
        "fractions": [0.] * 35, "spam_recent": [0.] * 35, "spam_at": [0] * 35,
        "primary": [22, 23, 24], "major": [25, 26, 27], "minor": [0, 1, 2, 3, 4, 5],
        "attributes": [50] * 8, "mastered": [], "level": 1, "starting_sum": 120,
        "current_sum": 120, "advancement_multiplier": .3, "reflexes": 2,
        "minutes": 1000, "last_check": 1000, "last_training": 0, "last_rest": -1,
        "sp": 30, "gold": 200000, "fatigue": 5000, "known": [0], "real_ms": 0,
        "arcane_path": -1, "martial_path": -1, "challenge_at": -1, "challenge_level": 0,
        "pending_level": -1, "pending_pool": -1,
    }


def test_replay_strict_clock_and_one_raise_per_pass():
    s = lake()
    s["uses"][22] = 500
    after, cost = transition(s, {"kind": "check", "minutes": 360}, initial_effort())
    assert after["skills"] == s["skills"] and cost["rest_passes"] == 0
    after, cost = transition(after, {"kind": "check", "minutes": 1}, cost)
    assert after["skills"][22] == 21 and after["uses"][22] == 0
    assert s["uses"][22] == 500 and cost["minutes"] == 361


def test_mastery_resets_uses_but_keeps_fraction_and_unlock_is_separate():
    s = lake()
    s["skills"][22:24] = [100, 100]
    s["mastered"] = [23]
    s["uses"][22], s["fractions"][22] = 18, .5
    after, cost = transition(s, {"kind": "master", "skill": 22}, initial_effort())
    assert after["uses"][22] == 0 and after["fractions"][22] == .5
    after, cost = transition(after, {"kind": "choose", "family": "arcane",
                                     "path": 2, "pair": [22, 23]}, cost)
    assert after["known"] == [0]
    after, cost = transition(after, {"kind": "buy", "family": "arcane",
                                     "path": 2, "spell": 1, "gold_cost": 3}, cost)
    assert goal_met(after, {"arcane_path": 2, "known": [1]}) and cost["spent"] == 3
    with pytest.raises(ValueError, match="gold"):
        transition(after, {"kind": "reset", "family": "arcane"}, cost)


def test_quarter_credit_no_foe_and_spell_resources():
    s = lake()
    s["skills"][22] = 100
    s["mastered"] = [22]
    action = {"kind": "practice", "skill": 22, "count": 4, "amount": 1,
              "cadence_ms": 5000, "spell": 0, "sp_cost": 5}
    result, effort = transition(s, action, initial_effort())
    assert result["uses"][22] == 1 and result["sp"] == 10 and effort["practice"] == 4
    with pytest.raises(ValueError, match="SP"):
        transition(result, action, effort)


def test_reduced_exhaustive_path_frontier_and_determinism():
    request = example("tradeoffs")
    original = copy.deepcopy(request)
    ctx = _prepare(_freeze(request, None), load_ruleset())
    points = set()
    for choices in itertools.product(*(range(len(w)) for w in request["stages"])):
        path, end = _route(ctx, list(choices), public_choices=True)
        if goal_met(end, ctx[5]):
            e = path["effort"]
            points.add((e["practice"], e["minutes"], e["spent"]))
    result = plan_progression(request)
    assert result["status"] == "optimal_proven"
    assert points == {(1, 541, 100), (3, 361, 0)}
    assert {(r["effort"]["practice"], r["effort"]["minutes"], r["effort"]["spent"])
            for r in result["routes"]} == points
    assert request == original and plan_progression(request)["result_hash"] == result["result_hash"]
    assert replay_progression(json.loads(json.dumps(result)))["routes_checked"] == 2
    assert result["timings"]["first_replayed_seconds"] >= result["timings"]["native_seconds"]


def test_create_to_cap_and_post_cap_mastery():
    cap = plan_progression(example("creation-to-cap"))
    assert cap["status"] == "optimal_proven"
    route = cap["routes"][0]
    assert route["state"]["level"] == 45 and route["checkpoints"][0]["state"]["level"] == 1
    assert route["effort"]["rest_passes"] > 100 and route["effort"]["practice"] > 10000
    mastery = plan_progression(example("mastery"))
    assert replay_progression(mastery)["valid"]
    selected = mastery["routes"][0]
    assert selected["state"]["skills"][22] == 101 and selected["state"]["arcane_path"] == "battlemage"
    assert selected["checkpoints"][0]["state"]["arcane_path"] is None


def test_legacy_precise_gap_and_unavailable_observations():
    result = plan_progression(example("legacy-gap"), base_dir=Path(__file__).resolve().parents[1] / "examples")
    assert result["status"] == "unsupported" and result["first_gap"]["stage"] == 0
    assert result["prefix"]["state"]["skills"] is None and replay_progression(result)["prefix_checked"]


def test_incomplete_rules_and_bounded_incumbents():
    req = example("tradeoffs")
    req["stages"][0].append({"kind":"practice","skill":22,"spell":123,"evidence":"Unresolved record"})
    result = plan_progression(req)
    assert result["status"] == "best_found_bounded"
    assert "unresolved" in result["excluded_actions"][0][0]["reason"]
    assert replay_progression(json.loads(json.dumps(result)))["valid"]
    req["search"] = {"max_nodes":1}
    limited = plan_progression(req)
    assert not limited["exact"] and limited["termination"] == "node_limit"
    assert replay_progression(limited)["valid"]


@pytest.mark.parametrize("key,val", [("routes", [None]), ("routes",[{}]), ("routes",{}),
                                     ("first_gap",{}), ("exact",False), ("next_decision",None)])
def test_replay_refuses_modified_result(key, val):
    result = plan_progression(example("tradeoffs"))
    with pytest.raises(ValueError):
        replay_progression({**result, key:val})


def test_replay_rejects_malformed_frozen_request_and_fake_empty_frontier():
    result = plan_progression(example("tradeoffs"))
    bad = {**result, "frozen_request":{}, "input_hash":digest({})}
    with pytest.raises(ValueError):
        replay_progression(bad)
    no_routes = {**result, "routes":[], "prefix":result["routes"][0],
                 "first_gap":{"stage":2,"reasons":["declared activities ended before the goal"]}}
    no_routes["result_hash"] = _identity(no_routes)
    with pytest.raises(ValueError):
        replay_progression(no_routes)


def test_generator_retain_distinct_and_user_time_model():
    req = example("tradeoffs")
    windows = req.pop("stages")
    req["activities"] = windows[0] + windows[1]
    req["max_events"] = 2
    req["search"].update(final_stage_only=True, retain_states=True)
    req["time_model"] = {"seconds_by_kind":{"practice":2, "train":12, "check":20},
                         "source":"Measured active player seconds per event for this scenario"}
    result = plan_progression(req)
    assert len(result["routes"]) == 2
    assert {r["wall_time_to_train_seconds"] for r in result["routes"]} == {26, 32}
    assert replay_progression(result)["routes_checked"] == 2


@pytest.mark.parametrize("action,reason", [
    ({"kind":"check","trigger":"short_rest_end","minutes":361,"evidence":"Attempted short rest"}, "night"),
    ({"kind":"rest","refill_sp":200,"site":"rough","evidence":"Rough campsite"}, "bed or camp"),
    ({"kind":"train","skill":22,"guild":"MagesGuild","roll":10,"member":False,"evidence":"At guild"}, "membership"),
    ({"kind":"practice","skill":3,"activity":"motion","evidence":"Jump"}, "odometer"),
    ({"kind":"practice","skill":29,"activity":"practice","evidence":"Generic"}, "verified gameplay"),
    ({"kind":"practice","skill":22,"spell":-1,"cadence_ms":0,"evidence":"One cast"}, "cadence"),
])
def test_unavailable_activities_explain_gate(action, reason):
    req = example("tradeoffs")
    req["stages"] = [[action]]
    result = plan_progression(req)
    assert not result["routes"] and reason in str(result["first_gap"])
    assert replay_progression(result)["valid"]


def test_checks_require_completed_chargen():
    req = example("tradeoffs")
    req["start"]["character"]["chargenDone"] = False
    result = plan_progression(req)
    assert result["status"] == "unsupported" and "chargen" in str(result["first_gap"])


def test_classic_signed_use_shift_for_imported_counters():
    req = example("tradeoffs")
    req["start"]["character"]["skillUses"][22] = 32768
    req["stages"] = req["stages"][1:]
    plan = plan_progression(req)
    assert plan["status"] == "infeasible_proven"
    assert plan["prefix"]["state"]["skills"][22] == 20
    assert replay_progression(plan)["prefix_checked"]


def test_movement_distance_and_resource_cost_are_checked_by_replay():
    req = example("mastery")
    save = req["start"]["character"]
    save["skills"][3] = 100
    save["masteredSkills"] = [3]
    save["skillUses"][22] = 0
    req["goal"] = {"mastered":[3]}
    req["search"] = {"exact":True, "final_stage_only":True}
    req["stages"] = [[{"kind":"practice","skill":3,"count":6,"activity":"motion","horizontal_m":1.25,
                       "fatigue_cost":64,"evidence":"Recorded six forward jumps and a 64-unit exertion debit"}]]
    result = plan_progression(req)
    after = result["routes"][0]["state"]
    assert after["uses"][3] == 5 and after["fatigue"] == 27936
    assert replay_progression(result)["valid"]


def test_purchase_requires_ownership_and_charges_the_visible_price():
    req = example("tradeoffs")
    spell = dict(req["start"]["character"]["spells"][0], index=17)
    purchase = {"kind":"buy","gold_cost":13,"spell":17,"record":spell,"evidence":"Quoted offer at accessible seller"}
    req["goal"] = {"known":[17]}
    req["stages"] = [[purchase]]
    plan = plan_progression(req)
    route = plan["routes"][0]
    assert route["checkpoints"][0]["state"]["known"] == [-1]
    assert route["state"]["known"] == [-1,17] and route["effort"]["spent"] == 13
    assert replay_progression(plan)["valid"]
    purchase["gold_cost"] = 200001
    blocked = plan_progression(req)
    assert blocked["status"] == "infeasible_proven" and "gold" in str(blocked["first_gap"])


def test_stale_rules_and_special_spell_costs_cannot_fund_ordinary_start():
    req = example("tradeoffs")
    req["require_starting_damage"] = True
    req["start"]["character"]["spells"][0]["pvpKitCost"] = 30
    plan = plan_progression(req)
    assert plan["status"] == "unsupported" and plan["first_gap"]["stage"] == 0
    plan["ruleset_hash"] = "0"*64
    with pytest.raises(ValueError, match="ruleset mismatch"):
        replay_progression(plan)


@pytest.mark.parametrize("fare", [None, 30])
def test_arrival_requires_structured_fare_and_no_unpaid_travel(fare):
    req = example("tradeoffs")
    arrivals = req["stages"][1][0]
    if fare is None:
        arrivals.pop("fare_gold", None)
    else:
        arrivals["fare_gold"] = fare
    out = plan_progression(req)
    assert not out["routes"] and out["status"] == "unsupported"
    assert "fare" in str(out["first_gap"]) and replay_progression(out)["valid"]


def test_custom_environmental_magery_blocks_starting_damage_and_future_casts():
    req = example("creation-to-cap")
    req["start"]["profile"] = "custom"
    req["start"]["class"]["disadvantages"] = [
        {"primary": "lightPoweredMagery", "secondary": "unableToUseMagicInDarkness"}]
    req["stages"] = [req.pop("cycles")[0]["windows"][0]]
    req["goal"] = {"skills":{"22":100}}
    initial = plan_progression(req)
    assert initial["first_gap"]["stage"] == 0 and "environment" in str(initial["goal_blockers"])
    req["require_starting_damage"] = False
    later = plan_progression(req)
    assert later["first_gap"]["stage"] == 1 and "environment" in str(later["first_gap"])
    assert replay_progression(later)["valid"]

