"""Game-owned outcomes from the authenticated JavaScript snapshot."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dfo_optimizer import encounter_advanced_reference as powers


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=["native","scalar"])
def run_trial(request):
    def run(scene, spell):
        policy = [{"spell":0}]
        if request.param == "native":
            from dfo_optimizer import _encounter
            return _encounter.evaluate(scene,[spell],[policy],[1],trace=True)["rows"][0]["trials"][0]
        from dfo_optimizer.encounter_reference import simulate_trial
        scene = {"incoming":[], "first_round_us":5_000_000,"round_period_us":5_000_000, **scene,
                 "caster":{"cast_speed_pct":0,"power_pct":0,"pierce":0, **scene["caster"]},
                 "enemies":[{"x_mm":0,"z_mm":0,"radius_mm":450,"willpower":50,**e} for e in scene["enemies"]]}
        return simulate_trial(scene,[spell],policy,1,trace=True)
    return run


def test_spell_effects_and_arcane_paths_have_game_witnesses():
    data = json.loads((ROOT / "tests/fixtures/encounter-oracle.json").read_text())
    assert {r["effect_id"] for r in data["effects"]} == {"4,0", "5,255", "10,8", "35,255", "18,255"}
    assert len(data["paths"]) == 15
    assert sum(row["id"] == "elementalist" for row in data["paths"]) == 1
    assert data["listeners"]["conflux"] == [0, 3, 3, 6, 0]
    assert data["listeners"]["kill"] == [55, 10]
    assert data["shield"]["after_recast"] == data["shield"]["starting"]
    assert len(data["area"]["hits"]) == 2
    assert data["area"]["self_at_rim"] is True
    assert data["listeners"]["wellspring"] == [5, 5, 11]


def test_all_passive_reads_and_signature_callbacks_match_game_snapshot():
    data = json.loads((ROOT / "tests/fixtures/encounter-oracle.json").read_text())
    for row in data["paths"]:
        id = powers.PATH_IDS[row["id"]]
        state = powers.PathState(id)
        assert row["awake"] == row["id"]
        assert powers.path_damage(state, 0, 20, 100, 1, False, False) == row["low_hp_shielded_power"]
        assert powers.path_pierce(id) == row["pierce"]
        assert powers.path_speed(id) == row["cast_speed"]
        assert powers.path_cost(id, True, 100) == row["shield_cost"]
    for row in data["listeners"]["signature"]:
        state = powers.PathState(powers.PATH_IDS[row["id"]])
        hp, sp = 50, 0
        for _ in range(2):
            hp, sp = powers.path_signature(state, 5, 11, hp, 100, sp, 200)
        assert (hp, sp) == (row["hp"], row["sp"])


def test_fractional_carry_does_not_revive_and_kill_gates_are_applied():
    state = powers.PathState(13)
    assert powers.path_kill(state, False, False, 20, 55, 4, 55) == (20, 4)
    hp, sp = powers.path_kill(state, True, False, 0, 55, 4, 55)
    assert (hp, sp) == (0, 6)
    assert powers.gear_kill(state, 11, True, sp, 55) == 12
    assert powers.gear_kill(state, 11, False, sp, 55) == sp
    assert powers.path_round(powers.PathState(4), 10, 94, 100) == 95
    assert powers.path_kill(powers.PathState(14), True, True, 4, 10, 2, 100) == (4, 22)
    assert powers.path_signature(state, 0, 19, 4, 99, 6, 11) == (4, 6)


def test_path_timers_and_conditional_draw_order():
    state = powers.PathState(9)
    for action in (1, 1, 2):
        powers.path_landed(state, 1000, action, 2)
    assert powers.path_damage(state, 10_999, 1, 100, 0, False, False) == 6
    assert powers.path_damage(state, 11_000, 1, 100, 0, False, False) == 0
    state = powers.PathState(15)
    assert powers.path_hurt(state, 0, 30, 29, 100) == 54
    assert powers.path_hurt(state, 179_999, 30, 29, 100) == 29
    assert powers.path_hurt(state, 180_000, 30, 29, 100) == 54
    tape = SimpleNamespace(next=iter([.125, .124]).__next__)
    assert not powers.path_evades(9, tape)
    assert not powers.path_evades(10, tape)
    assert powers.path_evades(10, tape)


@pytest.mark.parametrize("id", ["4,0", "5,255", "10,8", "35,255", "18,255"])
def test_first_landing_and_random_draw_count_match_real_game(id, run_trial):
    data = json.loads((ROOT / "tests/fixtures/encounter-oracle.json").read_text())
    game = next(e for e in data["effects"] if e["effect_id"] == id)
    kind, subtype = map(int,id.split(","))
    self_cast = kind in (10, 35, 18)
    e = dict(type=kind,subtype=subtype,base_low=3,base_high=9,plus_low=1,plus_high=3,per_level=5,
             duration_base=2,duration_increment=1,duration_per_level=12,
             chance_base=20,chance_increment=1,chance_per_level=5)
    spell=dict(range_type=0 if self_cast else 2,element=4,cost_sp=game["cast_sp"],effects=[e])
    scenario = dict(caster=dict(level=10,live_skill=60,climb=60,speed=50,available_sp=2000,
                                willpower=50,target_hp=30), hp=50,max_hp=100,max_sp=2000,
                    horizon_us=500_000,enemies=[{"hp":30,"distance_mm":1000}],tape=game["tape"])
    trace = run_trial(scenario,spell)
    assert trace["draws"] == game["draws"]
    observed = trace["end_hp"] if self_cast else 30-trace["damage"]
    assert observed == game["after"]
    assert trace["spent_sp"] == game["cast_sp"]


def test_effect_room_cap_and_signature_shield_consume_correct_draws():
    defense = powers.Defenses(absorb_chance=100,reflect_chance=100,career_absorbs=True)
    effect = dict(type=4,subtype=0,base_low=5,base_high=5,plus_low=1,plus_high=1,per_level=20)
    rolls = SimpleNamespace(next=iter([.75, .4, .4]).__next__)
    assert powers.try_absorb(defense,effect,2,50,1,0,rolls)==0
    assert powers.try_absorb(defense,effect,2,50,6,6,rolls)==6
    assert powers.absorb_refund(12,7)==3
    assert powers.aegis_bolt(30,100,rolls)==20


def test_martial_carry_healing_and_guard_match_the_game():
    data = json.loads((ROOT/"tests/fixtures/encounter-oracle.json").read_text())["martial"]
    assert len(data["paths"]) == 15
    s = powers.PathState(martial_id=powers.MARTIAL_IDS["vanguard"])
    assert [powers.martial_guard(s,7) for _ in range(4)] == data["guard"]
    s = powers.PathState(martial_id=powers.MARTIAL_IDS["juggernaut"])
    assert powers.path_hurt(s,0,60,29,100) == data["juggernaut"]
    s = powers.PathState(martial_id=powers.MARTIAL_IDS["bloodletter"])
    assert powers.path_kill(s,True,False,50,100,0,200)[0] == data["kill_hp"]
    s = powers.PathState(martial_id=powers.MARTIAL_IDS["brawler"])
    assert powers.path_round(s,0,50,100) == data["round_hp"]
    assert powers.martial_speed(powers.MARTIAL_IDS["windrunner"]) == data["windborne"]
    assert data["evasion"] == {"order": ["arcane", "martial"], "lost": 0}
    state = powers.PathState(martial_id=powers.MARTIAL_IDS["bladedancer"])
    draws = SimpleNamespace(next=iter([.1, .099]).__next__)
    assert not powers.martial_evades(state, draws)
    assert powers.martial_evades(state, draws)


@pytest.mark.parametrize("id", ["battlemage","spellbreaker","necromancer"])
def test_two_signature_landings_against_actual_host(id,run_trial):

    data = json.loads((ROOT/"tests/fixtures/encounter-oracle.json").read_text())
    path = next(x for x in data["paths"] if x["id"]==id)
    results = next(x["results"] for x in data["signature_casts"] if x["id"]==id)
    names = {"magnitudeBaseLow":"base_low","magnitudeBaseHigh":"base_high",
             "magnitudeLevelBase":"plus_low","magnitudeLevelHigh":"plus_high","magnitudePerLevel":"per_level",
             "durationBase":"duration_base","durationMod":"duration_increment","durationPerLevel":"duration_per_level",
             "chanceBase":"chance_base","chanceMod":"chance_increment","chancePerLevel":"chance_per_level"}
    slots = [dict(type=e["type"],subtype=e["subType"],climb=60,
                  **{names[k]:v for k,v in e["settings"].items()}) for e in path["slots"]]
    paid = results[0]["paid"]
    spell = dict(range_type=2,element=path["element"],effects=slots,climb=60,cost_sp=paid,signature=True)
    scenario = dict(caster=dict(level=10,live_skill=60,climb=60,speed=50,available_sp=1000,
                                willpower=50,target_hp=100),hp=50,max_hp=100,max_sp=1000,
                    enemies=[dict(hp=100,distance_mm=1000,critical_weakness=34)],tape=[.05]*32,
                    path_id=powers.PATH_IDS[id],horizon_us=1_000_000)
    witness = run_trial(scenario,spell)
    assert witness["damage"] == 100-results[-1]["foe_hp"]
    assert witness["draws"] == results[-1]["draws"]
    assert witness["end_hp"] == results[-1]["hp"]
    assert witness["restored_sp"] == results[-1]["sp"]
    assert witness["trace"][-1][7] == results[-1]["shield"]


@pytest.mark.parametrize("flavor", ["reflect","resist","absorb","room"])
def test_ordered_multislot_defenses_against_actual_host(flavor,run_trial):

    data = json.loads((ROOT/"tests/fixtures/encounter-oracle.json").read_text())
    game = next(x for x in data["defenses"] if x["flavor"]==flavor)
    wards = {"reflect":{"reflect_chance":100},"resist":{"resist_chance":100},
             "absorb":{"career_absorbs":True},"room":{"career_absorbs":True}}[flavor]
    foe = dict(hp=60,max_sp=200,sp=199 if flavor=="room" else 0,absorb_skill=60,
               wards=wards,distance_mm=1000)
    scene = dict(caster=dict(level=10,live_skill=60,climb=60,speed=50,available_sp=14,
                             willpower=50,target_hp=60),hp=50,max_hp=100,max_sp=200,tape=[.99]*40,
                 enemies=[foe],horizon_us=500_000)
    slot = dict(type=4,subtype=0,base_low=3,base_high=9,plus_low=1,plus_high=3,per_level=5)
    spell = dict(range_type=2,element=4,cost_sp=7,effects=[slot,slot])
    v = run_trial(scene,spell)
    assert v["end_hp"] == game["hp"]
    assert v["end_sp"] == game["sp"]
    assert v["damage"] == 60-game["foe_hp"]
    assert v["draws"] == game["draws"]
