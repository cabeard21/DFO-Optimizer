"""Progression, native loadout search and the user-facing game projections share a spell."""
import json
from math import isclose
from pathlib import Path

import pytest

from dfo_optimizer import spellbook

CTX = dict(level=10, live_skill=110, climb=100, speed=50, available_sp=120,
           target_hp=30, willpower=50, price_factor=1)
H = dict(effect_id="4,0", base_low=3, base_high=6, plus_low=1, plus_high=2, per_level=8)
D = dict(effect_id="5,255", chance_base=12, chance_increment=1, chance_per_level=5)


def recipe(*effects):
    return dict(element=4, range_type=2, effects=list(effects))


def test_source_oracle_conditions():
    scope = Path(__file__).resolve().parent / "fixtures" / "spellbook-oracle.json"
    rows = json.loads(scope.read_text())["examples"]
    assert len(rows) >= 6
    for row in rows:
        result = spellbook.evaluate_loadout(row["context"], [row["spell"]])[0]
        for key in ["expected_health_loss", "kill_probability", "expected_damage",
                    "cost_sp", "purchase_gold", "dps"]:
            assert result[key] == pytest.approx(row["estimate"][key], abs=1e-9), (row["id"], key)
        assert row["specific"]["available"] and row["specific"]["after"] == 0
        assert row["specific"]["trajectory_count"] >= 2


@pytest.mark.parametrize("order", [(H,), (D,), (H, H), (H, D), (D, H), (H, D, H), (D, D, D)])
def test_absolute_frontier_matches_immutable_memory(order):
    body = recipe(*order)
    output = spellbook.evaluate_loadout(dict(CTX, pierce=12, elemental_resists=[0,0,0,0,44]), [body])[0]
    ref = spellbook.replay_spell(dict(CTX, pierce=12, elemental_resists=[0,0,0,0,44]), body)
    for k in ("cost_sp", "purchase_gold", "expected_damage", "expected_health_loss", "kill_probability"):
        assert output[k] == pytest.approx(ref[k], abs=1e-10)


def test_mixed_exact_routes_own_topological_order():
    a, b = spellbook.evaluate_loadout(CTX, [recipe(H, D), recipe(D, H)])
    assert isclose(a["expected_health_loss"], b["expected_health_loss"], abs_tol=1e-12)
    assert a["expected_damage"] < b["expected_damage"]
    assert a["cost_sp"] == b["cost_sp"]
    no_pi, pi = [spellbook.evaluate_loadout(dict(CTX, pierce=absent), [recipe(D)])[0]
                 for absent in (0,80)]
    assert no_pi["kill_probability"] == pi["kill_probability"]


@pytest.mark.parametrize("mut", [
    dict(effects=[]), dict(effects=[H]*4), dict(range_type=0), dict(element=5),
    dict(effects=[dict(D, chance_base=0)]), dict(effects=[dict(D, chance_per_level=21)]),
    dict(effects=[dict(H, plus_low=3)]), dict(effects=[dict(H, effect_id="22,0")]),
])
def test_illegal_spell_excludes_nonterminal_fictions(mut):
    with pytest.raises((ValueError, TypeError)):
        spellbook.evaluate_loadout(CTX, [dict(recipe(H), **mut)])


@pytest.mark.parametrize("next_hp", [1, 6, 12, 23, 1000])
def test_exact_incumbents_replay_all_cross_price_interactions(next_hp):
    choices = [H, {**H, "plus_high":3}, {**H, "base_low":5}]
    c = {**CTX, "target_hp":next_hp, "live_skill":170, "climb":133,
         "pierce":4, "focus_pct":6, "willpower":75}
    s = recipe(*choices)
    own = spellbook.evaluate_loadout(c, [s])[0]
    actual = spellbook.replay_spell(c, s)
    for k in ("expected_damage", "expected_health_loss", "kill_probability", "dps"):
        assert own[k] == pytest.approx(actual[k], abs=1e-10)


def test_dynamic_growth_audit_cannot_grow_beyond_affordability():
    from dfo_optimizer import _spellbook
    counts = [(spellbook.pack_spell(recipe(H, H, H)), 1)]
    events = dict(casts=3, gold=2000, max_nodes=99)
    wall = _spellbook.search_book(CTX, counts, [], **events, wall_seconds=1e-12, memory_bytes=5000)
    assert wall["termination"] == "time_limit" and wall["nodes"] == 0
    low = _spellbook.search_book(CTX, counts, [], **events, wall_seconds=0, memory_bytes=10)
    assert low["termination"] == "memory_limit" and low["nodes"] == 0


def test_wide_reference_damage_distribution_matches_scalar_product():
    from collections import Counter
    from dfo_optimizer.spellbook_reference import _apply_damage
    remaining = {0: .125, **{h+100: .875/400 for h in range(400)}}
    losses = [(n, 1/500) for n in range(500)]
    direct = Counter()
    for hp, a in remaining.items():
        for loss, b in losses:
            direct[max(0, hp-loss)] += a*b
    assert _apply_damage(remaining, losses) == pytest.approx(direct, abs=1e-11)


def test_reference_discards_zero_weight_survivors_after_a_lethal_effect():
    from dfo_optimizer.spellbook_reference import _apply_damage
    remaining = {**dict.fromkeys(range(1, 401), 0.), 0: 1.}
    losses = [(n, 1/256) for n in range(256)]
    assert _apply_damage(remaining, losses) == {0: 1.}


def test_sparse_reference_uses_only_the_reachable_health_values():
    from dfo_optimizer.spellbook_reference import _apply_damage
    # A target HP observation can be large while the supported outcomes are sparse.
    remaining = {500_000_000 + i * 1_000_000: 1/256 for i in range(256)}
    losses = [(n, 1/257) for n in range(257)]
    actual = _apply_damage(remaining, losses)
    assert sum(actual.values()) == pytest.approx(1)
    assert actual[500_000_000 - 256] == pytest.approx(1 / (256 * 257))
