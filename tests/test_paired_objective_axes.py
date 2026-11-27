"""Paired-family objectives use the same checkpoint outcomes as native lifecycle retention."""

from types import SimpleNamespace

from dfo_optimizer.lifecycle_family_frontier import paired_frontier


def panel(family, scores, trial=None):
    pairs = []
    for seed in (42, 43):
        steps = []
        for i, dps in enumerate(scores):
            step = {"stage": i, "level": i + 1, "dps": dps}
            if trial is not None:
                step["performance"] = {**trial, "damage": dps, "spent_sp": 2}
            steps.append(step)
        row = {
            "family": family,
            "roll_seed": seed,
            "effort": {"practice": 1, "rest_passes": 1, "minutes": 1},
            "total_spent_gold": 0,
            "checkpoints": steps,
        }
        pairs.append(SimpleNamespace(family=(family,), seed=seed, witnesses={"r": row}))
    return pairs


def test_lower_damage_surviving_family_is_nondominated():
    dead = dict(damage_per_sp=5, cleared=False, censored_clear_us=100, ending_sp=0, survived=False)
    alive = {**dead, "damage_per_sp": 3, "survived": True, "ending_sp": 20}
    trials = [*panel("glass", [10], dead), *panel("warded", [6], alive)]
    result = paired_frontier(trials, id, "pareto", True)
    assert {p["family"] for p in result["points"]} == {"glass", "warded"}
    assert result["directions"]["final_censored_clear_us"] == "min"
    assert result["policy_enumeration_complete"] is False
    for p in result["points"]:
        assert p["means"]["final_survived"] == (p["family"] == "warded")
        assert p["means"]["final_ending_sp_after_clear"] is None
        assert set(p["axes"]) == set(p["means"])


def test_intermediate_checkpoint_prevents_false_paired_dominance():
    trials = [*panel("early and final", [10, 0, 10]), *panel("middle", [8, 20, 8])]
    result = paired_frontier(trials, id, "overall_pve", True)
    assert set(p["family"] for p in result["points"]) == {"early and final", "middle"}
    assert result["axes"] == [
        "early_dps",
        "stage_1_dps",
        "final_dps",
        "practice",
        "rest_passes",
        "minutes",
        "spent_gold",
    ]
