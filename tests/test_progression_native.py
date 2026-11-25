"""Finite native progression paths and source boundary regressions."""
import itertools
import json
import math
from pathlib import Path

import pytest

from dfo_optimizer import _progression as native


def start(**changes):
    return dict(dict(skills=[10] * 35, uses=[0] * 35, fractions=[0.] * 35,
                     progress=[0.] * 35, attributes=[50] * 8,
                     primary=[22, 23, 24], major=[25, 26, 27], minor=list(range(6)),
                     mastered=[], level=1, starting_sum=150, current_sum=150,
                     reflexes=2, advancement_multiplier=.3, minutes=1000, last_check=1000,
                     last_training=0, pending_level=-1, pending_pool=-1, gold=40,
                     sp=20, fatigue=1000, known=[0], arcane_path=-1, martial_path=-1), **changes)


def search(starting, stages, goal=None, **kwargs):
    return native.search(starting, stages, goal or {}, final_stage_only=True, **kwargs)


def test_strict_rest_threshold_and_owed_level():
    uses = [0] * 35
    uses[22] = 100
    s = start(uses=uses)
    first = search(s, [[dict(kind="check", minutes=360)]])
    assert first["results"][0]["state"]["skills"][22] == 10
    result = search(s, [[dict(kind="check", minutes=361)]], {"skills": {22: 11}})
    assert result["results"][0]["state"]["skills"][22] == 11
    assert result["results"][0]["effort"] == {"practice": 0, "rest_passes": 1, "minutes": 361, "spent": 0}
    assert s["skills"][22] == 10


def test_magic_floor_carry_mastery_and_overflow():
    skills = [10] * 35
    skills[22] = 100
    uses = [0] * 35
    uses[22] = 20000
    s = start(skills=skills, uses=uses)
    acts = [[dict(kind="master", skill=22)], [dict(kind="practice", skill=22, count=4, amount=1,
               cadence_ms=500, challenge_level=0, spell=0, sp_cost=5, minutes=0)]]
    row = search(s, acts)["results"][0]
    assert row["state"]["uses"][22] == 1
    assert row["state"]["fractions"][22] == 0.
    assert row["state"]["sp"] == 0
    assert row["state"]["mastered"] == [22]
    s["sp"] = 19
    miss = search(s, acts)
    assert miss["results"] == []
    assert miss["prefix"]["choices"] == [0]


def test_train_strict_max_and_cooldown():
    a = dict(kind="train", skill=22, gold_cost=8, roll=20, fatigue_cost=180)
    for value, clock, permitted in [(50, 720, True), (51, 720, False), (50, 719, False)]:
        skills = [10] * 35
        skills[22] = value
        s = start(skills=skills, minutes=clock, last_check=0)
        rows = search(s, [[a]])["results"]
        assert bool(rows) == permitted
        if permitted:
            assert rows[0]["state"]["uses"][22] == 20
            assert rows[0]["state"]["last_training"] == 720
            assert rows[0]["state"]["minutes"] == 900


def test_search_retains_history_for_lifecycle_and_respects_edge_budgets():
    s = start()
    skip = {"kind": "skip"}
    buy = {"kind": "buy", "spell": 7, "gold_cost": 5}
    stages = [[skip, buy], [skip, buy]]
    result = search(s, stages, {"known": [7]}, retain_states=True)
    assert sorted(r["choices"] for r in result["results"]) == [[0, 1], [1, 0]]
    assert len(search(s, stages, {"known": [7]})["results"]) == 1
    token = native.CancelToken()
    token.cancel()
    assert search(s, stages, cancel=token)["termination"] == "cancelled"
    assert search(s, stages, max_nodes=1)["termination"] == "node_limit"
    assert search(s, stages, memory_bytes=1)["termination"] == "memory_limit"


def test_exhaustive_effort_frontier_and_invalid_crossings():
    s = start()
    stages = [[dict(kind="skip"), dict(kind="practice", skill=22, amount=1, count=2,
              cadence_ms=10, minutes=5)], [dict(kind="check", minutes=361),
              dict(kind="train", skill=22, roll=10, gold_cost=3, fatigue_cost=180)],
              [dict(kind="check", minutes=361)]]
    all_rows = []
    for indices in itertools.product(*[range(len(x)) for x in stages]):
        selected = [[row[i]] for row, i in zip(stages, indices)]
        all_rows.extend(search(s, selected, {"skills": {22: 11}})["results"])
    costs = {tuple(r["effort"].values()) for r in all_rows}
    expected = {c for c in costs if not any(c != o and all(b <= a for b, a in zip(o, c)) for o in costs)}
    got = search(s, stages, {"skills": {22: 11}})
    assert {tuple(r["effort"].values()) for r in got["results"]} == expected
    with pytest.raises(ValueError):
        search(s, [[{"kind": "master", "skill": 35}]])
    with pytest.raises(ValueError):
        search(start(skills=[0] * 34), [])


def test_budget_keeps_goal_already_evaluated():
    result = search(start(), [[{"kind":"buy","spell":12,"gold_cost":10},{"kind":"skip"}]],
                    {"known":[12]}, max_nodes=1)
    assert result["termination"] == "node_limit"
    assert result["results"][0]["choices"] == [0]


def test_specialization_eligibility_purchase_and_only_family_reset():
    skills = [10] * 35
    skills[22:25] = [100,100,100]
    s = start(skills=skills, mastered=[22,23], gold=95, bank_gold=199910, martial_path=0)
    choose = dict(kind="choose", family="arcane", path=5, pair=[22,23])
    buy = dict(kind="buy", family="arcane", path=5, spell=200, gold_cost=5)
    reset = dict(kind="reset", family="arcane")
    miss = search(s, [[buy]])
    assert not miss["results"]
    row = search(s, [[choose],[buy],[reset]], {"known":[200]})["results"][0]
    assert row["state"]["gold"] == row["state"]["bank_gold"] == 0
    assert row["state"]["martial_path"] == 0 and row["state"]["arcane_path"] == -1
    assert row["effort"]["spent"] == 200005
    assert search(s, [[dict(choose,pair=[22,24])]])["results"] == []


def test_night_checks_medical_and_prevents_immediate_second_night():
    s = start()
    stages = [[dict(kind="rest", refill_sp=25)], [dict(kind="rest")]]
    result = search(s, stages)
    assert not result["results"]
    assert result["prefix"]["state"]["uses"][0] == 8
    assert result["prefix"]["state"]["sp"] == 25
    assert result["prefix"]["state"]["last_rest"] == 1480


def test_online_level_45_attributes_and_postcap_mastery():
    skills = [100] * 35
    for i in (22,23,24,25,26): skills[i] = 200
    s = start(skills=skills, mastered=[22,23,24,25,26], current_sum=800, level=44,
              pending_level=45, attributes=[99] * 8)
    steps = [[dict(kind="level", allocation_order=list(range(8)))],
             [dict(kind="master", skill=1)],
             [dict(kind="practice", skill=1, amount=10000, count=1000, cadence_ms=60000)],
             [dict(kind="check", minutes=361)]]
    out = search(s, steps, {"level":45, "skills":{1:101}})["results"][0]
    assert out["state"]["attributes"] == [100]*5+[99]*3
    assert out["state"]["pending_level"] == -1
    assert out["state"]["level"] == 45
    assert out["state"]["skills"][1] == 101


def test_conditional_actions_and_online_owed_chain():
    s = start(current_sum=800, pending_level=2)
    stages = [[{"kind":"master","skill":22,"if_eligible":True}],
              [{"kind":"practice","skill":22,"until_skill":10,"count":1,"sp_cost":100}],
              [{"kind":"level","allocation":[0,5,0,0,0,0,0,0]}]]
    result = search(s, stages)["results"][0]
    assert result["effort"]["practice"] == 0
    assert result["state"]["level"] == 2 and result["state"]["pending_level"] == 3
    assert result["state"]["attributes"][1] == 55
    full = start(pending_level=2, attributes=[100]*8)
    assert search(full, [[{"kind":"level","allocation":[0]*8}]])["results"]
    assert not search(full, [[{"kind":"level","allocation":[1]*8}]])["results"]
    assert not search(start(), [[{"kind":"level","allocation":[0]*8}]])["results"]


def test_reduced_search_matches_independent_python_path_enumeration():
    # Each paying activity is one confirmed magic practice opportunity before a
    # single skill check. Independent reference uses the closed-form threshold.
    from math import floor
    import random
    s = start(sp=11)
    for seed in range(10):
        rng=random.Random(seed)
        opportunities = [[(rng.randint(1,3),rng.randint(1,3),rng.randint(0,3)) for _ in range(3)]
                         for _ in range(3)]
        stages = [[dict(kind="practice",skill=22,spell=0,count=count,sp_cost=sp,minutes=mins)
                   for count,sp,mins in row] for row in opportunities]
        stages.append([dict(kind="check",minutes=361)])
        costs = set()
        for path in itertools.product(*opportunities):
            uses=sum(x[0] for x in path)
            if sum(n*p for n,p,t in path)>11 or uses<floor(10*.3*1.04*2/5)+1: continue
            costs.add((uses,361+sum(x[2] for x in path)))
        expected={a for a in costs if not any(a!=b and b[0]<=a[0] and b[1]<=a[1] for b in costs)}
        result=search(s,stages,{"skills":{22:11}})
        assert {(r["effort"]["practice"],r["effort"]["minutes"]) for r in result["results"]} == expected


@pytest.mark.parametrize("skill,axis,stride", [(3,"horizontal_m",1.),(17,"vertical_m",3.),
                         (18,"vertical_m",.5),(21,"horizontal_m",1.)])
def test_motion_measures_actual_distance_without_spam(skill, axis, stride):
    skills=[10] * 35
    skills[skill]=100
    s=start(skills=skills, mastered=[skill], primary=[skill,22,23], minor=[0,1,2,4,5,6])
    # An initial mark earns zero, movement under the threshold carries forward.
    act=dict(kind="practice",skill=skill,count=5, **{axis:stride/4})
    result=search(s,[[act]])["results"][0]["state"]
    assert result["uses"][skill] == 1
    assert result["fractions"][skill] == 0
    assert result["spam_recent"][skill] == 0
    assert result["move_mark"][skill] == 5*stride/4


def source_fixture():
    return json.loads((Path(__file__).parent/"fixtures"/"progression-oracle.json").read_text(encoding="utf-8"))


def test_source_price_level_and_effective_skill_oracles():
    for row in source_fixture()["events"]:
        case, expected = row["input"], row["output"]
        if row["kind"]=="price":
            i, v, lv = case["skill"], case["raw"], case["level"]
            skills = [10]*35
            skills[i] = v
            ladder = 1 if v<100 else 1.5 if v<125 else 2 if v<150 else 4
            threshold = math.ceil(expected*ladder)
            for n, increased in [(threshold-1,0),(threshold,1)]:
                uses = [0]*35
                uses[i] = n
                s = start(skills=skills,uses=uses,level=lv,mastered=[i] if v>=100 else [])
                got = search(s,[[dict(kind="check",minutes=361)]])["results"][0]["state"]
                assert got["skills"][i] == v+increased, (case,n)
        elif row["kind"]=="effective":
            skills = [10]*35
            skills[22] = case["raw"]
            uses = [0]*35
            uses[23] = 1000
            s = start(skills=skills,uses=uses,mastered=[22],starting_sum=60,current_sum=60)
            got = search(s,[[dict(kind="check",minutes=361)]])["results"][0]["state"]
            assert got["current_sum"] == expected + 51
        elif row["kind"]=="online_level":
            s = start(starting_sum=case["anchor"],current_sum=case["held"],attributes=[100]*8)
            stages = [[dict(kind="check",minutes=361)]]+[[dict(kind="level",allocation=[0]*8,if_due=True)]]*44
            got = search(s,stages)["results"][0]["state"]
            assert got["level"] == expected


def test_source_timed_challenge_fraction_and_overflow_oracles():
    oracle=source_fixture()
    b=oracle["birth"]
    def actor(**overrides):
        return start(**dict(dict(skills=b["skills"],attributes=b["attributes"],
            advancement_multiplier=.3+2.7*12/52,starting_sum=b["starting_sum"],
            current_sum=b["current_sum"],minutes=b["last_check"],last_check=b["last_check"]),**overrides))
    for row in oracle["events"]:
        k, case, expected = row["kind"], row["input"], row["output"]
        if k=="check":
            uses = [0]*35
            uses[case["skill"]] = case["uses"]
            got=search(actor(uses=uses),[[dict(kind="check",minutes=case["delay"])]])["results"][0]["state"]
            assert (got["skills"][22],got["uses"][22],got["last_check"]) == (
                expected["raw"],expected["uses"],expected["last_check"])
        elif k=="real_use":
            i=case["skill"]
            skills=b["skills"].copy()
            skills[i]=case["raw"]
            stages=[]
            elapsed=0
            for j,now in enumerate(case["times"]):
                stages.append([dict(kind="practice",skill=i,amount=case["amount"],cadence_ms=now-elapsed,
                                    challenge_level=case["foe"] or 0 if j==0 else 0)])
                elapsed=now
                end=search(actor(skills=skills,mastered=[i]),stages)["results"][0]["state"]
                assert end["uses"][i]+end["fractions"][i] == pytest.approx(sum(expected[:j+1]))
        elif k=="bank":
            skills=b["skills"].copy()
            skills[22]=150
            uses=[0]*35
            uses[22]=60000
            stages=[[dict(kind="check",minutes=361)]]*(case["t"]//361)
            got=search(actor(skills=skills,uses=uses,mastered=[22]),stages)["results"][0]["state"]
            assert got["progress"][22] == pytest.approx(expected["progress"])
            assert got["skills"][22] == expected["raw"]
            assert got["uses"][22] == expected["uses"]


def test_stock_spell_byte_record_price():
    a=dict(kind="practice",skill=22,spell=0,recipe=[4,2,0,0,0,0,255])
    got=search(start(),[[a]])["results"][0]["state"]
    assert got["sp"] == 15


@pytest.mark.parametrize("last_rest, legal", [(-1,False),(1362,False),(1241,False),(1242,True),(1361,True)])
def test_short_rest_requires_recent_completed_night_at_action_time(last_rest, legal):
    action = dict(kind="check", short_rest=True, minutes=361)
    rows = search(start(last_rest=last_rest), [[action]])["results"]
    assert bool(rows) == legal


def test_motion_opportunity_charges_total_fatigue_before_tallies():
    motion = dict(kind="practice", skill=21, count=5, horizontal_m=3., fatigue_cost=1001)
    assert not search(start(fatigue=1000), [[motion]])["results"]
    state = search(start(fatigue=1002), [[motion]])["results"][0]["state"]
    assert state["fatigue"] == 1
    assert state["uses"][21] == 5


@pytest.mark.parametrize("uses,raised", [(32767,True),(32768,False),(65536,False),(65538,True)])
def test_ordinary_tally_uses_source_signed_shift(uses, raised):
    counts=[0]*35
    counts[22]=uses
    result=search(start(uses=counts), [[dict(kind="check",minutes=361)]])
    assert result["results"][0]["state"]["skills"][22] == 10 + raised


def test_bridge_accepts_supported_combat_modifiers_and_large_purse():
    source_gold=2**53-1
    a=dict(kind="practice",skill=22,spell=0,recipe=[4,1,9,10,1,1,20],skill_bonus=9980,focus_pct=1000)
    r=search(start(gold=source_gold), [[a],[dict(kind="check",minutes=2**31-1)]])["results"][0]
    assert r["state"]["sp"] == 16  # Floor five discounted by the game's 30% cap.
    assert r["state"]["gold"] == source_gold
