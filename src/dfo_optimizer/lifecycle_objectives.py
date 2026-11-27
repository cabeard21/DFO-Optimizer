"""Checkpoint objective definitions shared by lifecycle search, comparison and refinement."""
from math import isclose

from .progression_replay import require


OBJECTIVES = {
    "legacy": "Checkpoint DPS, practice, rest passes, personal minutes and gold.",
    "overall_pve": "Pareto frontier of checkpoint DPS, practice, rest passes, personal minutes and gold.",
    "endgame_damage": "Highest funded final-checkpoint direct spell DPS.",
    "encounter_damage": "Most clipped hostile HP lost in the final encounter.",
    "clear_performance": "Highest final encounter clear indicator and lowest horizon-censored clear time.",
    "damage_per_sp": "Most final-checkpoint hostile HP lost per gross SP spent. Undefined at zero spend.",
    "resource_sustain": "Most remaining SP after clearing the final encounter. Undefined for unfinished fights.",
    "survivability": "Highest final encounter survival indicator on the shared trial.",
    "progression_effort": "Pareto frontier of practice, rest passes, personal minutes and total gold to goal.",
    "pareto": "Pareto frontier of all supported checkpoint performance and progression effort axes.",
}
ENCOUNTER_ONLY = {"encounter_damage", "clear_performance", "resource_sustain", "survivability"}


def validate_objective(raw):
    name = raw.get("objective", "legacy")
    require(isinstance(name, str) and name in OBJECTIVES, "unknown lifecycle objective")
    require(name not in ENCOUNTER_ONLY or "encounter" in raw, f"{name} requires an encounter")
    require(name != "endgame_damage" or "encounter" not in raw, "endgame_damage requires direct spell evaluation")
    return name


def stage_performance(damage, gross_sp, trial=None, horizon=None):
    result = {"damage": damage, "spent_sp": gross_sp,
              "damage_per_sp": damage / gross_sp if gross_sp else None}
    if trial is not None:
        result.update(cleared=trial["cleared"], survived=not trial["dead"], ending_sp=trial["end_sp"],
                      censored_clear_us=trial["end_us"] if trial["cleared"] else horizon)
    return result


def _stage_axes(perf, objective):
    # Undefined nonnegative metrics sort below every defined value, including zero.
    efficiency = perf["damage_per_sp"]
    ratio = efficiency if efficiency is not None else -1
    clear = (int(perf["cleared"]), -perf["censored_clear_us"]) if "cleared" in perf else ()
    sustain = perf["ending_sp"] if clear and clear[0] else -1
    if objective == "damage_per_sp":
        return (ratio,)
    if objective == "encounter_damage":
        return (perf["damage"],)
    if objective == "clear_performance":
        return clear
    if objective == "resource_sustain":
        return (sustain,)
    if objective == "survivability":
        return (int(perf["survived"]),)
    if objective == "pareto":
        return (ratio, *clear, sustain, int(perf["survived"])) if clear else (ratio,)
    return ()


def ranking_coordinates(witness, objective):
    steps = witness["checkpoints"]
    effort = witness["effort"]
    costs = (-effort["practice"], -effort["rest_passes"], -effort["minutes"], -witness["total_spent_gold"])
    if objective in ("overall_pve", "legacy"):
        return (*[s["dps"] for s in steps], *costs)
    if objective == "endgame_damage":
        return (steps[-1]["dps"],)
    if objective == "progression_effort":
        return costs
    if objective == "pareto":
        return (*[v for s in steps for v in (s["dps"], *_stage_axes(s["performance"], objective))], *costs)
    return _stage_axes(steps[-1]["performance"], objective)


def refinement_priority(witness, objective):
    if not witness:
        return ()
    if objective in (None, "legacy", "overall_pve", "pareto"):
        return (witness["checkpoints"][-1]["dps"], witness["checkpoints"][0]["dps"], -witness["total_spent_gold"])
    return ranking_coordinates(witness, objective)


def check_native_metrics(row, steps, objective):
    if "metric_axes" not in row:
        return  # Already archived witnesses carry replayed checkpoints.
    expected = [x for step in steps for x in _stage_axes(step["performance"], objective)]
    actual = row["metric_axes"]
    require(len(actual) == len(expected) and
            all(isclose(x, y, rel_tol=1e-10, abs_tol=1e-11) for x, y in zip(actual, expected)),
            "native objective differs from independent checkpoint replay")
