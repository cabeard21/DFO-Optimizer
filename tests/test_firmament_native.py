from itertools import combinations

from dfo_optimizer import _firmament


def test_native_search_can_reach_damage_through_neutral_life_connector():
    context = dict(level=2, live_skill=20, climb=20, speed=50, available_sp=0,
                   target_hp=200, willpower=50)
    zero = (0,) * 13
    power = (10, *zero[1:])
    nodes = [(True, False, False, (1,), zero, zero),
             (False, True, False, (0, 2), zero, zero),
             (False, False, True, (1, 3), power, zero),
             (False, False, False, (2,), power, zero)]
    args = context, (0, 1, 20, 20, 1, 1, 2), nodes, -1, (), 1, 1, (50, 50, 20, 0, 12, 0, 0)
    result = _firmament.traverse(*args, max_nodes=100, wall_seconds=0, memory_bytes=65536)
    selected = result['candidates'][0]
    assert result['termination'] == 'exhausted'
    assert result['nodes'] == 4
    assert selected['keys'] == [1, 2]
    assert selected['additions'] == [0, 1, 2]
    assert selected['health_loss_sum'] > result['baseline']['health_loss_sum']


def test_native_duplicate_paths_match_independent_whole_tree_counts():
    context = dict(level=2, live_skill=20, climb=20, speed=50, available_sp=0,
                   target_hp=200, willpower=50)
    zero = (0,) * 13
    edges = ((1, 2), (0, 3), (0, 3), (1, 2))
    nodes = [(index == 0, index == 1, False, neighbors, zero, zero)
             for index, neighbors in enumerate(edges)]
    args = context, (0, 1, 20, 20, 1, 1, 2), nodes, 0, (), 1, 1, (50, 50, 20, 0, 12, 0, 0)

    def legal(selection):
        if len(set(selection) - {1}) > 1:
            return False
        seen = {0}
        for _ in range(len(selection)):
            seen |= {node for current in seen for node in edges[current] if node in selection}
        return set(selection) <= seen

    count = sum(legal(nodes) for size in range(4) for nodes in combinations((1, 2, 3), size))
    result = _firmament.traverse(*args, max_nodes=100, wall_seconds=0, memory_bytes=65536)
    assert result['termination'] == 'exhausted'
    assert result['nodes'] == count
    assert [row['keys'] for row in result['candidates']] == [[]]
    for _ in range(2):
        limited = _firmament.traverse(*args, max_nodes=2, wall_seconds=0, memory_bytes=65536)
        assert limited['termination'] == 'node_limit'
        assert limited['nodes'] == 2
    token = _firmament.CancelToken()
    token.cancel()
    cancelled = _firmament.traverse(*args, max_nodes=100, wall_seconds=0, memory_bytes=65536, cancel=token)
    assert cancelled['termination'] == 'cancelled'
    assert cancelled['candidates'] == []


def test_native_firmament_discount_stacks_after_gear_and_pays_signed_price():
    context = dict(level=2, live_skill=20, climb=20, speed=50, available_sp=0,
                   target_hp=200, willpower=50, focus_pct=11)
    zero = (0,) * 13
    gains = (0, 0, 0, 17, 10, 0, 0, 0, 0, 0, 0, 8, 10)
    prices = (0, 0, 0, -4, *zero[4:])
    nodes = [(True, False, False, (1,), zero, zero),
             (False, False, True, (0,), gains, prices)]
    result = _firmament.traverse(context, (0, 1, 20, 20, 1, 1, 2), nodes, 0, (), 1, 0,
                                 (50, 50, 20, 0, 12, 0, 2),
                                 max_nodes=100, wall_seconds=0, memory_bytes=65536)
    assert result['baseline']['cost_sp'] == 80
    assert result['baseline']['available_sp'] == 152
    assert result['candidates'][0]['cost_sp'] == 63
    assert result['candidates'][0]['available_sp'] == 175
