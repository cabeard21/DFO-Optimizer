"""Check the scalar finalist evaluator against real pinned JS, without a native module."""
import json
from pathlib import Path

import pytest

from dfo_optimizer.encounter_reference import _Replay
from dfo_optimizer.encounter_request import freeze_encounter
from dfo_optimizer.encounter_statistics import probability_intervals, single_cast_exact


ROOT=Path(__file__).resolve().parents[1]
ORACLE=json.loads((ROOT/"tests/fixtures/encounter-oracle.json").read_text(encoding="utf8"))
NAMES={"magnitudeBaseLow":"base_low","magnitudeBaseHigh":"base_high","magnitudeLevelBase":"plus_low",
       "magnitudeLevelHigh":"plus_high","magnitudePerLevel":"per_level","chanceBase":"chance_base",
       "chanceMod":"chance_increment","chancePerLevel":"chance_per_level","durationBase":"duration_base",
       "durationMod":"duration_increment","durationPerLevel":"duration_per_level"}


def shot():
    raw=json.loads((ROOT/"examples/encounter-miss.json").read_text(encoding="utf8"))
    raw["actor"].update(hp=50,max_hp=100,max_sp=200,current_sp=7,level=10,
         destruction_live=60,destruction_trained=60,defense={"willpower":50},
         school_trained={"restoration":60,"mysticism":60},
         school_live={"restoration":60,"mysticism":60,"alteration":60},
         school_climb={"restoration":60,"mysticism":60,"alteration":60})
    raw["scenario"]["enemies"][0].update(x_mm=1000,hp=60,willpower=50,level=10,sp=0,max_sp=200,absorb_skill=60,
        evidence="Upstream hostMagic test entity and frozen pool")
    raw["spells"][0].update(effects=[{"effect_id":"4,0","base_low":3,"base_high":9,"plus_low":1,"plus_high":3,"per_level":5}])
    raw["scenario"]["tape"]=[.99]*40
    return raw


def with_path(raw, martial="none", arcane="none"):
    rows = ORACLE["martial"]["paths"] + [
        {"id": p["id"], "skills": p["schools"]} for p in ORACLE["paths"]]
    mastered = sorted({skill for path in rows if path["id"] in (martial,arcane) for skill in path["skills"]})
    raw["actor"].update(path=arcane,martial_path=martial,mastered=mastered,
        path_evidence={"source":"Fresh source-oracle host entity","observed_at_ms":0,
                       "context":"ordinary_online_pve","initial_state":"fresh"})
    return raw


def test_source_martial_guard_and_dual_evade_order():
    oracle=ORACLE["martial"]
    guard=simulator(with_path(shot(),"vanguard"))
    hits=[]
    for _ in oracle["guard"]:
        before=guard.hp
        guard.hurt(7,True)
        hits.append(before-guard.hp)
    assert hits==oracle["guard"]
    assert guard.out["mitigated"]==28-sum(hits)
    raw=with_path(shot(),"bladedancer","seer")
    raw["scenario"]["tape"]=[.126,.099]
    dual=simulator(raw)
    dual.hurt(9,True)
    assert 50-dual.hp==oracle["evasion"]["lost"] and dual.rng.cursor==2


def test_source_martial_hurt_round_kill_and_speed_basis():
    oracle=ORACLE["martial"]
    jug=simulator(with_path(shot(),"juggernaut"))
    jug.hp=60
    jug.hurt(31,False)
    assert jug.hp==oracle["juggernaut"]
    brawl=simulator(with_path(shot(),"brawler"))
    brawl.round()
    assert brawl.hp==oracle["round_hp"]
    raw=with_path(shot(),"bloodletter")
    raw["scenario"]["enemies"][0]["hp"]=1
    blood=simulator(raw)
    blood.landed(0,(0,0,1,7))
    assert blood.hp==oracle["kill_hp"]
    raw=with_path(shot(),"windrunner")
    assert freeze_encounter(raw)["blockers"]
    raw["actor"]["path_evidence"]["speed_basis"]="before_martial_fold"
    assert simulator(raw).c["speed"]==50+oracle["windborne"]
    raw["actor"]["path_evidence"]["speed_basis"]="observed_final"
    assert simulator(raw).c["speed"]==50


def test_unverified_martial_state_and_active_techniques_are_not_scored():
    raw=with_path(shot(),"crusader")
    assert freeze_encounter(raw)["blockers"]
    raw=with_path(shot(),"brawler")
    del raw["actor"]["path_evidence"]
    assert freeze_encounter(raw)["blockers"]
    raw=with_path(shot(),"brawler")
    raw["actor"]["mastered"].pop()
    assert freeze_encounter(raw)["blockers"]


def simulator(raw):
    frozen=freeze_encounter(raw)
    assert not frozen["blockers"]
    return _Replay(frozen["scenario"],frozen["spells"],frozen["policies"][0],1,True)


@pytest.mark.parametrize("observed",ORACLE["defenses"],ids=lambda x:x["flavor"])
def test_source_defensive_chain(observed):
    raw=shot()
    raw["spells"][0]["effects"]*=2
    key={"reflect":"reflect_chance","resist":"resist_chance"}.get(observed["flavor"],"career_absorbs")
    wards={key:True if key=="career_absorbs" else 100,"evidence":"Oracle fixture","active_through_us":9_000_000}
    foe=raw["scenario"]["enemies"][0]
    foe["wards"]=wards
    if observed["flavor"]=="room": foe["sp"]=199
    self_hit=observed["flavor"]=="self"
    if self_hit: raw["actor"]["wards"]=wards
    r=simulator(raw)
    r.last_cost=7
    r.landed(-1 if self_hit else 0,(0,0,1,7))
    assert (r.hp,r.sp,r.hps[0],r.foe_sp[0],r.rng.cursor)==(
        observed["hp"],observed["sp"],observed["foe_hp"],observed["foe_sp"],observed["draws"])
    assert sum(event[1]=="reflected" for event in r.out["trace"])==observed["reflected"]


@pytest.mark.parametrize("observed",ORACLE["signature_casts"],ids=lambda x:x["id"])
def test_source_signature_cost_and_ordered_effects(observed):
    raw=shot()
    path=next(p for p in ORACLE["paths"] if p["id"]==observed["id"])
    with_path(raw,arcane=path["id"])
    raw["actor"].update(path=path["id"],mastered=path["schools"],current_sp=0,known_signature_indices=[path["index"]])
    raw["scenario"]["tape"]=[.05]*32
    raw["scenario"]["enemies"][0].update(hp=100,critical_weakness=2|32)
    raw["spells"][0].update(signature=path["index"],element=path["element"],range_type=path["range_type"],evidence="Source oracle shelf",
        effects=[{"effect_id":f'{e["type"]},{e["subType"]}',**{NAMES[k]:v for k,v in e["settings"].items()}}
                 for e in path["slots"]])
    r=simulator(raw)
    for i,expected in enumerate(observed["results"]):
        paid=r.spells[0]["cost_sp"]
        before=r.hps[0]
        r.landed(0,(0,0,i+1,paid))
        assert (paid,before-r.hps[0],r.hps[0],r.hp,r.sp,r.rng.cursor,r.shield,r.silence[1])==(
             expected["paid"],expected["damage"],expected["foe_hp"],expected["hp"],expected["sp"],
             expected["draws"],expected["shield"],expected["silence"])


def test_no_confidence_interval_for_repeated_identical_tape_and_small_distribution():
    raw=shot()
    raw["scenario"].pop("tape")
    raw["scenario"]["enemies"][0]["hp"]=1
    raw["actor"]["current_sp"]=22
    r=simulator(raw)
    analytic=single_cast_exact(r.s,r.spells,r.policy)
    assert analytic["outcomes"]==210000 and 0<analytic["clear_probability"]<1
    assert analytic["clear_probability"]==analytic["expected_hostile_hp_loss"]
    rows=[r.run()]
    assert probability_intervals(rows,[.4])["clear"] is None
    assert len(probability_intervals(rows,[])["clear"])==2


@pytest.mark.parametrize("name",("miss","duel","pack","dungeon"))
def test_independent_end_to_end_worked_request(name):
    raw=json.loads((ROOT/"examples"/f"encounter-{name}.json").read_text(encoding="utf8"))
    d=freeze_encounter(raw)
    assert not d["blockers"]
    for policy in d["policies"]:
        for seed in d["seeds"]:
            r=_Replay(d["scenario"],d["spells"],policy,seed,True).run()
            assert 0<=r["end_hp"]<=raw["actor"]["max_hp"]
            assert 0<=r["end_sp"]<=raw["actor"]["max_sp"]
            assert r["end_sp"]==r["initial_sp"]-r["spent_sp"]+r["restored_sp"]


def test_next_room_preserves_costs_and_never_leaks_future_victims():
    raw=shot()
    raw["actor"].update(current_sp=100,max_sp=100)
    raw["spells"][0]["range_type"]=3
    foe=raw["scenario"]["enemies"][0]
    foe.update(hp=1)
    raw["scenario"]["enemies"].append({**foe,"id":"second"})
    raw["scenario"]["rooms"]=[{"id":"entry","enemies":[0],"delay_us":0},
        {"id":"vault","enemies":[1],"delay_us":2_000_000,"rest_hp":80,"rest_sp":100,
         "evidence":"Uninterrupted protected rest after clearing the entry"}]
    raw["scenario"]["incoming"]=[{"source":1,"kind":"spell","damage":2,"time_us":0}]
    r=simulator(raw).run()
    events=r["trace"]
    assert [(e[0],e[2]) for e in events if e[1]=="impact"]==[(200000,0),(2400000,1)]
    assert [(e[0],e[4]) for e in events if e[1]=="room"]==[(2200000,1)]
    assert next(e for e in events if e[1]=="incoming")[0]==2200000
    assert r["rest_us"]==2000000 and r["cleared"] and r["end_hp"]==78
    assert r["draws"]==6
    raw["scenario"]["rooms"][1]["enemies"]=[0]
    with pytest.raises(ValueError): freeze_encounter(raw)
