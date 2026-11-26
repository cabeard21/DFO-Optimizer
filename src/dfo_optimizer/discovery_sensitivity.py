"""Rerun admission on paired, one-at-a-time changes to declared world inputs."""

from copy import deepcopy
from time import perf_counter

from .progression_domain import fields, integer, require

AXES = {
    "gear_access",
    "practice_cadence_ms",
    "challenge_level",
    "cache_gold",
    "practice_circuits",
    "horizon_us",
    "budget_gold",
    "max_nodes",
}


def vary(request, axis, value):
    query = deepcopy(request)
    if axis == "gear_access":
        require(value in ("owned", "practical", "theoretical"), "unknown sensitivity gear access")
        from .discovery_presets import _equipment

        query["equipment"] = {} if value == "owned" else _equipment(value == "theoretical")
    elif axis in ("practice_cadence_ms", "challenge_level", "cache_gold", "practice_circuits"):
        itinerary = query["progression"].get("itinerary")
        require(isinstance(itinerary, dict), "this sensitivity axis requires a conditional itinerary")
        field, low, high = {
            "practice_cadence_ms": ("cadence_ms", 1400, 1_000_000),
            "challenge_level": ("challenge_level", 0, 2000),
            "practice_circuits": ("cycles", 1, 4000),
            "cache_gold": ("cache_gold", 0, 2**31 - 1),
        }[axis]
        itinerary[field] = integer(value, axis, low, high)
    elif axis == "horizon_us":
        require("encounter" in query, "horizon sensitivity requires an encounter")
        query["encounter"]["scenario"]["horizon_us"] = integer(value, axis, 1, 3_600_000_000)
    elif axis == "max_nodes":
        query["search"] = {**query.get("search", {}), "max_nodes": integer(value, axis, 0, 2**62)}
    elif axis == "budget_gold":
        query["budget_gold"] = integer(value, axis, 0, 2**53 - 1)
    else:
        raise ValueError("unknown discovery sensitivity axis")
    return query


def run_variants(request, run, cancel, on_incumbent=None):
    """Share the total budget among the primary and each fresh comparison."""
    from .lifecycle import _controls

    config = fields(request["sensitivity"], AXES, "discovery sensitivity")
    base = {k: v for k, v in request.items() if k not in ("sensitivity", "class_admission")}
    cases = [(None, None, base)]
    for key, values in config.items():
        require(
            isinstance(values, list) and 0 < len(values) <= 12, "sensitivity requires 1..12 values per axis"
        )
        cases.extend((key, value, vary(base, key, value)) for value in values)
    limits = _controls(request)
    deadline = perf_counter() + limits["wall_seconds"] if limits["wall_seconds"] else None
    nodes = 0
    report = []
    primary = None
    for i, (axis, value, query) in enumerate(cases):
        remaining = len(cases) - i
        left = limits["max_nodes"] - nodes
        time_left = deadline - perf_counter() if deadline else 0
        if i and (
            (cancel and cancel.cancelled())
            or (limits["max_nodes"] and left <= 0)
            or (deadline and time_left <= 0)
        ):
            why = (
                "cancelled"
                if cancel and cancel.cancelled()
                else "node_limit"
                if limits["max_nodes"] and left <= 0
                else "time_limit"
            )
            report.append({"axis": axis, "value": value, "status": "unvisited", "termination": why})
            continue
        quota = max(1, left // remaining) if limits["max_nodes"] else 0
        cap = query.get("search", {}).get("max_nodes", 0)
        if axis == "max_nodes" and cap:
            quota = min(cap, quota) if quota else cap
        control = {
            **query.get("search", {}),
            "max_nodes": quota,
            "wall_seconds": max(1e-12, time_left / remaining) if deadline else 0.0,
        }
        plan = run({**query, "search": control}, on_incumbent=on_incumbent if not i else None)
        work = plan["counters"]["nodes"]
        if quota and work > quota:
            raise RuntimeError("sensitivity run exceeded its node allocation")
        nodes += work
        if i == 0:
            primary = plan
        else:
            families = sorted({row["family"] for row in plan["candidates"]})
            report.append(
                {
                    "axis": axis,
                    "value": value,
                    "status": plan["status"],
                    "input_hash": plan.get("input_hash"),
                    "result_hash": plan["result_hash"],
                    "max_nodes": quota,
                    "wall_seconds": control["wall_seconds"],
                    "roll_spread": plan["roll_spread"],
                    "frontier_size": len(plan["candidates"]),
                    "retained_families": families,
                    "nodes": work,
                }
            )
    return {
        **primary,
        "sensitivity": report,
        "sensitivity_budget": {"total": limits, "nodes_used": nodes, "variations": config},
    }
