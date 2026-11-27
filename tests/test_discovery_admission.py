import json
from pathlib import Path

import pytest

from dfo_optimizer.lifecycle import optimize_build, replay_build


EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


def reduced(strategy='exhaustive'):
    build = json.loads((EXAMPLES / 'build-lifecycle.json').read_bytes())
    query = json.loads((EXAMPLES / 'max-intelligence.json').read_bytes())
    query.update(top_k=64, race_ids=[1], attribute_domains={}, exact=True)
    return {**build, 'families': [], 'roll_seeds': [42, 97], 'class_search': query,
            'class_admission_strategy': strategy, 'search': {'max_nodes': 100000, 'wall_seconds': 0}}


def test_exhaustive_panel_shares_budget_and_archives_first_replay():
    req = reduced()
    first = []
    result = optimize_build(req, on_incumbent=first.append)
    stats = result['class_admission']
    assert stats['enumeration_complete'] and stats['admission_complete'] and stats['downstream_complete']
    assert stats['generated_legal'] == stats['admitted'] == stats['evaluated'] > 0
    assert stats['class_nodes'] + stats['lifecycle_nodes'] == result['counters']['nodes'] <= 100000
    assert result['exact'] and replay_build(result)['validated']
    assert len(first) == 1 and not first[0]['exact'] and replay_build(first[0])['validated']


def test_generation_consumes_the_final_node_without_unlimited_downstream_search():
    req = reduced('examples')
    req['search']['max_nodes'] = 1
    result = optimize_build(req)
    assert result['counters']['nodes'] == result['class_admission']['class_nodes'] == 1
    assert not result['exact'] and not result['candidates']


def test_baselines_and_unvisited_rolls_remain_visible_to_comparison():
    req = reduced('examples')
    req['families'] = [{'id': 'Breton', 'baseline_id': 'm1-breton-caster'}]
    req['search']['max_nodes'] = 1
    result = optimize_build(req)
    rows = result['family_comparisons']
    assert len(rows) == 1 and rows[0]['baseline_id'] == 'm1-breton-caster'
    assert rows[0]['complete_roll_set'] is False
    assert len(rows[0]['rolls']) == 2
    assert all(r['status'] == 'unvisited' and r['witness_index'] is None for r in rows[0]['rolls'])


def test_replay_validates_every_comparison_witness_and_proof_layer():
    from dfo_optimizer.lifecycle import _id
    req = reduced('examples')
    req['families'] = [{'id': 'Breton', 'baseline_id': 'm1-breton-caster'}]
    result = optimize_build(req)
    assert all(r['complete_roll_set'] for r in result['family_comparisons'])
    assert replay_build(result)['routes_checked'] == len(result['candidates']) + len(result['comparison_witnesses'])
    result['class_admission']['admission_complete'] = True
    result['result_hash'] = _id(result)
    with pytest.raises(ValueError, match='admission'):
        replay_build(result)


def test_heuristic_scope_never_inherits_exact_downstream_status():
    result = optimize_build(reduced('examples'))
    stats = result['class_admission']
    assert stats['downstream_complete'] and not stats['admission_complete']
    assert result['status'] == 'best_found_bounded' and not result['exact']


def test_explicit_strategy_requires_class_search():
    req = reduced('unknown')
    with pytest.raises(ValueError, match='admission strategy'):
        optimize_build(req)
    del req['class_search']
    with pytest.raises(ValueError, match='class_search'):
        optimize_build(req)


def test_adaptive_neighborhood_respects_locks_budget_and_paired_comparison():
    from dfo_optimizer.class_document import ATTRIBUTES
    from dfo_optimizer.search_request import EXAMPLE_SKILLS
    req = reduced('adaptive')
    req.update(objective='endgame_damage')
    req['class_search'].update(profile='spellcaster_discovery_v1', objective='diverse', top_k=1,
                               required_masteries=[], skill_domains=[[i] for i in EXAMPLE_SKILLS],
                               coarse_attribute_domains={'intelligence': [40,50,60]},
                               attribute_domains={a: [50] for a in ATTRIBUTES if a not in ('strength', 'intelligence')})
    plan = optimize_build(req)
    evidence = plan['frozen_request']['class_admission']
    assert any(p['center'] in evidence['screening_features'] for p in evidence['passes'][1:])
    assert len(plan['comparison_witnesses']) + len(plan['candidates']) > 0
    assert any(f['rank'] for f in plan['family_comparisons'])
    assert all(f['complete_roll_set'] == (f['mean_score'] is not None) for f in plan['family_comparisons'])
    assert plan['counters']['nodes'] <= req['search']['max_nodes']
    assert replay_build(plan)['validated']
    assert plan['result_hash'] == optimize_build(req)['result_hash']


def test_cancel_after_incumbent_keeps_replay_and_incomplete_comparisons():
    from dfo_optimizer import _lifecycle
    token = _lifecycle.CancelToken()
    plan = optimize_build(reduced(), cancel=token, on_incumbent=lambda _: token.cancel())
    assert plan['status'] == 'cancelled' and plan['candidates'] and replay_build(plan)['validated']
    assert not plan['class_admission']['downstream_complete']


def test_cap_itinerary_budgets_one_long_probe_before_uniform_paired_probes():
    from dfo_optimizer.lifecycle_refinement import first_probe
    raw = {'progression': {'goal': {'level': 45}, 'itinerary': {'cycles': 3500}}}
    assert 21048 < first_probe(raw, available=750000, fair_share=2929) < 750000 // 4
    assert first_probe(raw, available=10, fair_share=1) <= 10
    assert first_probe({'progression': {}}, available=1000, fair_share=12) == 12


def test_adaptive_widening_recovers_the_reduced_checkpoint_reversal():
    from dfo_optimizer.class_document import ATTRIBUTES
    from dfo_optimizer.search_request import EXAMPLE_SKILLS
    req = json.loads((EXAMPLES / 'build-checkpoint-reversal.json').read_bytes())
    req.pop('families')
    req['class_search'] = {**reduced()['class_search'], 'objective': 'diverse',
                           'profile': 'spellcaster_discovery_v1', 'top_k': 1, 'required_masteries': [],
                           'skill_domains': [[i] for i in EXAMPLE_SKILLS],
                           'attribute_domains': {**dict.fromkeys(ATTRIBUTES, [50]), 'strength': [30],
                                                 'intelligence': [70], 'speed': [49,50,51], 'endurance': [49,50,51]}}
    req.update(class_admission_strategy='adaptive', roll_seeds=[73, 97], objective='overall_pve',
               search={'max_nodes': 250000, 'wall_seconds': 0})
    result = optimize_build(req)
    exact = optimize_build({**req, 'class_admission_strategy': 'exhaustive'})
    assert exact['exact'] and result['exact']
    assert result['class_admission']['admitted'] == exact['class_admission']['admitted'] > 1
    def metrics(plan):
        return {(r['roll_seed'], r['total_spent_gold'], tuple(s['dps'] for s in r['checkpoints']))
                for r in plan['candidates']}
    assert metrics(result) == metrics(exact)
    assert any(early > late for _, _, (early, late) in metrics(result))
    assert any(early < late for _, _, (early, late) in metrics(result))
    assert replay_build(result)['validated']


def test_replay_shares_one_progression_reconstruction_across_witnesses(monkeypatch):
    from dfo_optimizer import lifecycle
    plan = optimize_build(reduced('examples'))
    calls = []
    original = lifecycle._route
    def route(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(lifecycle, '_route', route)
    witnesses = [*plan['candidates'], *plan['comparison_witnesses']]
    assert len(witnesses) > 2
    assert replay_build(plan)['validated']
    assert len(calls) == len({(w['family'], w['roll_seed'], tuple(w['progression_choices'])) for w in witnesses})


def test_paired_pareto_uses_one_class_with_a_replayed_route_for_each_roll():
    req = reduced()
    req.update(objective='overall_pve')
    plan = optimize_build(req)
    frontier = plan['paired_family_frontier']
    witnesses = plan['candidates'] + plan['comparison_witnesses']
    assert frontier['points']
    for point in frontier['points']:
        selected = [witnesses[r['witness_index']] for r in point['rolls']]
        assert {w['family'] for w in selected} == {point['family']}
        assert [w['roll_seed'] for w in selected] == req['roll_seeds']
        assert point['means']['early_dps'] == pytest.approx(sum(w['checkpoints'][0]['dps'] for w in selected)/len(selected))
        assert point['means']['spent_gold'] == sum(w['total_spent_gold'] for w in selected)/len(selected)
    from dfo_optimizer.lifecycle import _id
    frontier['points'][0]['means']['final_dps'] += 1
    plan['result_hash'] = _id(plan)
    with pytest.raises(ValueError, match='paired family'):
        replay_build(plan)


def test_custom_and_baseline_archives_compare_on_the_same_prospective_axes():
    from dfo_optimizer.lifecycle import compare_builds
    from dfo_optimizer.build_baselines import resolve_family_baseline
    from dfo_optimizer.ruleset import load_ruleset
    req = json.loads((EXAMPLES / 'build-lifecycle.json').read_bytes())
    req.update(objective='overall_pve', families=req['families'][:1])
    reference = optimize_build(req)
    start = resolve_family_baseline('m1-breton-caster', load_ruleset())
    custom = optimize_build({**req, 'families': [{'id': 'My custom class', 'start': {**start, 'profile': 'custom'}}]})
    comparison = compare_builds([reference, custom])
    points = comparison['paired_family_frontier']['points']
    assert {r['plan_index'] for r in points} == {0,1}
    assert all(len(row['rolls']) == len(req['roll_seeds']) for row in points)


def test_cap_schedules_two_generated_families_across_common_rolls_before_breadth(monkeypatch):
    from dfo_optimizer import discovery_presets
    from dfo_optimizer.class_document import ATTRIBUTES
    from dfo_optimizer.search_request import EXAMPLE_SKILLS
    req = reduced('adaptive')
    schedule = req['progression']
    req['progression'] = {'itinerary': {'cycles': 1800}, 'goal': {'level': 45}}
    monkeypatch.setattr(discovery_presets,'bind_itinerary',lambda *_: schedule)
    req['class_search'].update(profile='spellcaster_discovery_v1',objective='diverse',top_k=4,race_ids=[1,2,3,4],
                               attribute_domains=dict.fromkeys(ATTRIBUTES,[50]),required_masteries=[],
                               skill_domains=[[i] for i in EXAMPLE_SKILLS])
    req['families'] = [{'id':'Control','baseline_id':'m1-breton-caster'}]
    result = optimize_build(req)
    pilots = result['refinement']['trials'][:4]
    assert [r['roll_seed'] for r in pilots] == [42,97,42,97]
    first, second = pilots[0]['family'], pilots[2]['family']
    assert first != second and 'Control' not in (first,second)
    assert [r['family'] for r in pilots] == [first,first,second,second]
    assert all(r['validated_routes'] for r in pilots)


def test_nested_class_budget_is_shared_by_every_adaptive_pass():
    from dfo_optimizer.class_document import ATTRIBUTES
    from dfo_optimizer.search_request import EXAMPLE_SKILLS
    req = reduced('adaptive')
    req['class_search'].update(profile='spellcaster_discovery_v1',objective='diverse',max_nodes=8000,
                               top_k=2,required_masteries=[],skill_domains=[[i] for i in EXAMPLE_SKILLS],
                               attribute_domains=dict.fromkeys(ATTRIBUTES,[50]),race_ids=[1,2,3,4])
    plan = optimize_build(req)
    assert plan['candidates']
    assert plan['class_admission']['class_nodes'] <= req['class_search']['max_nodes']
