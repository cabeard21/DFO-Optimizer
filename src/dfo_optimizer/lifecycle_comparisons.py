"""Keep an independently checked example for each family and common birth roll."""
from collections import defaultdict
from statistics import fmean

from .lifecycle_objectives import ranking_coordinates, refinement_priority


def family_comparisons(plan, trials):
    objective = plan["frozen_request"].get("objective", "legacy")
    incumbents = plan["candidates"]
    indices = {id(row): i for i, row in enumerate(incumbents)}
    extra = []
    summaries = {}
    def index(row):
        if id(row) not in indices:
            indices[id(row)] = len(incumbents) + len(extra)
            extra.append(row)
        return indices[id(row)]
    scalar = objective in ("endgame_damage", "encounter_damage", "damage_per_sp",
                           "resource_sustain", "survivability")
    for trial in trials:
        name = trial.family[0]
        family = summaries.setdefault(name, {"family": name, "baseline_id": trial.family[2], "rolls": []})
        point = {"seed": trial.seed, "witness_index": None,
                 "status": trial.stopping_reasons if trial.visited else "unvisited"}
        if trial.witnesses:
            row = max(trial.witnesses.values(), key=lambda r: refinement_priority(r, objective))
            point.update(status="validated", witness_index=index(row),
                         search_complete=not trial.stopping_reasons,
                         early_dps=row["checkpoints"][0]["dps"], final_dps=row["checkpoints"][-1]["dps"])
            if scalar:
                value, = ranking_coordinates(row, objective)
                point["score"] = value if value >= 0 else None
            if objective == "clear_performance":
                perf = row["checkpoints"][-1]["performance"]
                point.update(cleared=perf["cleared"], censored_clear_us=perf["censored_clear_us"])
        elif trial.visited:
            point["status"] = "incomplete" if trial.stopping_reasons else "no_feasible_route"
            point["stopping_reasons"] = trial.stopping_reasons
        family["rolls"].append(point)
    scores = defaultdict(list)
    for family in summaries.values():
        rolls = family["rolls"]
        family["complete_roll_set"] = all(r["status"] == "validated" for r in rolls)
        if scalar:
            mean = None
            if all(r.get("score") is not None for r in rolls):
                mean = fmean(r["score"] for r in rolls)
                scores[mean].append(family)
            family.update(mean_score=mean, rank=None)
        if objective == "clear_performance":
            full = family["complete_roll_set"]
            family.update(clear_fraction=fmean(r["cleared"] for r in rolls) if full else None,
                          censored_mean_clear_us=fmean(r["censored_clear_us"] for r in rolls) if full else None)
    for rank, value in enumerate(sorted(scores, reverse=True), 1):
        for family in scores[value]:
            family["rank"] = rank
    frontier = {}
    if objective in ("overall_pve", "pareto", "progression_effort"):
        from .lifecycle_family_frontier import paired_frontier
        paired = paired_frontier(trials, index, objective, "checkpoints" in plan["frozen_request"])
        survivors = {p["family"] for p in paired["points"]}
        for key, family in summaries.items():
            family["paired_pareto"] = key in survivors if family["complete_roll_set"] else None
        frontier["paired_family_frontier"] = paired
    return {"family_comparisons": list(summaries.values()), "comparison_witnesses": extra, **frontier}


def verify_comparisons(plan, witnesses, families):
    from .lifecycle_family_frontier import verify_paired_frontier
    from .progression_replay import require

    objective = plan["frozen_request"].get("objective", "legacy")
    expected = {}
    summaries = plan["family_comparisons"]
    require(len(summaries) == len(families) and {s["family"] for s in summaries} == set(families),
            "incomplete family comparison roster")
    for summary in summaries:
        values = []
        rolls = summary["rolls"]
        require([r["seed"] for r in rolls] == plan["paired_rolls"], "invalid family comparison roll panel")
        require(summary["complete_roll_set"] == all(p["witness_index"] is not None for p in rolls),
                "invalid family comparison coverage")
        for point in rolls:
            idx = point["witness_index"]
            require((idx is not None) == (point["status"] == "validated"), "invalid family comparison status")
            if idx is None:
                continue
            require(type(idx) is int and 0 <= idx < len(witnesses), "invalid family comparison witness")
            row = witnesses[idx]
            require(row["family"] == summary["family"] and row["roll_seed"] == point["seed"]
                    and row["checkpoints"][0]["dps"] == point["early_dps"]
                    and row["checkpoints"][-1]["dps"] == point["final_dps"], "invalid family comparison witness")
            if "mean_score" in summary:
                value, = ranking_coordinates(row, objective)
                require(point["score"] == (value if value >= 0 else None), "invalid paired objective score")
                if value >= 0:
                    values.append(value)
            if objective == "clear_performance":
                perf = row["checkpoints"][-1]["performance"]
                require(perf["cleared"] == point["cleared"] and perf["censored_clear_us"] == point["censored_clear_us"],
                        "invalid paired clear outcomes")
        if "mean_score" in summary:
            mean = fmean(values) if len(values) == len(rolls) else None
            require(mean == summary["mean_score"], "invalid paired objective mean")
            expected[summary["family"]] = mean
        if objective == "clear_performance":
            for public, key in (("clear_fraction","cleared"),("censored_mean_clear_us","censored_clear_us")):
                require(summary[public] == (fmean(p[key] for p in rolls) if summary["complete_roll_set"] else None),
                        "invalid paired clear mean")
    scores = sorted({v for v in expected.values() if v is not None}, reverse=True)
    ranks = {score: rank for rank, score in enumerate(scores, 1)}
    require(all(s["rank"] == ranks.get(expected[s["family"]]) for s in summaries if s["family"] in expected),
            "invalid paired family rank")
    verify_paired_frontier(plan, witnesses)
