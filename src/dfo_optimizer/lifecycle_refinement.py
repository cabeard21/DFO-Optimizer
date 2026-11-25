"""Allocate a single deterministic native node budget across paired class trials."""
from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class Trial:
    family: tuple
    seed: int | None
    stopping_reasons: list = field(default_factory=lambda: ["node_limit"])
    witnesses: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)
    last_limit: int = 0

    @property
    def peak(self):
        return max((r["checkpoints"][-1]["dps"] for r in self.witnesses.values()), default=0)


def refine_families(raw, rules, families, rolls, limits, truncated, cancel, started, search):
    from .lifecycle import _finish
    from .progression import digest

    trials = [Trial(family, seed) for seed in rolls for family in families]
    counters = dict(nodes=0, pruned=0, leaves=0, evaluations=0, cache_hits=0,
                    work_bytes=0, progression_nodes=0, layouts=0)
    history = []
    first = None
    checked = 0
    stops = ["class_limit"] if truncated else []
    budget = limits["max_nodes"]
    deadline = started + limits["wall_seconds"] if limits["wall_seconds"] else None

    def visit(trial, node_limit, phase):
        nonlocal checked, first
        if cancel is not None and cancel.cancelled():
            stops.append("cancelled")
            return False
        now = perf_counter()
        if deadline is not None and now >= deadline:
            stops.append("time_limit")
            return False
        if node_limit < 1:
            return False
        allocation = {**limits, "max_nodes": node_limit, "wall_seconds": deadline-now if deadline else 0.}
        result = search(trial.family, trial.seed, allocation)
        used = result["counters"]["nodes"]
        if used > node_limit:
            raise RuntimeError("Lifecycle trial exceeded its allocated node budget")
        for key, count in result["counters"].items():
            counters[key] = max(counters[key], count) if key == "work_bytes" else counters.get(key, 0) + count
        if first is None and result["timings"]["first_validated_seconds"] is not None:
            first = now - started + result["timings"]["first_validated_seconds"]
        checked += result["validation"]["routes_checked"]
        trial.last_limit = node_limit
        trial.gaps = result["gaps"]
        trial.stopping_reasons = result["stopping_reasons"]
        for witness in result["candidates"]:
            trial.witnesses[digest([witness["progression_choices"], witness["choices"]])] = witness
        history.append({"family": trial.family[0], "roll_seed": trial.seed, "phase": phase,
                        "limit": node_limit, "nodes": used, "termination": result["termination"]})
        return True

    # Spend at most a quarter on initial probes. A small global budget can
    # legally terminate before every family gets its first node.
    probe = max(1, budget // (4 * len(trials)))
    for trial in trials:
        if not visit(trial, min(probe, budget - counters["nodes"]), "probe"):
            break

    # Refine leaders first, with a reserved share for every unfinished pair.
    # A fresh deeper run spends its whole allocation, including repeated work.
    # Revisit only when enough budget remains to improve the previous limit.
    while not any(reason in stops for reason in ("cancelled", "time_limit")):
        pending = sorted((t for t in trials if "node_limit" in t.stopping_reasons), key=lambda t: -t.peak)
        if not pending:
            break
        progressed = False
        for i, trial in enumerate(pending):
            remaining = budget - counters["nodes"]
            allocation = remaining // (len(pending) - i)
            if allocation <= trial.last_limit:
                continue
            if not visit(trial, allocation, "refine"):
                break
            progressed = True
        if not progressed:
            break

    for trial in trials:
        stops.extend(trial.stopping_reasons)
    rows = [r for t in trials for r in t.witnesses.values()]
    gaps = [g for t in trials for g in t.gaps]
    plan = _finish(raw, rules, rolls, rows, gaps, counters, stops, first, started, checked)
    plan["refinement"] = {"strategy": "equal probes then deeper paired searches", "trials": history}
    return plan
