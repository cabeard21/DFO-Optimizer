"""Compare the compiled loadout/spell frontier with an independent Cartesian oracle."""
from fractions import Fraction
from itertools import product
import random

import pytest

from dfo_optimizer import _gear
from dfo_optimizer.spell_reference import evaluate_reference

CTX = {"level": 8, "speed": 78, "live_skill": 90, "climb": 88, "available_sp": 35,
       "target_hp": 80, "willpower": 50, "power_pct": 0, "focus_pct": 0,
       "pierce": 0, "cast_speed_pct": 0, "price_factor": 1, "immune": 0, "resistant": 0,
       "low_tolerance": 0, "critical_weakness": 0, "resist_mods": [0]*5, "elemental_resists": [0]*5}
AXES = ((0,), (1,), (1, 4), (2, 5), (1,), (2, 6), (1, 3))


def query(items, placements, axes=AXES, ctx=CTX, locks=None, preferred=None,
          budget=(8, 3), **overrides):
    current = {item[3]: n for n, item in enumerate(items) if item[3] >= 0}
    slots = [((locks or {}).get(i, -2), current.get(i,-1), (preferred or {}).get(i,-1),
              placements.get(i, [])) for i in range(27)]
    options = {"memory_bytes": 64 << 20, "wall_seconds": 0, "max_nodes": 0, "per_state": 0}
    return _gear.traverse(dict(ctx), axes, items, slots, budget, **{**options, **overrides})


def option(mods=(0,)*8, cost=(0,0), legendary=-1, worn=-1, owned=True):
    return (tuple(mods), tuple(cost), legendary, worn, owned)


def axes_metrics(loss, n, rate, cost):
    return Fraction(loss*rate, n), Fraction(loss, n*cost)


def test_firmament_gear_hook_prices_and_clips_capacity_on_swap():
    axes = ((0,), (1,), (30,), (30,), (1,), (1,), (1,))
    caster = {**CTX, "live_skill": 50, "available_sp": 130}
    items = [option([0]*7+[30], worn=0), option([0]*7+[25])]
    placements = {0: [(0, 1), (1, 1)]}
    projection = (78, 40, 50, 30, 6, 0, 0)
    gains = (10, 0, 0, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    prices = (0,) * 13
    off = query(items, placements, axes, caster, locks={0: 0})
    on = query(items, placements, axes, caster, locks={0: 0}, firmament=(projection, gains, prices))
    assert on["results"][0]["cost_sp"] < off["results"][0]["cost_sp"]
    assert on["results"][0]["health_loss_sum"] > off["results"][0]["health_loss_sum"]
    # Removing the worn item drops the pool before replacement Intelligence is applied.
    swapped = query(items, placements, axes, caster, locks={0: 1}, firmament=(projection, gains, prices))
    assert swapped["results"] == [] and swapped["uncertain_sp_recipes"] == 1


@pytest.mark.parametrize("seed", range(6))
def test_random_reduced_exact_joint_frontier(seed):
    rng = random.Random(seed)
    items = [option([rng.randrange(0, 15) for _ in range(8)], (rng.randrange(5), rng.randrange(3)))
             for _ in range(4)]
    placements = {0:[(i,1) for i in (0,1,2)], 1:[(i,2) for i in (0,1,3)]}
    out = query(items, placements)
    all_points = set()
    for first, second in product((-1,0,1,2), (-1,0,1,3)):
        picks = [items[i] for i in (first,second) if i>=0]
        if first==second and first>=0 or any(sum(i[1][j] for i in picks)>v for j,v in enumerate((8,3))):
            continue
        mods = [sum(i[0][j] for i in picks) for j in range(8)]
        ctx = {**CTX, "speed":min(100,CTX["speed"]+mods[0]),
               "live_skill":CTX["live_skill"]+mods[1]+mods[6], "cast_speed_pct":min(30,mods[2]),
               "power_pct":min(30,mods[3]), "pierce":mods[4], "focus_pct":min(30,mods[5])}
        for recipe in product(*AXES):
            if recipe[2]>recipe[3] or recipe[4]>recipe[5]:
                continue
            s = evaluate_reference(ctx,recipe)
            if s["affordable"]:
                all_points.add(axes_metrics(s["health_loss_sum"], s["outcomes"],
                                            round(s["cast_rate"]*200), s["cost_sp"]))
    frontier = {p for p in all_points if not any(q != p and q[0]>=p[0] and q[1]>=p[1] for q in all_points)}
    got = {axes_metrics(r["health_loss_sum"],r["outcomes"],r["rate_200"],r["cost_sp"]) for r in out["results"]}
    assert out["termination"]=="exhausted" and got==frontier
    assert out["cache_hits"]>0


def test_source_slot_blockers_donors_and_conditional_legendaries():
    items = [option(), option()]
    assert not query(items,{19:[(0,(1<<19)|(1<<21))],21:[(1,1<<21)]},
                     locks={19:0,21:1})["results"]
    assert not query(items[:1],{4:[(0,1<<4)],5:[(0,1<<5)]},
                     locks={4:-1,5:0},preferred={5:4})["results"]
    out = query(items,{4:[(0,1<<4),(1,1<<4)],5:[(0,1<<5)]},
                locks={4:-1,5:0},preferred={5:4})
    assert out["results"]
    base = [option((5,12,4,6,0,3,15,0),legendary=1),option((15,3,8,10,0,5,15,0),legendary=1)]
    out = query(base,{4:[(0,1<<4)],5:[(1,1<<5)]},locks={4:0,5:1})
    for r in out["results"]:
        expected = evaluate_reference({**CTX, "speed":83, "live_skill":132,"cast_speed_pct":4,
                          "power_pct":6,"focus_pct":3},r["recipe"])
        assert r["health_loss_sum"]==expected["health_loss_sum"]
        assert r["rate_200"]==round(expected["cast_rate"]*200) and r["cost_sp"]==expected["cost_sp"]


def test_limits_and_wide_domain_grid():
    token = _gear.CancelToken()
    token.cancel()
    assert query([],{},cancel=token)["termination"]=="cancelled"
    assert query([],{},memory_bytes=20)["termination"]=="memory_limit"
    assert query([],{},max_nodes=2)["termination"]=="node_limit"
    assert query([],{},wall_seconds=1e-12)["termination"]=="time_limit"
    sampled = query([],{},per_state=3)
    assert sampled["sampled_spells"] and sampled["evaluations"]<=3
    grid = ((0,1),(1,2),tuple(range(1,6)),tuple(range(3,9)),(1,2,3),(2,3,4),(1,2))
    wide = query([],{},axes=grid)
    for r in wide["results"]:
        assert evaluate_reference(CTX,r["recipe"])["health_loss_sum"]==r["health_loss_sum"]
    assert query([],{},axes=[(),*AXES[1:]])["results"]==[]


def test_packed_input_validation():
    with pytest.raises(ValueError,match="occupancy"):
        query([option()],{0:[(0,0)]})
    with pytest.raises(ValueError,match="own slot"):
        query([option()],{0:[(0,2)]})
    with pytest.raises(ValueError,match="option"):
        query([option(mods=(1,))],{})
    with pytest.raises(ValueError,match="setting"):
        query([],{},axes=[(100,),*AXES[1:]])
    with pytest.raises(ValueError,match="wall_seconds"):
        query([],{},wall_seconds=float("nan"))
