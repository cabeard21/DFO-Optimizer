from fractions import Fraction

import pytest


def scene(*, hp=50, sp=20, enemy_hp=500, horizon=1_000_000, **overrides):
    return {
        "caster": {"level": 1, "live_skill": 60, "climb": 60, "speed": 50, "available_sp": sp,
                   "willpower": 50, "target_hp": enemy_hp},
        "hp": hp, "max_hp": 50, "max_sp": 20, "horizon_us": horizon,
        "first_round_us": 5_000_000, "round_period_us": 5_000_000,
        "enemies": [{"hp": enemy_hp, "willpower": 50, "z_mm": 1000}], **overrides}


def damage(range_type=1):
    return {"cost_sp": 10, "element": 4, "range_type": range_type, "effects": [
        {"type": 4,"subtype": 0, "base_low": 15, "base_high": 15, "plus_low": 1, "plus_high": 1,"per_level": 20}]}


def run(scenario=None, spells=None, policies=None, **kwargs):
    from dfo_optimizer import _encounter
    return _encounter.evaluate(scenario or scene(), spells or [damage()],
                               policies or [[{"spell":0}]], [42], **kwargs)


def test_payment_precedes_release_and_persistent_damage_stops_at_actual_hp():
    trial=run(scene(enemy_hp=1,tape=[0.,0.,.99]),trace=True)["rows"][0]["trials"][0]
    assert trial["cleared"] and trial["damage"]==1 and trial["spent_sp"]==10
    assert trial["end_us"]==200000
    assert [(event[0],event[1]) for event in trial["trace"]][:3]==[(0,"click"),(200000,"release"),(200000,"impact")]
    assert trial["trace"][0][6]==10


def test_full_hp_melee_guard_precedes_lethal_spell_and_acts_before_equal_time_cast():
    trial=run(scene(incoming=[{"time_us":200000,"source":0,"damage":99,"kind":"blow"},
                              {"time_us":200000,"source":0,"damage":1,"kind":"spell"}]),trace=True)["rows"][0]["trials"][0]
    assert trial["dead"] and trial["damage"]==0 and trial["end_hp"]==0
    assert trial["min_hp"]==0 and trial["spent_sp"]==10 and trial["end_us"]==200000


def test_no_cast_without_sp_and_observed_recovery_resumes_policy():
    p=run(scene(sp=0,recovery=[{"time_us":200000,"kind":"potion","duration_us":0,"hp":0,"sp":55}]))["rows"][0]["trials"][0]
    assert p["restored_sp"]==20 and p["consumables"]==1
    assert p["casts"]==2 and p["end_sp"]==0 and p["min_sp"]==0


def test_budgets_return_only_complete_common_trial_panels():
    from dfo_optimizer import _encounter
    p=run(max_events=1)
    assert p["termination"]=="event_limit" and p["rows"]==[] and p["events"]==1
    assert run(memory_bytes=1)["termination"]=="memory_limit"
    c=_encounter.CancelToken()
    c.cancel()
    assert run(cancel=c)["termination"]=="cancelled"


def test_ensemble_seed_is_repeatable_and_policies_share_trials():
    report=run(policies=[[{"spell":0}],[{"spell":0}]], trace=True)
    assert report["termination"]=="exhausted"
    assert report["rows"][0]["trials"]==report["rows"][1]["trials"]
    assert report["rows"][0]["trials"][0]["draws"]>0


def test_safe_rest_cannot_overlap_an_in_flight_cast():
    schedule=[{"kind":"rest","time_us":500000,"duration_us":400000,"hp":50,"sp":20}]
    p=run(scene(recovery=schedule,horizon=600000),trace=True)["rows"][0]["trials"][0]
    assert p["rest_us"]==400000
    assert [t[0] for t in p["trace"] if t[1]=="click"]==[500000]
    with pytest.raises(ValueError,match="rest"):
        run(scene(recovery=schedule,incoming=[{"time_us":200000,"source":0,"kind":"spell","damage":1}]))


def test_evidence_limited_piercing_and_area_schedules_have_distinct_victims():
    foes=[{"hp":20,"willpower":0,"x_mm":2000},{"hp":20,"willpower":0,"x_mm":5500}]
    area=run(scene(enemies=foes,horizon=400000,tape=[0,0,.99]*8),[damage(4)],trace=True)["rows"][0]["trials"][0]
    touched={row[2] for row in area["trace"] if row[1]=="impact"}
    assert touched=={-1,0,1} and area["end_hp"]==35 and area["damage"]==30
    centered=run(scene(enemies=foes,horizon=400000,tape=[0,0,.99]*8),[damage(3)])["rows"][0]["trials"][0]
    assert centered["damage"]==15 and centered["end_hp"]==50


def test_seer_dodge_and_full_health_guard_apply_to_foe_blows_only():
    hits=[{"source":0,"time_us":0,"kind":"blow","damage":99},
          {"source":0,"time_us":1,"kind":"blow","damage":99},
          {"source":0,"time_us":2,"kind":"spell","damage":1}]
    p=run(scene(path_id=10,tape=[0.,.99],incoming=hits),trace=True)["rows"][0]["trials"][0]
    assert p["dead"] and p["end_us"]==2 and p["mitigated"]==149
    assert p["draws"]==2 and p["min_hp"]==0


def test_caster_power_does_not_amplify_the_casters_own_blast():
    request=scene(horizon=400000,tape=[0.,0.,.99]*8)
    request["caster"]={**request["caster"],"power_pct":100,"climb":140,"pierce":20}
    trial=run(request,[damage(4)])["rows"][0]["trials"][0]
    assert trial["damage"]==42 and trial["end_hp"]==35


def test_wellspring_actual_gain_and_clipping():
    p=run(scene(enemy_hp=1,wellspring_pct=10,tape=[0,0,.99]))["rows"][0]["trials"][0]
    assert p["cleared"] and p["restored_sp"]==2 and p["end_sp"]==12


def test_hostile_bundle_tests_room_per_slot_before_one_half_refund():
    # 15 damage points cost 37 SP at receiver skill 60, even though this
    # policy's observed opportunity would pay a different amount to cast.
    bolt=damage()
    bolt["effects"]*=2
    request=scene(sp=0,horizon=0,wards={"career_absorbs":True},max_sp=37,
                  incoming=[{"time_us":0,"kind":"bundle","source":0,"spell":0}])
    trial=run(request,[bolt],trace=True)["rows"][0]["trials"][0]
    assert trial["end_hp"]==50 and trial["restored_sp"]==37
    assert [row[4] for row in trial["trace"] if row[1]=="absorbed"]==[37,37]


def test_reflection_omits_one_slot_then_delivers_all_slots_back_to_original_caster():
    bolt=damage()
    bolt["effects"]*=2
    enemy={"hp":500,"z_mm":1000,"willpower":50,"wards":{"reflect_chance":100}}
    s=scene(enemies=[enemy],horizon=300000,tape=[.99]*20)
    trial=run(s,[bolt],trace=True)["rows"][0]["trials"][0]
    assert trial["damage"]==15 and trial["end_hp"]==20
    assert [(r[1],r[2],r[4]) for r in trial["trace"] if r[1] in ("reflected","impact")]==[
        ("reflected",0,0),("impact",0,15),("impact",-1,30)]


def test_reflected_hostile_bundle_has_its_original_caster_and_cannot_bounce_twice():
    s=scene(sp=0,horizon=0,tape=[0,0,0,.99],wards={"reflect_chance":100},wellspring_pct=10,
            incoming=[{"time_us":0,"kind":"bundle","source":0,"spell":0}],
            enemies=[{"hp":2,"level":3,"willpower":50,"wards":{"reflect_chance":100}}])
    row=run(s,trace=True)["rows"][0]["trials"][0]
    assert row["cleared"] and row["end_hp"]==50 and row["damage"]==2 and row["draws"]==4
    assert row["restored_sp"]==2


def test_resistance_after_failed_absorption_reflection_rolls():
    ward={"absorb_chance":50,"reflect_chance":50,"resist_chance":100}
    s=scene(sp=0,max_sp=200,horizon=0,tape=[.99,.99,.99],wards=ward,
            incoming=[{"time_us":0,"kind":"bundle","source":0,"spell":0}])
    row=run(s,trace=True)["rows"][0]["trials"][0]
    assert (row["end_hp"],row["end_sp"],row["draws"])==(50,0,3)
    assert any(r[1]=="resisted" for r in row["trace"])


def test_aegis_bolt_raises_shield_from_actual_health_loss_and_soaks_next_blow():
    s=scene(path_id=1,horizon=400000,tape=[.99]*5,
            incoming=[{"time_us":300000,"source":0,"kind":"blow","damage":12}])
    trial=run(s,[{**damage(),"signature":True}],trace=True)["rows"][0]["trials"][0]
    assert trial["damage"]==15 and trial["mitigated"]==10
    assert trial["end_hp"]==48 and trial["draws"]==5


def test_silence_on_the_player_prevents_paid_clicks_until_actual_round_sweep():
    silence={"type":19,"subtype":255,"chance_base":100,"duration_base":1}
    s=scene(horizon=600000,first_round_us=250000,tape=[.99]*5,
            incoming=[{"time_us":0,"source":0,"kind":"bundle","spell":1}])
    trial=run(s,[damage(),{**damage(),"effects":[silence]}],trace=True)["rows"][0]["trials"][0]
    assert [r[0] for r in trial["trace"] if r[1]=="click"]==[250000]
    assert trial["damage"]==15 and trial["draws"]==5


def test_zero_duration_regenerate_spends_cast_but_does_not_roll_or_heal():
    regen={"type":18,"subtype":255,"base_low":40,"base_high":40,"duration_base":0}
    s=scene(hp=10,horizon=250000)
    out=run(s,[{**damage(0),"effects":[regen]}])["rows"][0]["trials"][0]
    assert (out["spent_sp"],out["draws"],out["end_hp"])==(10,0,10)


def test_incoming_spell_index_checked_against_the_actual_admitted_loadout():
    s=scene(incoming=[{"kind":"bundle","source":0,"spell":3,"time_us":1}])
    with pytest.raises(ValueError,match="Incoming spell index"):
        run(s)


def test_room_transition_starts_only_after_clear_then_applies_verified_rest_floors():
    foes=[{"hp":1,"willpower":50,"z_mm":1000},{"hp":1,"willpower":50,"z_mm":1000}]
    rooms=[{"enemies":[0],"delay_us":0},{"enemies":[1],"delay_us":900000,"rest_hp":45,"rest_sp":20}]
    hits=[{"kind":"spell","source":0,"time_us":300000,"damage":999},
          {"kind":"spell","source":1,"time_us":0,"damage":5}]
    req=scene(hp=30,sp=10,horizon=2000000,enemies=foes,rooms=rooms,incoming=hits,tape=[.99]*8)
    t=run(req,[damage(3)],trace=True)["rows"][0]["trials"][0]
    assert t["cleared"] and (t["end_us"],t["end_hp"],t["end_sp"])==(1300000,40,10)
    assert (t["restored_sp"],t["rest_us"],t["damage"])==(20,900000,2)
    assert [(r[0],r[1]) for r in t["trace"] if r[1] in ("room","incoming")]==[
        (1100000,"room"),(1100000,"incoming")]


def test_rooms_cannot_skip_cast_recovery_or_access_an_unopened_enemy():
    foes=[{"hp":1,"willpower":50,"z_mm":1000}]*2
    rooms=[{"enemies":[0],"delay_us":0},{"enemies":[1],"delay_us":0}]
    req=scene(enemies=foes,rooms=rooms,tape=[.99]*6)
    trial=run(req,[damage()],[[{"spell":0,"target":1},{"spell":0}]],trace=True)["rows"][0]["trials"][0]
    assert [(r[0],r[2]) for r in trial["trace"] if r[1]=="click"]==[(0,0),(700000,1)]
    assert trial["end_us"]==900000 and trial["rest_us"]==0


def test_vanguard_guard_fraction_is_carried_across_enemy_blows():
    hits=[{"time_us":t,"source":0,"kind":"blow","damage":5} for t in (0,1)]
    hits.append({"time_us":2,"source":0,"kind":"spell","damage":10})
    trial=run(scene(martial_id=3,incoming=hits,horizon=2))["rows"][0]["trials"][0]
    assert trial["end_hp"]==31 and trial["mitigated"]==1


def test_bladedancer_evasion_is_checked_only_for_a_foe_blow():
    hits=[{"time_us":0,"source":0,"kind":"blow","damage":9},
          {"time_us":1,"source":0,"kind":"spell","damage":8}]
    trial=run(scene(martial_id=5,incoming=hits,horizon=1,tape=[.01]))["rows"][0]["trials"][0]
    assert trial["end_hp"]==42 and trial["draws"]==1 and trial["mitigated"]==9


def test_reject_invalid_room_partition_and_unproven_overlapping_recovery():
    with pytest.raises(ValueError,match="partition"):
        run(scene(enemies=[{"hp":1},{"hp":1}],rooms=[{"enemies":[0]},{"enemies":[0]}]))
    with pytest.raises(ValueError,match="recovery"):
        run(scene(rooms=[{"enemies":[0]}],recovery=[{"time_us":1,"kind":"potion","sp":5}]))


def test_exhausted_rng_or_unsupported_effect_fails_explicitly():
    with pytest.raises(ValueError,match="tape"):
        run(scene(tape=[0.]))
    with pytest.raises(ValueError,match="unsupported"):
        run(spells=[{**damage(),"effects":[{"type":14,"subtype":0}]}])


def test_dominated_policy_and_equal_ties_removed_natively():
    p=run(scene(tape=[0.,0.,.99]*8), policies=[[{"spell":0}],[{"spell":0}]],frontier=True)
    assert p["policies_completed"]==2 and [r["policy_index"] for r in p["rows"]]==[0]


def test_packed_common_tape_and_policy_buffer_count_toward_native_memory_budget():
    result=run(scene(tape=[.5]*8192),memory_bytes=16384)
    assert result["termination"]=="memory_limit" and result["rows"]==[] and result["events"]==0


def test_all_native_objectives_match_exhaustive_independent_seeded_trial_frontiers():
    from dfo_optimizer import _encounter
    from dfo_optimizer.encounter_reference import simulate_trial
    req=scene(incoming=[],recovery=[],tape=[],enemy_hp=19,horizon=1_500_000)
    req["caster"].update(power_pct=0,pierce=0,cast_speed_pct=0)
    req["enemies"][0].update(x_mm=0,radius_mm=450,level=1)
    seeds=[1,29,256,12345,0]
    spells=[]
    for damage_value,cost in [(6,3),(12,7),(25,16),(4,0)]:
        spell=damage()
        spell["cost_sp"]=cost
        spell["effects"][0].update(base_low=damage_value,base_high=damage_value+2)
        spells.append(spell)
    policies=[[{"spell":i},{"spell":j}] for i in range(4) for j in range(4)]
    def ratio(n,d):
        return (bool(d),Fraction(n,d) if d else Fraction(0))
    scores=[]
    for policy in policies:
        trials=[simulate_trial(req,spells,policy,seed) for seed in seeds]
        def total(key):
            return sum(t[key] for t in trials)
        kills_rate=ratio(total("kills"),total("end_us"))
        censored=sum(t["end_us"] if t["cleared"] else req["horizon_us"] for t in trials)
        scores.append((total("cleared"),len(seeds)-total("dead"),kills_rate,total("damage"),
                       -total("spent_sp"),-censored,ratio(total("damage"),total("spent_sp"))))
    for objective,axes in (("pareto",range(6)),("clear_probability",[0]),("survival_probability",[1]),
                           ("kills_per_minute",[2]),("damage_per_sp",[6])):
        frontier=[]
        for i,current in enumerate(scores):
            if not any(i!=j and all(other[k]>=current[k] for k in axes) and
                       (any(other[k]>current[k] for k in axes) or j<i) for j,other in enumerate(scores)):
                frontier.append(i)
        report=_encounter.evaluate(req,spells,policies,seeds,frontier=True,objective=objective)
        assert report["termination"]=="exhausted"
        assert [row["policy_index"] for row in report["rows"]]==frontier


@pytest.mark.parametrize("overrides",[{"hp":-1},{"max_sp":0},{"enemies":[]},{"round_period_us":0}])
def test_invalid_packed_scenario(overrides):
    with pytest.raises(ValueError):
        run({**scene(),**overrides})
