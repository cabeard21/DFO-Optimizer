import json
from pathlib import Path

import pytest

from dfo_optimizer.lifecycle import optimize_build, replay_build


def request():
    path = Path(__file__).resolve().parents[1] / "examples" / "build-checkpoint-reversal.json"
    q = json.loads(path.read_text())
    q["spellbook"]["policies"] = [["known/990"],["mixed-bolt"]]
    q["encounter"] = {"seed":41,"at":"checkpoints","idle_us":2_000_000,
                      "evidence":"Separated foe groups with stationary safe downtime",
                      "scenario":{"id":"held room","evidence":"One ordinary stationary opponent",
                                  "horizon_us":1_500_000,
                                  "enemies":[{"id":"foe","hp":300,"willpower":45,"x_mm":0,"z_mm":0}],
                                  "incoming":[{"time_us":100,"source":0,"kind":"spell","damage":2}]}}
    return q


def test_chained_encounter_checkpoints_debit_real_hp_and_sp():
    q = request()
    out = optimize_build(q)
    assert out["status"] == "optimal_proven" and replay_build(out)["validated"]
    for row in out["candidates"]:
        first, second = row["checkpoints"]
        assert second["encounter"]["initial_hp"] == first["encounter"]["end_hp"]
        assert second["sp_available"] == first["sp_after_policy"]
        assert first["encounter"]["initial_hp"] > first["encounter"]["end_hp"]
        assert first["policy_sp"] > 0
        assert second["dps"] == pytest.approx(second["encounter"]["damage"]/1.5)


def test_frozen_terminal_encounter_remains_replayable():
    q=request()
    q["encounter"]["at"]="terminal"
    out=optimize_build(q)
    assert out["candidates"] and replay_build(out)["validated"]
    assert [s["stage"] for s in out["candidates"][0]["checkpoints"]] == [1]


def test_gear_and_book_encounters_use_the_same_access_checked_route():
    from dfo_optimizer.gear import evaluate_gear, optimize_gear
    from dfo_optimizer.spellbook import evaluate_spellbook, optimize_spellbook

    fixture = Path(__file__).resolve().parents[1] / "examples" / "progression-tradeoffs.json"
    start = json.loads(fixture.read_text())["start"]
    q = dict(character=start["character"], live_observations=start["live_observations"],
             encounter={**request()["encounter"], "at":"terminal"},
             spellbook={"policies":[["known/-1"]]}, search={"exact":True})
    for service in (evaluate_gear, optimize_gear, evaluate_spellbook, optimize_spellbook):
        plan = service(q)
        assert plan["status"] == "optimal_proven" and replay_build(plan)["validated"]
        step = plan["candidates"][0]["checkpoints"][0]
        assert step["casting_policy"] == ["known/-1"] and step["encounter"]["casts"] > 0
    with pytest.raises(ValueError, match="owned_only"):
        optimize_gear({**q, "offers":[{}]})


def test_hostile_spells_and_intervening_recovery_need_evidence():
    q = request()
    q["encounter"]["scenario"]["incoming"] = [{"time_us":0, "kind":"bundle","spell":"hostile bolt"}]
    plan = optimize_build(q)
    assert not plan["exact"] and "hostile catalog" in str(plan["gaps"])


def test_dead_character_cannot_enter_second_fight():
    q = request()
    q["encounter"]["scenario"]["incoming"][0]["damage"] = 1_000_000
    plan = optimize_build(q)
    assert plan["status"] == "infeasible_proven" and not plan["candidates"]


def test_wellspring_restores_from_one_equipped_physical_roll():
    from dfo_optimizer.gear import evaluate_gear
    folder = Path(__file__).resolve().parents[1] / "examples"
    start = json.loads((folder / "progression-tradeoffs.json").read_text())["start"]
    ring = json.loads((folder / "gear-owned.json").read_text())["inventory"][0]["item"]
    start["character"]["items"].append({**ring, "affixes":[ring["affixes"][0],{"id":"wellspring","value":4}]})
    control = request()["encounter"]
    control["scenario"].update(enemies=[{"id":"foe","hp":1,"willpower":0,"x_mm":0,"z_mm":0}],
                               tape=[0.9]*8, incoming=[])
    q = dict(character=start["character"], live_observations=start["live_observations"],
             encounter={**control,"at":"terminal"}, search={"exact":True})
    equipped = evaluate_gear(q)
    empty = evaluate_gear({**q,"loadout":{}})
    assert replay_build(equipped)["validated"] and replay_build(empty)["validated"]
    worn = equipped["candidates"][0]["checkpoints"][0]["encounter"]
    bare = empty["candidates"][0]["checkpoints"][0]["encounter"]
    assert worn["kills"] == bare["kills"] == 1
    assert worn["end_sp"] - bare["end_sp"] == worn["restored_sp"] == 8


def test_burst_winner_reverses_in_a_sustained_fight_with_the_same_pool():
    fixture = Path(__file__).resolve().parents[1] / "examples" / "build-encounter-reversal.json"
    q = json.loads(fixture.read_text())
    burst = optimize_build(q)
    q["encounter"]["scenario"]["horizon_us"] = 20_000_000
    sustained = optimize_build(q)
    for plan, name in ((burst, "surge"), (sustained, "spark")):
        assert plan["exact"] and replay_build(plan)["validated"], plan["gaps"]
        strongest = max((r["checkpoints"][0] for r in plan["candidates"]), key=lambda c:c["dps"])
        assert strongest["casting_policy"] == [name]


def test_imported_path_requires_the_source_mastery_pair():
    from dfo_optimizer.spellbook import optimize_spellbook
    from dfo_optimizer.ruleset import load_ruleset

    start = json.loads((Path(__file__).resolve().parents[1] / "examples/progression-tradeoffs.json").read_text())["start"]
    path = next(p for p in load_ruleset()["progression_rules"]["paths"] if p["id"] == "riftwalker")
    save = {**start["character"], "arcanePath":"riftwalker", "masteredSkills":path["skills"]}
    for skill in path["skills"]:
        save["skills"][skill] = 100
    query = dict(character=save, live_observations=start["live_observations"],
                 encounter={**request()["encounter"], "at":"terminal",
                            "path_evidence":{"source":"Observed active path in ordinary PvE",
                                             "context":"ordinary_online_pve","initial_state":"fresh","observed_at_ms":1}},
                 search={"exact":True})
    legal = optimize_spellbook(query)
    assert legal["candidates"] and replay_build(legal)["validated"], legal["gaps"]
    bad = optimize_spellbook({**query,"character":{**save,"masteredSkills":[]}})
    assert not bad["candidates"] and "mastery pair" in str(bad["gaps"])


def test_active_funded_mage_stars_raise_actual_landed_damage():
    from dfo_optimizer.gear import evaluate_gear
    start = json.loads((Path(__file__).resolve().parents[1] / "examples/progression-tradeoffs.json").read_text())["start"]
    save = start["character"]
    effect = save["spells"][0]["effects"][0]
    effect["magnitudeBaseLow"] = effect["magnitudeBaseHigh"] = 40
    control = {**request()["encounter"], "at":"terminal",
               "firmament_evidence":{"source":"Unmentored online PvE sheet after tree attunement",
                   "observed_at_ms":1,"context":"ordinary_online_pve","in_force":True,"mentor_scale":1,
                   "sp_capacity_basis":"observed_with_tree"}}
    control["scenario"] = {**control["scenario"], "horizon_us":500000, "incoming":[],
                           "tape":[0.9]*20}
    q = dict(character=save, live_observations=start["live_observations"], encounter=control, search={"exact":True})
    base = evaluate_gear(q)
    oracle = json.loads((Path(__file__).parent / "fixtures/encounter-oracle.json").read_text())["permanent"]
    sky = {"tree":oracle["tree"],"renown":5,"profession_ranks":[0]*10,
           "source":"Synthetic observed paid tree","observed_at_ms":1,"character_id":save["characterId"],"access":True}
    signed = evaluate_gear({**q,"firmament":sky})
    assert signed["candidates"] and replay_build(signed)["validated"], signed["gaps"]
    old = base["candidates"][0]["checkpoints"][0]
    changed = signed["candidates"][0]["checkpoints"][0]
    assert (old["encounter"]["damage"], changed["encounter"]["damage"]) == (40,42)
    assert changed["firmament_modifiers"]["power_pct"] == oracle["stats"]["spellPower"] == 4
    assert oracle["fault"] is None and oracle["points"] == {"stars":2,"craft":0}
    stale = {**sky,"observed_at_ms":2}
    blocked = evaluate_gear({**q,"firmament":stale})
    assert not blocked["exact"] and "SP observed" in str(blocked["gaps"])
