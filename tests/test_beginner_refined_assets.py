from collections import Counter

import pytest

from dfo_optimizer.beginner_classes import manual_classes
from dfo_optimizer.beginner_progression import CheckpointCache
from dfo_optimizer.beginner_refined_assets import asset_law, equipment_options, hold_book, prepare, prepare_options, tune
from dfo_optimizer.beginner_scenarios import _stage, scenario_matrix
from dfo_optimizer.encounter_request import _slot
from dfo_optimizer.physical_encounter import laws
from dfo_optimizer.ruleset import _progression_service_rules


class Budget:
    memory = 64 << 20
    token = None

    def __init__(self):
        self.used = Counter()

    def remaining(self):
        return 1_000_000 - self.used['spell_nodes'] - self.used['encounter_events']

    def seconds(self):
        return 60


@pytest.fixture(scope='module')
def projected():
    rules = _progression_service_rules(None)
    family = manual_classes(ruleset=rules)[0]
    result = CheckpointCache(rules).project({**family['start'], 'roll_seed': 42})
    return result['checkpoints'], rules


def test_mundane_loadouts_respect_access_class_and_weight(projected):
    (birth, middle, cap), _ = projected
    assert equipment_options(birth, 'owned')[0]['loadout'] == birth['loadout']
    assert len(equipment_options(middle, 'representative')) >= 2
    for mode in ('representative', 'theoretical'):
        stage = equipment_options(cap, mode)[0]
        assert stage['carry']['headroom_kg'] >= 0
        assert stage['physical_player']['weapon']['templateIndex'] in map(int, laws()['weapons'])
        assert stage['asset_access']['mode'] == mode
        assert all(a['kind'] != 'hypothetical_item' for a in stage['transactions'])
        assert stage['loadout'] != cap['loadout']


def test_owned_spells_are_preserved_and_optimized_choices_are_funded(projected):
    (birth, _, cap), rules = projected
    budget = Budget()
    assert prepare(birth, 'owned', rules, budget)['spells'] == birth['spells']
    optimized = prepare(cap, 'representative', rules, budget)
    quotes = [a for a in optimized['acquisitions'] if a['kind'] == 'optimized_spell']
    owned = prepare(cap, 'owned', rules, budget)
    assert quotes and sum(a['gold'] for a in quotes) <= owned['state']['gold']
    assert all(a['id'] in {s['id'] for s in optimized['spells']} for a in quotes)
    assert budget.used['spell_nodes'] > 0
    assert owned['state']['gold'] > optimized['state']['gold']
    counterpart = hold_book(owned, optimized)
    assert counterpart['loadout'] == owned['loadout']
    assert counterpart['spells'] == optimized['spells']
    assert counterpart['state']['gold'] == optimized['state']['gold']
    combined = {**optimized, 'spell_policy': 'burst', 'variants': {'owned_only': owned}}
    taken = _stage(combined, 'owned_only')
    assert taken['physical_player'] == owned['physical_player']
    assert taken['physical_player'] != optimized['physical_player']
    assert taken['spell_policy'] == 'steady'


def test_source_defensive_gold_price_matches_shared_encounter_components():
    for spell in asset_law()[0]['defense']:
        blockers = []
        _, gold, _ = _slot(spell['effect'], blockers)
        assert not blockers
        assert gold == spell['gold']
        assert gold * 60 // 400 == spell['sp']


def test_theoretical_book_stays_out_of_practical_receipts(projected):
    (_, _, cap), rules = projected
    result = prepare_options(cap, 'theoretical', rules, Budget())
    assert all(row['spells'] == result[0]['spells'] for row in result)
    assert result[0]['theoretical_spells']
    assert any(s['effects'][0]['effect_id'] == '35,255' and s['id'].startswith('Shield ')
               for s in result[0]['spells'])
    assert all(not row['acquisitions'] for row in result)


def test_replay_checked_native_policy_tuning(projected):
    (_, _, cap), rules = projected
    budget = Budget()
    prepared = prepare(cap, 'theoretical', rules, budget)
    case = next(c for c in scenario_matrix() if c['id'] == 'sustained')
    result = tune(prepared, case, rules, budget)
    assert result['spells'] == prepared['spells']
    assert result['spell_policy'] in ('steady', 'heal_early', 'conserve', 'burst')
    assert result['policy_tuning']['policies_evaluated'] >= 2
    assert budget.used['encounter_events'] > 0
