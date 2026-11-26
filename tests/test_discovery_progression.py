"""Prospective school practice and ordinary online creation-to-cap vitals."""
import json
from pathlib import Path

import pytest

from dfo_optimizer import _progression
from dfo_optimizer.progression import _prepare, plan_progression, replay_progression
from dfo_optimizer.progression_practice import release_cost
from dfo_optimizer.progression_replay import initial_effort, transition
from dfo_optimizer.ruleset import load_ruleset


ROOT = Path(__file__).resolve().parents[1]


def request():
    start = json.loads((ROOT / "examples/progression-creation-to-cap.json").read_text())["start"]
    start["class"]["skills"] = {"primary": [22, 23, 26], "major": [24, 25, 27], "minor": list(range(6))}
    return {"start": start, "project_creation_vitals": True, "require_starting_damage": False,
            "goal": {"level": 1}, "search": {"exact": True, "final_stage_only": True}}


@pytest.mark.parametrize(("skill", "spell"), [(22, 991), (23, 995), (24, 993), (25, 992),
                                             (26, 997), (27, 998)])
def test_all_schools_pay_actual_cost_and_tally(skill, spell):
    req = request()
    req["stages"] = [[{"kind": "practice", "skill": skill, "spell": spell, "count": 150,
                       "until_spent": True, "cadence_ms": 120000,
                       "evidence": "Declared safe opportunities for paid releases."}],
                     [{"kind": "rest", "site": "bed", "recovery": "full_bed",
                       "evidence": "An uninterrupted full-priced bed is available."}]]
    req["search"]["retain_states"] = True
    plan = plan_progression(req)
    assert plan["exact"] and replay_progression(plan)["valid"]
    initial, practiced, rested = [cp["state"] for cp in plan["routes"][0]["checkpoints"]]
    assert 0 <= practiced["sp"] < initial["sp"]
    assert 0 < practiced["uses"][skill] < 150
    assert initial["sp"] == rested["sp"] == rested["max_sp"]


def test_paired_online_level_health_increment_and_retroactive_floor():
    req = json.loads((ROOT / "examples/progression-creation-to-cap.json").read_text())
    req["project_creation_vitals"] = True
    plan = plan_progression(req)
    assert plan["exact"] and replay_progression(plan)["valid"]
    route = plan["routes"][0]
    final, initial = route["state"], route["checkpoints"][0]["state"]
    assert final["level"] == 45 and final["hp"] == initial["hp"]
    h = req["start"]["class"]["hitPointsPerLevel"]
    even = int(25 + h + 44 * max(1, (h // 2 + h) / 2 + final["attributes"][4] // 10 - 5))
    assert final["max_hp"] >= even and final["max_sp"] == 3 * final["attributes"][1]


def test_wrong_school_rejected_and_imported_vitals_stay_observational():
    req = request()
    req["stages"] = [[{"kind": "practice", "skill": 22, "spell": 993, "cadence_ms": 1400,
                       "evidence": "Wrong school."}]]
    plan = plan_progression(req)
    assert "school" in plan["excluded_actions"][0][0]["reason"]
    req = json.loads((ROOT / "examples/progression-tradeoffs.json").read_text())
    req["project_creation_vitals"] = True
    with pytest.raises(ValueError, match="new character"):
        plan_progression(req, base_dir=ROOT / "examples")


def test_native_and_scalar_transitions_match_pinned_game_operations():
    events = json.loads((ROOT / "tests/fixtures/progression-oracle.json").read_text())["events"]
    rules = load_ruleset()
    records = {r["index"]: r for r in rules["progression_rules"]["creation"]["generated_records"]}
    req = {**request(), "stages": []}
    _, _, _, _, _, _, _, _, template, _ = _prepare(req, rules)
    paths = {}
    for row in events:
        case, expected = row["input"], row["output"]
        if row["kind"] == "school_release":
            school, raw = case["school"], case["raw"]
            start = {**template, "known": [0], "skills": [raw] * 35,
                     "mastered": [school] if raw >= 100 else [], "sp": 320}
            action = {"kind": "practice", "skill": school, "spell": 0,
                      **release_cost(records[case["id"]], school)}
            native = _progression.search(start, [[action]], {}, final_stage_only=True)["results"][0]["state"]
            scalar, _ = transition(start, action, initial_effort())
            assert scalar["sp"] == native["sp"] == 320 - expected
        elif row["kind"] in ("level_vitals", "full_bed"):
            seed = case["rollSeed"]
            start = paths.get(seed, {**template, "attributes": [50,65,50,50,48,50,50,50],
                                     "raw_max_hp": 55, "hp": 37, "max_hp": 55, "sp": 12,
                                     "hp_roll_state": seed, "current_sum": 800})
            if row["kind"] == "full_bed":
                action = {"kind": "rest", "full_bed": True}
            else:
                start = {**start, "pending_level": start["level"] + 1}
                action = {"kind": "level", "allocation": [0,3,0,0,2,0,0,0]}
            native = _progression.search(start, [[action]], {}, final_stage_only=True)["results"][0]["state"]
            scalar, _ = transition(start, action, initial_effort())
            assert {k: native[k] for k in expected} == {k: scalar[k] for k in expected} == expected
            paths[seed] = scalar


def test_named_hypothetical_gold_stack_is_collected_once():
    events = json.loads((ROOT / "tests/fixtures/progression-oracle.json").read_text())["events"]
    case, = [r for r in events if r["kind"] == "collect_gold"]
    take = {"kind": "collect_gold", "copy": "lesson money", "amount": 321,
            "evidence": "Conditional known stack in a reachable container."}
    req = {**request(), "stages": [[take], [take, {"kind": "skip"}]]}
    plan = plan_progression(req)
    assert plan["exact"] and replay_progression(plan)["valid"]
    row, = plan["routes"]
    assert row["choices"] == [0,1]
    assert row["state"]["gold"] - row["checkpoints"][0]["state"]["gold"] == case["output"]["gold"] - case["input"]["gold"]
    assert case["output"]["repeated"] is False and case["output"]["pack_items"] == 0
    assert row["state"]["collected_gold_copies"] == ["lesson money"]
    with pytest.raises(ValueError, match="conflicting"):
        plan_progression({**req, "stages": [[take], [{**take, "amount": 322}]]})


def test_unresolved_passive_regeneration_stops_projected_current_hp_until_bed():
    req = {**request(), "stages": []}
    d, *_, start, _ = _prepare(req, load_ruleset())
    start = {**start, "career_regeneration": True, "hp": 11}
    wait = {"kind": "check", "minutes": 480}
    bed = {"kind": "rest", "full_bed": True}
    waited, effort = transition(start, wait, initial_effort())
    assert not waited["hp_known"]
    assert transition(waited, bed, effort)[0]["hp_known"]
    for acts, known in (([wait], False), ([wait, bed], True)):
        result = _progression.search(start, [[a] for a in acts], {}, final_stage_only=True)
        assert result["results"][0]["state"]["hp_known"] is known


def test_six_school_creation_itinerary_reaches_cap_with_a_paid_minor_school():
    from dfo_optimizer.discovery_presets import bind_itinerary, discovery_preset

    start = request()["start"]
    start["class"]["skills"] = {"primary": [22, 23, 26], "major": [24, 25, 3], "minor": [27, 1, 4, 5, 6, 7]}
    query = bind_itinerary(discovery_preset("creation_to_cap")["progression"], start, load_ruleset())
    # Constrain publications to the declared level milestones for this standalone oracle.
    plan = plan_progression({**query, "start": start})
    assert plan["exact"] and replay_progression(plan)["routes_checked"] == 1
    route, = plan["routes"]
    assert route["state"]["level"] == 45 and route["state"]["max_hp"] >= route["state"]["hp"] > 0
    assert set(route["state"]["mastered"]) == set(range(22, 28))
    assert any(a["kind"] == "buy" and a["record"]["custom"] and a["gold_cost"] > 0 for a in route["actions"])


def test_policy_binds_only_at_first_earned_level_and_replays_both_allocations():
    req = {**request(), "stages": []}
    _, _, _, _, _, _, _, _, start, _ = _prepare(req, load_ruleset())
    start.update(pending_level=2, current_sum=800, allocation_policy=-1)
    choices = [{"kind": "level", "if_due": True, "allocation_policy": i, "allocation_order": order}
               for i, order in enumerate(([1,6,4,0,2,3,5,7], [6,1,4,0,2,3,5,7]))]
    result = _progression.search(start, [choices]*4, {"level":5}, retain_states=True, final_stage_only=True)
    assert {tuple(r["choices"]) for r in result["results"]} == {(0,)*4, (1,)*4}
    for row in result["results"]:
        state, effort = start, initial_effort()
        for index in row["choices"]:
            state, effort = transition(state, choices[index], effort)
        assert state == row["state"] and row["state"]["allocation_policy"] == row["choices"][0]
    start.update(pending_level=-1)
    idle = _progression.search(start, [choices]*5, {}, final_stage_only=True, retain_states=True)
    assert [r["choices"] for r in idle["results"]] == [[0]*5]
