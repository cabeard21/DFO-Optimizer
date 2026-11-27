from collections import defaultdict
from statistics import fmean

from .lifecycle_objectives import _stage_axes
from .progression_replay import require


EFFORT = ("practice", "rest_passes", "minutes", "spent_gold")
LEGACY_AXES = ("early_dps", "final_dps", *EFFORT)
ENCOUNTER = ("cleared", "censored_clear_us", "ending_sp_after_clear", "survived")


def direction(axis):
    return -1 if axis in EFFORT or axis.endswith("censored_clear_us") else 1


def metrics(row, objective, label, *, legacy=False):
    cost = {**row["effort"], "spent_gold": row["total_spent_gold"]}
    result = {}
    steps = row["checkpoints"]
    if objective != "progression_effort":
        if legacy:
            result.update(early_dps=steps[0]["dps"], final_dps=steps[-1]["dps"])
        else:
            for i, step in enumerate(steps):
                prefix = "final" if i == len(steps) - 1 else "early" if not i else f"{label}_{step[label]}"
                result[f"{prefix}_dps"] = step["dps"]
                if objective == "pareto":
                    axes = _stage_axes(step["performance"], objective)
                    names = ("damage_per_sp", *ENCOUNTER)
                    for name, value in zip(names[: len(axes)], axes, strict=True):
                        result[f"{prefix}_{name}"] = (
                            -value if name == "censored_clear_us" else value if value >= 0 else None
                        )
    return {**result, **{key: cost[key] for key in EFFORT}}


def coordinates(values, axes):
    return tuple(values[key] * direction(key) if values[key] is not None else -1 for key in axes)


def means(values):
    return {
        key: fmean(row[key] for row in values) if all(row[key] is not None for row in values) else None
        for key in values[0]
    }


def signature(rows, label, axes):
    return tuple(tuple(s[label] for s in r["checkpoints"]) for r in rows), tuple(axes)


def _front(groups):
    from . import _lifecycle

    kept = []
    for (_, axes), points in groups.items():
        coords = [coordinates(p["means"], axes) for p in points]
        kept.extend(points[i] for i in _lifecycle.frontier_indices(coords))
    return kept


def _policies(pairs, index, objective, label):
    panels = [[(r, metrics(r, objective, label)) for r in t.witnesses.values()] for t in pairs]
    axes = list(dict.fromkeys(k for panel in panels for _, values in panel for k in values))
    policies = {}
    for axis in axes:
        available = [[(r, v) for r, v in panel if axis in v] for panel in panels]
        if not all(available):
            continue

        def score(item):
            _, values = item
            return (*coordinates(values, [axis]), *coordinates(values, values))

        routes, values = zip(*(max(panel, key=score) for panel in available), strict=True)
        shared = [k for k in values[0] if all(k in row for row in values)]
        selected = tuple(index(r) for r in routes)
        if selected in policies:
            policies[selected][1]["selectors"].append(axis)
            continue
        point = {
            "family": pairs[0].family[0],
            "axes": shared,
            "selectors": [axis],
            "means": means([{k: row[k] for k in shared} for row in values]),
            "rolls": [{"seed": t.seed, "witness_index": i} for t, i in zip(pairs, selected, strict=True)],
        }
        policies[selected] = (signature(routes, label, shared), point)
    return policies.values()


def paired_frontier(trials, index, objective, explicit):
    families, groups = defaultdict(list), defaultdict(list)
    for trial in trials:
        families[trial.family[0]].append(trial)
    label = "stage" if explicit else "level"
    for pairs in families.values():
        if all(t.witnesses for t in pairs):
            for key, point in _policies(pairs, index, objective, label):
                groups[key].append(point)
    points = _front(groups)
    axes = list(dict.fromkeys(key for point in points for key in point["axes"]))
    return {
        "version": 2,
        "axes": axes,
        "directions": {k: "max" if direction(k) > 0 else "min" for k in axes},
        "policy_enumeration_complete": False,
        "points": points,
        "scope": (
            "One fixed class and one replayed route per birth roll. Each policy prioritizes one axis across "
            "the panel. Means weight all rolls equally. Pareto comparisons use matching checkpoint panels "
            "and objective axes. Per-roll archives retain further tradeoffs."
        ),
    }


def compare_paired(plans):
    groups = defaultdict(list)
    template = plans[0]["paired_family_frontier"]
    label = "stage" if "checkpoints" in plans[0]["frozen_request"] else "level"
    for i, plan in enumerate(plans):
        witnesses = [*plan["candidates"], *plan["comparison_witnesses"]]
        for point in plan["paired_family_frontier"]["points"]:
            routes = [witnesses[p["witness_index"]] for p in point["rolls"]]
            groups[signature(routes, label, point.get("axes", template["axes"]))].append(
                {**point, "plan_index": i}
            )
    points = _front(groups)
    axes = list(dict.fromkeys(k for p in points for k in p.get("axes", template["axes"])))
    return {
        **template,
        "points": points,
        "axes": axes,
        **(
            {"directions": {k: "max" if direction(k) > 0 else "min" for k in axes}}
            if template.get("version") == 2
            else {}
        ),
    }


def verify_paired_frontier(plan, witnesses):
    frontier = plan.get("paired_family_frontier")
    if frontier is None:
        return
    raw = plan["frozen_request"]
    objective, label = raw.get("objective"), "stage" if "checkpoints" in raw else "level"
    legacy = "version" not in frontier
    summaries = {s["family"]: s for s in plan["family_comparisons"]}
    groups = defaultdict(list)
    for point in frontier["points"]:
        rolls = point["rolls"]
        require(
            point["family"] in summaries and summaries[point["family"]]["complete_roll_set"],
            "invalid paired family",
        )
        require([r["seed"] for r in rolls] == plan["paired_rolls"], "incomplete paired family panel")
        indices = [r["witness_index"] for r in rolls]
        require(
            all(type(i) is int and 0 <= i < len(witnesses) for i in indices), "invalid paired family witness"
        )
        selected = [witnesses[i] for i in indices]
        require(
            all(
                w["family"] == point["family"] and w["roll_seed"] == r["seed"]
                for w, r in zip(selected, rolls, strict=True)
            ),
            "invalid paired family witness",
        )
        values = [metrics(row, objective, label, legacy=legacy) for row in selected]
        axes = [k for k in values[0] if all(k in v for v in values)]
        require(
            point.get("axes", frontier["axes"]) == axes
            and point["selectors"]
            and set(point["selectors"]) <= set(axes),
            "invalid paired family selector",
        )
        require(
            point["means"] == means([{k: v[k] for k in axes} for v in values]),
            "paired family performance differs from selected witnesses",
        )
        groups[signature(selected, label, axes)].append(point)
    kept = {p["family"] for p in frontier["points"]}
    if not legacy:
        axes = list(dict.fromkeys(k for p in frontier["points"] for k in p["axes"]))
        require(
            frontier["version"] == 2
            and frontier["axes"] == axes
            and frontier["policy_enumeration_complete"] is False
            and frontier["directions"] == {k: "max" if direction(k) > 0 else "min" for k in axes}
            and len(_front(groups)) == len(frontier["points"]),
            "invalid paired family frontier",
        )
    require(
        all(
            s["paired_pareto"] == (family in kept if s["complete_roll_set"] else None)
            for family, s in summaries.items()
        ),
        "invalid paired family membership",
    )
