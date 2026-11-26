"""Continue a single fixed itinerary across bounded native calls."""

from time import perf_counter

from .progression_domain import require
from .progression_replay import initial_effort


class ReplayInterrupted(Exception):
    def __init__(self, reason, stage, level):
        super().__init__(reason)
        self.reason = reason
        self.stage = stage
        self.level = level


def stop_reason(cancel, deadline):
    if cancel is not None and cancel.cancelled():
        return "cancelled"
    if deadline is not None and perf_counter() >= deadline:
        return "time_limit"
    return None


def interrupted_report(reason, counters, phase, stage, achieved, goal):
    return {
        "status": "cancelled" if reason == "cancelled" else "no_feasible_found",
        "termination": reason,
        "routes": [],
        "exact": False,
        "excluded_actions": {},
        "first_gap": {
            "stage": stage,
            "phase": phase,
            "reached_level": achieved,
            "requested_level": goal,
            "reasons": [reason],
        },
        "counters": dict(counters, nodes=counters.get("nodes", 0)),
    }


def search_fixed(start, stages, goal, limits, cancel, *, batch_size=32_768):
    from . import _progression

    # A single action at every window makes the complete attained state at the
    # boundary sufficient. A branching frontier would require all continuations.
    require(
        not limits["final_stage_only"] and all(len(s) == 1 for s in stages),
        "batched progression requires a deterministic first-goal itinerary",
    )
    began = perf_counter()
    path = {"state": start, "choices": [], "effort": initial_effort()}
    stats = {
        "results": [],
        "termination": "exhausted",
        "nodes": 0,
        "leaves": 0,
        "pruned": 0,
        "cache_hits": 0,
        "work_bytes": 0,
        "native_batches": 0,
        "first_feasible_seconds": None,
    }
    for offset in range(0, len(stages), batch_size):
        seconds = limits["wall_seconds"] - (perf_counter() - began)
        nodes = limits["max_nodes"] - stats["nodes"] if limits["max_nodes"] else 0
        if limits["wall_seconds"] and seconds <= 0:
            stats["termination"] = "time_limit"
            break
        if limits["max_nodes"] and nodes <= 0:
            stats["termination"] = "node_limit"
            break
        windows = stages[offset : offset + batch_size]
        report = _progression.search(
            path["state"],
            windows,
            goal,
            **{**limits, "max_nodes": nodes, "wall_seconds": max(0.0, seconds), "cancel": cancel},
        )
        for key in ("nodes", "leaves", "pruned", "cache_hits"):
            stats[key] += report[key]
        stats["native_batches"] += 1
        stats["termination"] = report["termination"]
        stats["work_bytes"] = max(stats["work_bytes"], report["work_bytes"])
        lane = report["results"][0] if report["results"] else report["prefix"]
        path["choices"].extend(lane["choices"])
        path = {
            **lane,
            "choices": path["choices"],
            "effort": {k: e + lane["effort"][k] for k, e in path["effort"].items()},
        }
        if report["results"]:
            stats["results"] = [path]
            stats["first_feasible_seconds"] = perf_counter() - began
            break
        if report["termination"] != "exhausted" or len(lane["choices"]) < len(windows):
            break
    return {**stats, "prefix": path}
