"""Independent exhaustive comparisons on small spell domains and physical equipment copies."""
from collections import defaultdict
from fractions import Fraction
from itertools import product
from random import Random

import pytest

from dfo_optimizer import _gear, _spells
from dfo_optimizer.spell_reference import evaluate_reference


def context():
    return dict(level=10, speed=56, live_skill=77, climb=77, available_sp=22, target_hp=33,
                willpower=42, pierce=0, power_pct=0, focus_pct=0, cast_speed_pct=0,
                resistant=8, immune=0, critical_weakness=0, low_tolerance=0,
                resist_mods=(0, 0, 0, 0, 0), elemental_resists=(0, 20, 0, 0, 0), price_factor=1)


def recipes(axes):
    return (r for r in product(*axes) if r[2] <= r[3] and r[4] <= r[5])


def metrics(ctx, recipe):
    score = evaluate_reference(ctx, recipe)
    damage = Fraction(score["health_loss_sum"], score["outcomes"])
    rate = Fraction(min(400, max(100, 150 + ctx["speed"] + 2 * ctx["cast_speed_pct"])), 200)
    return None if not score["affordable"] else (damage * rate, damage / score["cost_sp"])


def frontier(groups):
    return {a: rows for a, rows in groups.items()
            if not any(b != a and b[0] >= a[0] and b[1] >= a[1] for b in groups)}


@pytest.mark.parametrize("seed", [9, 31, 806, 1093])
def test_spell_native_matches_scalar_finite_oracle_with_ties(seed):
    rng = Random(seed)
    ctx = context()
    ctx.update(level=rng.randint(1, 45), live_skill=rng.choice([65, 99, 100, 101, 149]),
               climb=rng.randint(98, 140), target_hp=rng.randint(1, 42), focus_pct=rng.randrange(35))
    axes = [(0, 1), (1, 2)] + [tuple(sorted(rng.sample(range(1, 15), 3))) for _ in range(4)] + [(1, 10, 20)]
    groups = defaultdict(list)
    for r in recipes(axes):
        if (pair := metrics(ctx, r)) is not None:
            groups[pair].append(r)
    exact = _spells.search(ctx, axes)
    assert exact["end"] == "exhausted"
    assert dict(zip(exact["rows"], exact["multiplicities"], strict=True)) == {
        min(rows): len(rows) for rows in frontier(groups).values()}


@pytest.mark.parametrize("credit", [0, 2])
def test_gear_joint_native_matches_every_legal_copy_and_recipe(credit):
    ctx = context()
    axes = ((0, 1), (1, 2), (1, 2), (2, 3), (1, 2), (2,), (1, 3))
    # Two alternative ordinary copies, a two-slot item, and a duplicate legendary
    # with different lines. Numerical fixture uses the same physical ID in two
    # slot domains, one observed current item and two acquisition currencies.
    options = [((0, 0, 4, 0, 0, 0, 0, 0), (0, 0), -1, 1, True),
               ((2, 4, 0, 7, 0, 0, 0, 0), (1, 0), 0, -1, False),
               ((3, 7, 0, 0, 0, 12, 0, 0), (0, 2), -1, -1, False),
               ((0, 8, 0, 5, 0, 0, 2, 0), (0, 0), 0, -1, True)]
    places = [[(0, 2), (1, 2), (2, 6), (3, 2)], [(1, 4), (3, 4)]]
    slots = [(-2, -1, -1, []) for _ in range(27)]
    slots[1], slots[2] = (-2, 0, -1, places[0]), (-2, -1, -1, places[1])
    rows = defaultdict(list)
    for left, right in product((-1, 0, 1, 2, 3), (-1, 1, 3)):
        chosen = [i for i in (left, right) if i >= 0]
        if (left == 2 and right != -1) or len(set(chosen)) != len(chosen):
            continue
        if sum(options[i][1][1] for i in chosen) > credit:
            continue
        c = dict(ctx)
        seen = set()
        for i in chosen:
            (speed, skill, cast, power, _, focus, enhance, _), _, group, _, _ = options[i]
            c["live_skill"] += enhance
            if group >= 0 and group in seen:
                continue
            seen.add(group)
            c["speed"] += speed
            c["live_skill"] += skill
            c["cast_speed_pct"] += cast
            c["power_pct"] += power
            c["focus_pct"] += focus
        tie = ((left != 0) + (right != -1), len(chosen), (left < 0, left), (right < 0, right))
        for r in recipes(axes):
            if (pair := metrics(c, r)) is not None:
                rows[pair].append((tie, r, left, right))
    expected = {(left, right, r) for group in frontier(rows).values()
                for _, r, left, right in [min(group)]}
    actual = _gear.traverse(ctx, axes, options, slots, (1, credit), max_nodes=0,
                            memory_bytes=4 << 20, wall_seconds=0, per_state=0)
    assert actual["termination"] == "exhausted"
    assert {(r["slots"][1], r["slots"][2], r["recipe"]) for r in actual["results"]} == expected
