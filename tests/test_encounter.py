"""Public fixed/search/replay contract and conditional finite-seed proof."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from dfo_optimizer.encounter import evaluate_encounter, optimize_encounter, replay_encounter
from dfo_optimizer.encounter_request import freeze_encounter
from dfo_optimizer.encounter_reference import simulate_trial


def encounter(name="miss"):
    return json.loads((Path(__file__).resolve().parents[1] / "examples" / f"encounter-{name}.json").read_text())


PATH_OBSERVATION={"source":"Observed fresh online test character","observed_at_ms":0,
                  "context":"ordinary_online_pve","initial_state":"fresh"}


def test_paid_miss_and_resource_failure_are_replayable():
    raw = encounter()
    untouched = deepcopy(raw)
    result = evaluate_encounter(raw)
    assert raw == untouched
    assert result["status"] == "evaluated"
    row = result["winner"]
    assert row["metrics"]["mean_sp_spent"] == 5
    assert row["metrics"]["mean_ending_sp"] == 0
    assert row["metrics"]["damage_per_sp"] == 0
    assert row["metrics"]["unfinished_trials"] == len(raw["seeds"])
    assert row["metrics"]["mean_kill_time_us"] is None
    assert any(e[1] == "miss" for e in row["trace"])
    assert row["probability_intervals"]["clear"][0]==0
    assert 0<row["probability_intervals"]["clear"][1]<1
    assert row["single_cast_exact"]["clear_probability"]==0
    assert replay_encounter(json.loads(json.dumps(result)))["valid"]


def test_finite_policy_search_and_dataset_identity():
    raw = encounter("pack")
    a, b = optimize_encounter(raw), optimize_encounter(deepcopy(raw))
    assert a["status"] == "optimal_proven" and a["exact"]
    assert a["result_hash"] == b["result_hash"]
    assert a["winner"] in a["frontier"] and a["counters"]["policies_completed"] == len(raw["policies"])
    assert a["seed_scope"]["seeds"] == raw["seeds"]
    assert replay_encounter(a)["policies_checked"] == len(a["frontier"])
    a["winner"]["metrics"]["mean_damage"] += 1
    with pytest.raises(ValueError):
        replay_encounter(a)


def test_unverified_effect_blocks_claim_and_bounded_policies():
    raw = encounter("pack")
    raw["spells"][0]["effects"][0]["effect_id"] = "999,3"
    refused = optimize_encounter(raw)
    assert refused["status"] == "unsupported" and refused["blockers"] and not refused["exact"]
    raw = encounter("pack")
    raw["search"] = {"max_policies":1}
    partial = optimize_encounter(raw)
    assert partial["winner"] and partial["status"] == "best_found_bounded" and not partial["exact"]
    assert replay_encounter(partial)["valid"]


def test_seeds_geometry_and_search_validate_at_boundary():
    raw = encounter()
    for key,val in (("seeds",[1,1]),("seeds",[]),("seeds",[True]),("unknown",1)):
        with pytest.raises(ValueError):
            evaluate_encounter({**raw,key:val})
    raw["scenario"]["enemies"][0]["x_mm"] = float("nan")
    with pytest.raises(ValueError):
        evaluate_encounter(raw)


def test_recasting_requires_observed_book_and_verified_world_round_clock():
    raw=encounter()
    for observed in (None,False):
        raw["actor"]["has_spellbook"]=observed
        assert evaluate_encounter(raw)["status"]=="unsupported"
    raw["actor"]["has_spellbook"]=True
    for field,value in (("round_period_us",1),("first_round_us",5_000_001)):
        result=evaluate_encounter({**raw,"scenario":{**raw["scenario"],field:value}})
        assert result["status"]=="unsupported" and not result["exact"]
    raw["scenario"]["first_round_us"]=0
    assert evaluate_encounter(raw)["winner"]["trace"][0][1]=="round"


def test_package_cache_never_trusts_a_caller_bundle_or_returns_mutable_catalogs():
    from dfo_optimizer.ruleset import load_ruleset
    raw=encounter()
    c=freeze_encounter(raw)
    c["spells"][0]["effects"][0]["base_low"]=123
    c["scenario"]["enemies"].clear()
    fresh=freeze_encounter(raw)
    assert fresh["scenario"]["enemies"] and fresh["spells"][0]["effects"][0]["base_low"]!=123
    caller=load_ruleset()
    caller["progression_rules"]["paths"].clear()
    with pytest.raises(ValueError):
        freeze_encounter(raw,caller)


@pytest.mark.parametrize("name",["dungeon","duel","pack"])
def test_all_example_policies_and_public_finite_frontier(name):
    raw=encounter(name)
    measured=[]
    for candidate in raw["policies"]:
        fixed=evaluate_encounter({**raw,"policies":[candidate]})
        assert fixed["status"]=="evaluated" and replay_encounter(fixed)["trials_checked"]==len(raw["seeds"])
        measured.append(fixed["winner"]["metrics"])
    def vector(m):
        return (m["clear_probability"],m["survival_probability"],m["kills_per_minute"],m["mean_damage"],
                -m["mean_sp_spent"],-m["censored_mean_clear_us"])
    vectors={vector(m) for m in measured}
    expected={v for v in vectors if not any(w!=v and all(a>=b for a,b in zip(w,v)) for w in vectors)}
    ranked=optimize_encounter(raw)
    assert {vector(row["metrics"]) for row in ranked["frontier"]}==expected
    assert ranked["timings"]["first_replayed_seconds"] is not None


def test_granted_path_pair_cost_and_real_item_rolls():
    raw=encounter("dungeon")
    raw["actor"].update(path="wardwright",mastered=[25,26],path_evidence=PATH_OBSERVATION,wellspring_items=[
        {"instance_id":"ringA","rarity":"magic","pct":4,"evidence":"Recorded worn ring roll"},
        {"instance_id":"amuletB","rarity":"rare","pct":7,"evidence":"Recorded worn amulet roll"}])
    c=freeze_encounter(raw)
    original=freeze_encounter(encounter("dungeon"))
    assert c["scenario"]["path_id"]==5 and c["scenario"]["wellspring_pct"]==10
    assert c["spells"][2]["cost_sp"]<original["spells"][2]["cost_sp"]
    assert optimize_encounter(raw)["status"]=="optimal_proven"
    raw["actor"]["mastered"]=[]
    assert optimize_encounter(raw)["status"]=="unsupported"
    raw["actor"]["wellspring_items"][0]["pct"]=15
    with pytest.raises(ValueError): freeze_encounter(raw)


def test_siphon_life_requires_earned_schools_and_exact_bundle():
    raw=encounter()
    raw["actor"].update(path="necromancer",mastered=[23,27],known_signature_indices=[-46113],path_evidence=PATH_OBSERVATION,
                        school_trained={"restoration":139,"mysticism":120},
                        school_live={"restoration":125,"mysticism":101},
                        school_climb={"restoration":111,"mysticism":105},
                        current_sp=60,hp=42)
    raw["spells"][0].update(signature=-46113,evidence="Observed Siphon Life spellbook record",effects=[{"effect_id":"4,0","base_low":8,"base_high":16,
        "plus_low":2,"plus_high":3,"per_level":1}])
    raw["scenario"]["enemies"][0]["x_mm"]=4000
    raw["scenario"]["tape"]=[.9]*100
    result=evaluate_encounter(raw)
    assert result["winner"]["metrics"]["mean_healing"]>0
    raw["spells"][0]["effects"][0]["base_high"]=200
    assert evaluate_encounter(raw)["status"]=="unsupported"


def test_coincident_hit_before_release_and_self_blast_defense():
    raw=encounter()
    raw["scenario"]["enemies"][0].update(x_mm=2000,hp=10)
    raw["scenario"]["incoming"]=[{"source":0,"kind":"spell","damage":64,"time_us":200000}]
    result=evaluate_encounter(raw)
    assert [row[1] for row in result["winner"]["trace"]]==["click","incoming","death"]
    raw["scenario"]["incoming"]=[]
    raw["spells"][0]["range_type"]=4
    assert evaluate_encounter(raw)["status"]=="unsupported"
    raw["actor"]["defense"]={"willpower":50}
    raw["scenario"]["tape"]=[.9]*30
    r=evaluate_encounter(raw)["winner"]
    assert r["metrics"]["mean_ending_hp"]<64


def test_cancel_and_budget_do_not_publish_partial_seed_panels():
    from dfo_optimizer import _encounter
    raw=encounter("pack")
    token=_encounter.CancelToken()
    token.cancel()
    assert optimize_encounter(raw,cancel=token)["status"]=="cancelled"
    for opts,termination in (({"max_events":1},"event_limit"),({"memory_bytes":1},"memory_limit")):
        result=optimize_encounter({**raw,"search":opts})
        assert result["termination"]==termination and result["winner"] is None and not result["exact"]


@pytest.mark.parametrize("reason",("cancelled","time_limit"))
def test_interrupt_scalar_verification_never_certifies_partial_panels(monkeypatch,reason):
    from dfo_optimizer import _encounter
    from dfo_optimizer import encounter as public
    token=_encounter.CancelToken()
    clock=[0.]
    real=public.simulate_trial
    calls=[]
    def interrupt(*args,**kwargs):
        row=real(*args,**kwargs)
        calls.append(row)
        if reason=="cancelled": token.cancel()
        else: clock[0]=20.
        return row
    monkeypatch.setattr(public,"simulate_trial",interrupt)
    monkeypatch.setattr(public,"perf_counter",lambda:clock[0])
    result=public.optimize_encounter({**encounter("pack"),"search":{"wall_seconds":10}},cancel=token)
    assert result["termination"]==reason and not result["exact"]
    assert len(calls)==1 and result["winner"] is None


def test_supplied_tape_exhaustion_and_potion_caps():
    raw=encounter()
    raw["scenario"]["enemies"][0]["x_mm"]=1000
    raw["scenario"]["tape"]=[.9]
    c=freeze_encounter(raw)
    with pytest.raises(ValueError,match="tape exhausted"):
        simulate_trial(c["scenario"],c["spells"],c["policies"][0],1)
    with pytest.raises(ValueError,match="tape exhausted"):
        evaluate_encounter(raw)
    raw["scenario"]["tape"]=[.9]*300
    raw["scenario"]["recovery"]=[{"kind":"potion","time_us":100,"hp":100,"sp":100,"evidence":"One measured potion"}]
    r=evaluate_encounter(raw)["winner"]
    assert r["first_trial"]["consumables"]==1 and r["first_trial"]["restored_sp"]==60


def test_single_cast_exhaustive_distribution_compares_sample_with_finite_law():
    raw=encounter()
    raw["scenario"]["enemies"][0].update(x_mm=1000,hp=1)
    result=evaluate_encounter(raw)["winner"]
    exact=result["single_cast_exact"]
    assert exact["outcomes"]==30000 and 0<exact["lethal_outcomes"]<exact["outcomes"]
    assert exact["expected_hostile_hp_loss"]==exact["clear_probability"]


def test_first_reflected_slot_suppresses_only_that_slot_and_refires_full_bundle():
    raw=encounter()
    raw["actor"].update(defense={"willpower":50},current_sp=5)
    foe=raw["scenario"]["enemies"][0]
    foe.update(x_mm=1000,wards={"reflect_chance":100,"evidence":"Observed constant reflection",
               "active_through_us":raw["scenario"]["horizon_us"]})
    raw["spells"][0]["effects"]*=2
    raw["scenario"]["tape"]=[.9]*100
    first=evaluate_encounter(raw)["winner"]
    impacts=[e for e in first["trace"] if e[1]=="impact"]
    assert [e[2] for e in impacts]==[0,-1]
    assert impacts[1][4]==2*impacts[0][4]>0
    assert [e[4] for e in first["trace"] if e[1]=="reflected"]==[0]
    assert first["first_trial"]["spent_sp"]==5


def test_absorption_refund_persists_and_full_pool_allows_later_damage():
    raw=encounter()
    raw["actor"].update(current_sp=50)
    raw["scenario"]["horizon_us"]=3_000_000
    foe=raw["scenario"]["enemies"][0]
    foe.update(x_mm=1000,level=1,sp=0,max_sp=5,absorb_skill=100,evidence="Frozen foe pool; no unlisted spell use",
               wards={"career_absorbs":True,"active_through_us":3_000_000,"evidence":"Source Always career flag"})
    raw["scenario"]["tape"]=[.9]*100
    row=evaluate_encounter(raw)["winner"]
    assert [event[4] for event in row["trace"] if event[1]=="absorbed"]==[5]
    assert row["metrics"]["mean_damage"]>0
    raw["scenario"]["enemies"][0]["wards"]["active_through_us"]=1
    assert evaluate_encounter(raw)["status"]=="unsupported"


def test_incoming_absorption_is_paid_by_original_caster_not_player_and_clips():
    raw=encounter()
    raw["actor"].update(current_sp=0,max_sp=5,defense={"willpower":50},
                        wards={"career_absorbs":True,"active_through_us":9000000,"evidence":"Always career observation"})
    foe=raw["scenario"]["enemies"][0]
    foe.update(level=1,x_mm=225000)
    raw["scenario"]["incoming"]=[{"kind":"bundle","time_us":n,"source":0,"spell":"bolt",
               "evidence":"Observed landing of a source bundle"} for n in (10,20)]
    raw["scenario"]["tape"]=[.9]*100
    row=evaluate_encounter(raw)["winner"]
    assert row["first_trial"]["restored_sp"]==2 and row["first_trial"]["end_hp"]<64


@pytest.mark.parametrize("path",("vanguard","bladedancer","juggernaut","bloodletter","brawler","windrunner"))
def test_martial_path_native_and_independent_trial_replay(path):
    from dfo_optimizer.ruleset import load_ruleset
    raw=encounter("duel")
    pair=next(p["skills"] for p in load_ruleset()["progression_rules"]["paths"] if p["id"]==path)
    raw["actor"].update(martial_path=path,mastered=pair,
        path_evidence={**PATH_OBSERVATION,"initial_state":"fresh","speed_basis":"before_martial_fold"})
    result=optimize_encounter(raw)
    assert result["status"]=="optimal_proven"
    assert replay_encounter(result)["trials_checked"]>=len(raw["seeds"])


def test_dungeon_example_can_reach_the_shaman_after_protected_rest():
    raw=encounter("dungeon")
    result=optimize_encounter(raw)
    rows=result["frontier"]
    assert any(row["metrics"]["mean_rest_us"]>0 and row["metrics"]["clear_probability"]>0 for row in rows)
