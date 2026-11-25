"""Direct tests of the installed spell extension, including its complete frontier."""
from itertools import product
from fractions import Fraction
from concurrent.futures import ThreadPoolExecutor
from random import Random
from time import monotonic, sleep

import pytest

from dfo_optimizer import _spells


CAST = dict(level=10, live_skill=80, climb=100, speed=50, available_sp=1000,
            target_hp=100, willpower=50)
FIRE = (0, 1, 3, 3, 1, 1, 10)


def test_cast_matches_all_hundred_independent_rolls():
    out = _spells.evaluate(CAST, FIRE)
    amounts = [4 if roll > 55 else max(0, 4 * (100 - 5 * (55 - roll)) // 100)
               for roll in range(1, 101)]
    assert out['expected_damage'] == sum(amounts) / 100
    assert (out['gold'], out['effect_sp'], out['cost_sp']) == (60, 4, 5)
    assert out['recovery_seconds'] == 0.7
    assert out['release_seconds'] == 0.2


def test_immunity_before_pierce_and_gear_cut_after_floor():
    out = _spells.evaluate(dict(CAST, immune=8, pierce=100, focus_pct=50), FIRE)
    assert out['immune'] and out['expected_damage'] == 0
    assert out['cost_sp'] == 4


def test_distribution_accounts_for_hp_cap_and_absolute_resistance():
    recipe = (0, 2, 2, 4, 3, 5, 5)
    plain = _spells.evaluate(dict(CAST, target_hp=1), recipe)
    warded = _spells.evaluate(dict(CAST, target_hp=1, elemental_resists=[25, 0, 0, 0, 0]), recipe)
    assert warded['expected_damage'] == pytest.approx(plain['expected_damage'] * .75)
    assert 0 < warded['expected_health_loss'] == warded['kill_probability'] < 1
    assert warded['damage_per_sp'] == warded['expected_health_loss'] / warded['cost_sp']


def test_native_enumeration_keeps_every_nondominated_metric_tuple():
    domains = ((0, 4), (1, 2), (1, 2), (2, 4), (1, 3), (2, 3), (1, 2))
    scores = {}
    for recipe in product(*domains):
        if recipe[2] > recipe[3] or recipe[4] > recipe[5]:
            continue
        data = _spells.evaluate(CAST, recipe)
        damage = Fraction(data['health_loss_sum'], data['outcomes'])
        scores.setdefault((damage, damage / data['cost_sp']), []).append(recipe)
    front = {key: rows for key, rows in scores.items()
             if not any(other != key and other[0] >= key[0] and other[1] >= key[1] for other in scores)}
    got = _spells.search(CAST, domains)
    assert got['end'] == 'exhausted'
    assert dict(zip(got['rows'], got['multiplicities'])) == {min(rows): len(rows) for rows in front.values()}


def test_native_budget_cancellation_and_memory():
    dom = tuple((v,) for v in FIRE[:-1]) + ((1, 10),)
    assert _spells.search(CAST, dom, max_nodes=1)['end'] == 'node_limit'
    token = _spells.CancelToken()
    token.cancel()
    assert _spells.search(CAST, dom, token=token)['end'] == 'cancelled'
    assert _spells.search(CAST, dom, memory_bytes=1)['end'] == 'memory_limit'


def test_bounded_coverage_finds_affordable_alternative_to_immune_first_element():
    dom = ((0, 4), (1, 2), (1, 60, 100), (1, 60, 100),
           (1, 50, 100), (1, 50, 100), (1, 20))
    ctx = dict(CAST, immune=8)
    bounded = _spells.search(ctx, dom, max_nodes=32)
    assert bounded['end'] == 'node_limit' and bounded['nodes'] == 32
    assert all(row[0] == 4 for row in bounded['rows'])
    assert max(_spells.evaluate(ctx, r)['expected_health_loss'] for r in bounded['rows']) > 50
    assert bounded['rows'] == _spells.search(ctx, dom, max_nodes=32)['rows']


def test_exact_limit_and_ranked_top_k_have_stable_ties():
    dom = ((0, 4), (1,), (1, 2), (2,), (1,), (1,), (1,))
    exact = _spells.search(CAST, dom, max_nodes=4, objective='dps', top_k=2)
    rows = sorted(product(*dom), key=lambda r: (-_spells.evaluate(CAST, r)['dps'], r))
    assert exact['end'] == 'exhausted' and exact['rows'] == rows[:2]
    tied = _spells.search(dict(CAST, immune=127), dom)
    assert tied['rows'] == [min(product(*dom))] and tied['multiplicities'] == [4]


def test_batch_free_cast_and_unaffordable_rows():
    dom = tuple((v,) for v in FIRE)
    assert _spells.evaluate_batch(CAST, [FIRE]) == [_spells.evaluate(CAST, FIRE)]
    free = dict(CAST, free_cast=True, available_sp=0)
    assert _spells.evaluate(free, FIRE)['damage_per_sp'] is None
    assert not _spells.search(free, dom)['rows']
    assert _spells.search(free, dom, objective='dps')['rows'] == [FIRE]
    assert _spells.search(dict(CAST, available_sp=0), dom)['pruned'] == 1


@pytest.mark.parametrize('kwargs', [
    {'objective': 'typo'}, {'max_nodes': -1}, {'wall_seconds': float('nan')}, {'top_k': 0}
])
def test_invalid_native_limits(kwargs):
    with pytest.raises(ValueError):
        _spells.search(CAST, tuple((v,) for v in FIRE), **kwargs)


@pytest.mark.parametrize('bad', [(0, 0, 1, 1, 1, 1, 1), (0, 2, 10, 3, 1, 1, 1)])
def test_invalid_recipe(bad):
    with pytest.raises(ValueError):
        _spells.evaluate(CAST, bad)


def test_grid_and_wide_intervals_against_scalar_replay():
    from dfo_optimizer.spell_reference import evaluate_reference

    rng = Random(89272)
    ctx = dict(CAST, level=45, available_sp=100_000, live_skill=52, climb=140, power_pct=94,
               immune=0, resistant=8, low_tolerance=0, critical_weakness=0, price_factor=.87,
               resist_mods=[0, 15, 0, 0, 0], elemental_resists=[2, 0, 11, 0, 0],
               cast_speed_pct=14, focus_pct=29, pierce=7, target_hp=10_000)
    for _ in range(5):
        dom = ((0, 2), (1, 3), (1, 2), (rng.randint(70, 100),),
               (1, 2), (rng.randint(70, 100),), (1, rng.randint(3, 12)))
        scores = {}
        for row in product(*dom):
            expected = evaluate_reference(ctx, row)
            actual = _spells.evaluate(ctx, row)
            for key in ('damage_sum', 'health_loss_sum', 'kill_sum', 'outcomes', 'cost_sp'):
                assert actual[key] == expected[key]
            loss = Fraction(expected['health_loss_sum'], expected['outcomes'])
            scores[row] = loss / expected['cost_sp']
        sorted_rows = sorted(scores, key=lambda r: (-scores[r], r))
        result = _spells.search(ctx, dom, objective='damage_per_sp', top_k=6)
        assert result['rows'] == sorted_rows[:6]
        assert result['nodes'] == len(scores)


def test_running_cancellation_preserves_feasible_spells():
    token = _spells.CancelToken()
    axes = (range(5), range(1, 5), *(range(1, 101) for _ in range(4)), range(1, 21))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_spells.search, CAST, axes, token=token, wall_seconds=15)
        try:
            deadline = monotonic() + 15
            while not token.has_incumbent() and not future.done() and monotonic() < deadline:
                sleep(.002)
            assert token.has_incumbent()
        finally:
            token.cancel()
        out = future.result(timeout=15)
    assert out['end'] == 'cancelled' and out['rows'] and out['leaves'] > 0
    assert _spells.search(CAST, axes, wall_seconds=1e-15)['end'] == 'time_limit'
