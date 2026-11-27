"""Ordinary pinned online swings on the shared encounter event clock."""
import pytest
import json
from pathlib import Path

from test_encounter_native import damage, scene


def player(weapon=None, armor=()):
    return {"attributes": [50]*8, "skills": [50]*35, "race_id": 2,"fatigue":3000,
            "career": {}, "level": 1, "weapon": weapon, "armor": list(armor),
            "evidence": "Authored ordinary test actor, awake and facing target."}


def item(index, material, condition=100):
    return {"group": "Weapons" if index >= 113 else "Armor", "templateIndex": index,
            "material": material, "currentCondition": condition, "maxCondition": 100}


def combat(gear=None, armor=(), **changes):
    from dfo_optimizer.physical_encounter import ordinary_combat, ordinary_foe, freeze_physical
    scenario = scene(horizon=3_000_000, enemy_hp=90, **changes)
    spec = ordinary_combat([ordinary_foe()], evidence="Synthetic training duel in reach.")
    scenario["caster"].update(power_pct=0,pierce=0,cast_speed_pct=0)
    scenario["enemies"][0].update(x_mm=0,radius_mm=450)
    return {**scenario,"incoming":scenario.get("incoming",[]),"recovery":[],
            "physical":freeze_physical(player(gear, armor), spec, 1)}


@pytest.mark.parametrize("weapon", [None, item(113, 0), item(115, 1), item(113, 0, 1)])
def test_melee_starts_after_funded_spell_and_matches_reference(weapon):
    from dfo_optimizer import _encounter
    from dfo_optimizer.encounter_reference import simulate_trial
    s = combat(weapon, sp=10, incoming=[{"source":0, "kind":"melee", "time_us":1_700_000}])
    rules = [{"spell":0}]
    actual = _encounter.evaluate(s, [damage()], [rules], [33], trace=True)["rows"][0]["trials"][0]
    expected = simulate_trial(s, [damage()], rules, 33, trace=True)
    assert actual.pop("trace") == [tuple(row) for row in expected.pop("trace")]
    assert actual == expected
    assert actual["casts"] == 1 and actual["melee_swings"] > 0
    assert actual["incoming_swings"] == 1


def test_distant_target_does_not_offer_a_backup_swing():
    from dfo_optimizer import _encounter
    s = combat(item(113,1),sp=0)
    s["enemies"][0]["z_mm"] = 9000
    trial = _encounter.evaluate(s, [damage()], [[{"spell":0}]], [1])["rows"][0]["trials"][0]
    assert trial["melee_swings"] == trial["damage"] == 0


def test_mundane_lane_requires_supported_equipment_and_durability():
    for weapon in ({"templateIndex":113, "material":0},
                   {**item(113,1), "affixes":[{"id":"leech","value":4}]}):
        with pytest.raises(ValueError):
            combat(weapon)


def test_blows_and_schedules_against_pinned_online_js():
    from dfo_optimizer.physical_encounter import _fighter
    from dfo_optimizer.physical_reference import melee_blow
    from dfo_optimizer.encounter_reference import Draws
    fixture=json.loads((Path(__file__).parent/"fixtures/physical-oracle.json").read_text())
    for row in fixture["rows"]:
        incoming=row["incoming"]
        def actor(is_player, weapon, armor):
            spec=player(weapon,armor)
            if not is_player:
                spec.pop("fatigue")
                spec.update(career_index=1,min_metal=-1)
            return _fighter(spec,is_player,16667)
        a=actor(not incoming,row["weapon"],[])
        t=actor(incoming,None,[row["protection"]] if row["protection"] else [])
        rng=Draws(0,[row["roll"]]*20)
        result=melee_blow(a,t,not incoming,50,50,50,50,rng)
        assert (*result,rng.cursor,a["weapon"][2])==(row["damage"],row["hit"],row["part"],row["cursor"],row["condition"]), row
    for case in fixture["timing"]:
        raw=player(item(case["id"],1) if case["id"]>=0 else None)
        raw["attributes"][0],raw["attributes"][6]=47,case["speed"]
        assert _fighter(raw,True,16667)["armed"][-2:]==[case["hit"],case["ready"]]


def test_safe_fatigue_policy_and_carried_physical_only_state():
    from dfo_optimizer import _encounter
    from dfo_optimizer.encounter_reference import simulate_trial
    s=combat(None,sp=0)
    s["physical"]["fatigue"]=16
    row=_encounter.evaluate(s,[],[[]],[17],trace=True)["rows"][0]["trials"][0]
    scalar=simulate_trial(s,[],[],17,trace=True)
    assert row["melee_swings"]==1 and row["spent_fatigue"]==8 and row["end_fatigue"]==8
    assert row["melee_damage"]==scalar["melee_damage"] and row["end_fatigue"]==scalar["end_fatigue"]
    assert _encounter.evaluate(s,[],[[]],[17],max_events=1)["termination"]=="event_limit"


def test_every_native_first_blow_matches_source_damage_hit_part_and_draws():
    from dfo_optimizer import _encounter
    from dfo_optimizer.physical_encounter import freeze_physical,ordinary_combat,ordinary_foe
    vectors=json.loads((Path(__file__).parent/"fixtures/physical-oracle.json").read_text())["rows"]
    for row in vectors:
        foe=ordinary_foe(skill=50)
        foe["race_id"]=2
        incoming=row["incoming"]
        armor=[row["protection"]] if row["protection"] else []
        actor=player(None if incoming else row["weapon"],armor if incoming else [])
        foe["weapon"]=row["weapon"] if incoming else None
        foe["armor"]=[] if incoming else armor
        p=freeze_physical(actor,ordinary_combat([foe],evidence="Oracle trial"),1)
        swing=p["actors"][0]["armed"][-2]
        s=scene(sp=0,enemy_hp=100,horizon=1 if incoming else swing,physical=p,
                incoming=[{"source":0,"kind":"melee","time_us":1}] if incoming else [],tape=[row["roll"]]*20)
        out=_encounter.evaluate(s,[],[[]],[42],trace=True)["rows"][0]["trials"][0]
        kind=("enemy_melee" if incoming else "melee")+("_impact" if row["hit"] else "_miss")
        event=next(e for e in out["trace"] if e[1]==kind)
        assert (event[3],event[4],out["draws"])==(row["part"],row["damage"],row["cursor"])


def varied_fighters(row):
    from dfo_optimizer.physical_encounter import _fighter

    fighters=[]
    for i in range(2):
        is_player=(i==0)!=row["incoming"]
        spec=dict(attributes=row["attrs" if i==0 else "targetAttrs"],skills=[row["skills"][i]]*35,
                  weapon=row["rawW"] if not i else None,armor=row["coverings"] if i else [],
                  race_id=row["race"],level=row["levels"][i],career=row["career"],evidence="Upstream fixture")
        if not is_player: spec.update(career_index=row["careerIndex"],min_metal=row["metal"])
        fighters.append(_fighter(spec,is_player,16667))
    return fighters


def test_varied_races_proficiencies_soft_metal_and_consecutive_wear_match_game():
    from dfo_optimizer.physical_reference import melee_blow
    from dfo_optimizer.encounter_reference import Draws
    vectors=json.loads((Path(__file__).parent/"fixtures/physical-oracle.json").read_text())["varied"]
    for row in vectors:
        attacker,target=varied_fighters(row)
        rng=Draws(row["seed"],[])
        for expected in row["outputs"]:
            d,hit,part=melee_blow(attacker,target,not row["incoming"],10,100,10,100,rng)
            assert [d,hit,part,rng.cursor,attacker["weapon"][2],
                    target["armor"][3][0],target["armor"][7][0]]==expected,row


def test_native_consecutive_contacts_follow_the_upstream_paired_draw_stream():
    from dfo_optimizer import _encounter
    vectors=json.loads((Path(__file__).parent/"fixtures/physical-oracle.json").read_text())["varied"]
    for row in vectors:
        incoming=row["incoming"]
        fighters=varied_fighters(row)
        if incoming: fighters.reverse()
        # The source fixture has both adrenal rushes active, cancelling in the
        # hit roll. Full pools keep that same net term and avoid HP clipping.
        scene_config=scene(sp=0,hp=1_000_000,enemy_hp=1_000_000,horizon=20_000_000,max_hp=1_000_000,allow_wait=incoming,
                           physical={"actors":fighters,"fatigue":33,"fallback":not incoming,"enemy_reach_mm":2250},
                           incoming=[{"kind":"melee","source":0,"time_us":i*1_000_000} for i in range(4)] if incoming else [])
        trial=_encounter.evaluate(scene_config,[],[[]],[row["seed"]],trace=True)["rows"][0]["trials"][0]
        prefix="enemy_melee_" if incoming else "melee_"
        contacts=[(e[4],e[1]==prefix+"impact",e[3]) for e in trial["trace"] if e[1] in (prefix+"impact",prefix+"miss")]
        assert contacts==[tuple(expected[:3]) for expected in row["outputs"]],row["seed"]
        assert trial["draws"]==row["outputs"][-1][3]


def two_room_physical_result():
    from dfo_optimizer.encounter import evaluate_encounter
    from dfo_optimizer.physical_encounter import ordinary_combat,ordinary_foe
    raw=json.loads((Path(__file__).parents[1]/"examples/encounter-miss.json").read_text())
    weapon={**item(113,0,1),"maxCondition":50}
    caster={**player(weapon),"fatigue":17,"level":raw["actor"]["level"]}
    caster["attributes"][0]=100
    raw["actor"].update(physical=caster,has_spellbook=False)
    raw["spells"]=[]
    raw["policies"]=[{"id":"backup-only","rules":[]}]
    foe={"id":"first","hp":1,"willpower":50,"x_mm":1000,"z_mm":0}
    raw["scenario"].update(physical=ordinary_combat([ordinary_foe() for _ in range(2)],evidence="Two authored duels"),
                           enemies=[foe,{**foe,"id":"second"}],tape=[0.0]*30,
                           rooms=[{"id":"one","enemies":[0],"delay_us":0},{"id":"two","enemies":[1],"delay_us":0}])
    return evaluate_encounter(raw)


def test_physical_only_public_replay_preserves_wear_and_fatigue_across_rooms():
    from dfo_optimizer.encounter import replay_encounter
    result=two_room_physical_result()
    assert result["status"]=="evaluated"
    trial=result["winner"]["first_trial"]
    assert trial["melee_swings"]==trial["kills"]==2
    assert trial["spent_fatigue"]==16 and trial["end_fatigue"]==1
    assert trial["casts"]==0 and replay_encounter(result)["valid"]
    starts=[entry for entry in result["winner"]["trace"] if entry[1]=="melee_start"]
    assert [e[2] for e in starts]==[0,1]
    # First wear migrates the old iron dagger's single remaining point to
    # its current pool. The second swing uses the retained blade's schedule.
    assert starts[0][4]==starts[1][4]


def test_replay_refuses_stale_physical_law_even_when_damage_matches():
    from dfo_optimizer.encounter import _identity,replay_encounter
    result=two_room_physical_result()
    result["physical_mechanics"]["law_sha256"]="0"*64
    result["result_hash"]=_identity(result)
    with pytest.raises(ValueError,match="physical law"):
        replay_encounter(result)


def test_mixed_physical_and_spell_models_share_the_same_combatants():
    from dfo_optimizer.encounter_request import freeze_encounter
    request=two_room_physical_result()["frozen_request"]
    request["scenario"]["enemies"][0]["willpower"]=81
    with pytest.raises(ValueError,match="physical enemy"):
        freeze_encounter(request)
    request["scenario"]["enemies"][0]["willpower"]=50
    request["actor"]["defense"]={"willpower":80}
    with pytest.raises(ValueError,match="physical actor"):
        freeze_encounter(request)


def test_shared_authenticated_physical_tables_resist_accidental_mutation():
    from dfo_optimizer.physical_encounter import laws
    weapon=laws()["weapons"]["113"]
    with pytest.raises(TypeError):
        weapon["weight"]=weapon["weight"]
    with pytest.raises(TypeError):
        weapon["span"][0]=weapon["span"][0]

