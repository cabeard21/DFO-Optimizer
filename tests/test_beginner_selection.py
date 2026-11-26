import pytest

from dfo_optimizer.beginner_ranking import evaluate_metrics, pick_builds, ranking_key


def trial(case="physical", roll=42, *, alive=True, clear=True, damage=10, spent=2, elapsed=5):
    return {"status": "replayed", "scenario": case, "stage": "cap", "variant": "baseline",
            "roll_seed": roll, "seed": 101, "survived": alive, "cleared": clear,
            "censored_clear_us": elapsed if clear else 10, "horizon_us": 10, "damage": damage,
            "spent_sp": spent, "minimum_hp": 20 if alive else 0, "max_hp": 50}


def build(identity, trials, *, materials=3, speed=0.30):
    return {"id": identity, "race": identity, "race_id": identity,
            "class": {"skills": {}, "advantages": [], "disadvantages": []},
            "metrics": evaluate_metrics(trials, plate_weapon_materials=materials,
                                        advancement_multiplier=speed, mean_practice=100)}


def test_surviving_every_kind_of_fight_beats_high_average_damage():
    robust = build("safe", [trial(), trial("enemy_caster")])
    cannon = build("cannon", [trial(damage=100), trial("enemy_caster", alive=False, clear=False)])
    chosen, others = pick_builds([cannon, robust])
    assert chosen["id"] == "safe"
    assert [entry["id"] for entry in others] == ["cannon"]
    assert cannon["metrics"]["worst_clear_rate"] == 0
    assert cannon["metrics"]["mean_censored_clear_fraction"] == .75


def test_scenario_fractions_pair_birth_and_combat_draws():
    rows = [trial(), trial(roll=43, clear=False), trial("resistant"), trial("resistant", roll=43)]
    m = build("mage", rows)["metrics"]
    assert m["worst_clear_rate"] == .5
    assert m["mean_clear_rate"] == .75
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_metrics(rows + rows[:1], plate_weapon_materials=1, advancement_multiplier=.3, mean_practice=0)
    with pytest.raises(ValueError, match="panel"):
        evaluate_metrics(rows[:-1], plate_weapon_materials=1, advancement_multiplier=.3, mean_practice=0)


def test_uncertain_combat_never_scores_as_a_loss_or_free_survival():
    with pytest.raises(ValueError, match="replayed"):
        build("unknown", [{**trial(), "status": "unsupported"}])
    row = build("sword", [trial(spent=0)])
    assert row["metrics"]["mean_damage_per_sp"] is None
    assert build("ordinary", [trial(spent=2)])["metrics"]["mean_damage_per_sp"] is None
    assert build("dungeon", [trial("sustained", spent=2)])["metrics"]["mean_damage_per_sp"] == 5


def test_usable_materials_can_justify_slower_advancement_and_ties_prefer_fast():
    fewer = build("fast", [trial()], materials=1)
    flexible = build("medium", [trial()], speed=.4)
    fastest = build("fastest", [trial()])
    assert sorted([fewer, flexible, fastest], key=ranking_key) == [fastest, flexible, fewer]
    assert pick_builds([fewer, flexible, fastest])[1] == []


def test_durable_alternative_when_all_families_lose_one_stress_case():
    hard = trial("enemy_caster", alive=False, clear=False)
    caster = build("caster", [trial(), hard])
    bruiser = build("bruiser", [{**trial(clear=False), "minimum_hp":40}, hard])
    winner, alts = pick_builds([bruiser,caster])
    assert winner["id"] == "caster"
    assert [(r["id"],r["alternative_axis"]) for r in alts] == [("bruiser","mean_min_hp_fraction")]

