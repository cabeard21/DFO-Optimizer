"""Allocate a single deterministic native node budget across paired class trials."""
from dataclasses import dataclass, field
from time import perf_counter


def first_probe(raw, available, fair_share):
    """Give one prospective itinerary enough room to reach a replayable route.

    A six-skill circuit has at most 25 windows per day. This is a scheduling
    estimate, never a feasibility bound. Limit the pilot to an eighth of the
    remaining budget and return unused nodes to subsequent pairs.
    """
    itinerary = raw.get("progression", {}).get("itinerary")
    if not itinerary:
        return fair_share
    from .progression_domain import integer
    estimated = 25 * integer(itinerary.get("cycles"), "itinerary cycles", 1, 4000)
    return max(fair_share, min(estimated, available // 8))


@dataclass
class Trial:
    family: tuple
    seed: int | None
    stopping_reasons: list = field(default_factory=lambda: ["node_limit"])
    witnesses: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)
    last_limit: int = 0
    visited: bool = False

    @property
    def peak(self):
        return max((r["checkpoints"][-1]["dps"] for r in self.witnesses.values()), default=0)


def refine_families(raw, rules, families, rolls, limits, truncated, cancel, started, search,
                    *, admission=None, on_incumbent=None):
    from .lifecycle import _finish
    from .progression import digest

    trials = [Trial(family, seed) for seed in rolls for family in families]
    counters = dict(nodes=0, pruned=0, leaves=0, evaluations=0, cache_hits=0,
                    work_bytes=0, progression_nodes=0, layouts=0)
    if admission is not None:
        counters.update(nodes=admission.nodes, work_bytes=admission.work_bytes)
    history = []
    best_by_seed = {}
    first = None
    checked = 0
    stops = ["class_limit"] if truncated else []
    budget = limits["max_nodes"]
    deadline = started + limits["wall_seconds"] if limits["wall_seconds"] else None

    def finish(stop_reasons):
        rows = [r for t in trials for r in t.witnesses.values()]
        gaps = [g for t in trials for g in t.gaps]
        frozen = admission.freeze() if admission is not None else raw
        plan = _finish(frozen, rules, rolls, rows, gaps, dict(counters), stop_reasons, first, started, checked)
        if admission is not None:
            from .lifecycle_admission import annotate
            plan = annotate(plan, admission, trials, history)
        elif raw.get("objective", "legacy") != "legacy" and rolls != [None]:
            from .lifecycle import _id
            from .lifecycle_comparisons import family_comparisons
            plan.update(family_comparisons(plan,trials))
            plan["result_hash"] = _id(plan)
        return plan

    def priority(trial):
        if "objective" not in raw:
            return (trial.peak,)
        from .lifecycle_objectives import refinement_priority
        return max((refinement_priority(row, raw["objective"]) for row in trial.witnesses.values()), default=())

    def visit(trial, node_limit, phase):
        nonlocal checked, first
        if cancel is not None and cancel.cancelled():
            stops.append("cancelled")
            return False
        now = perf_counter()
        if deadline is not None and now >= deadline:
            stops.append("time_limit")
            return False
        if budget and node_limit < 1:
            return False
        allocation = {**limits, "max_nodes": node_limit, "wall_seconds": deadline-now if deadline else 0.}
        result = search(trial.family, trial.seed, allocation)
        used = result["counters"]["nodes"]
        if node_limit and used > node_limit:
            raise RuntimeError("Lifecycle trial exceeded its allocated node budget")
        for key, count in result["counters"].items():
            counters[key] = max(counters[key], count) if key == "work_bytes" else counters.get(key, 0) + count
        is_first = first is None and result["timings"]["first_validated_seconds"] is not None
        if is_first:
            first = now - started + result["timings"]["first_validated_seconds"]
        checked += result["validation"]["routes_checked"]
        trial.last_limit = node_limit
        trial.visited = True
        trial.gaps = result["gaps"]
        trial.stopping_reasons = result["stopping_reasons"]
        for witness in [*result["candidates"], *result.get("final_checkpoint_witnesses", [])]:
            trial.witnesses[digest([witness["progression_choices"], witness["choices"]])] = witness
        history.append({"family": trial.family[0], "roll_seed": trial.seed, "phase": phase,
                        "limit": node_limit, "nodes": used, "termination": result["termination"]})
        if admission is not None:
            observed = priority(trial) if trial.witnesses else ()
            best_by_seed[trial.seed] = max(best_by_seed.get(trial.seed, ()), observed)
            history[-1].update(elapsed_seconds=perf_counter()-started, validated_routes=len(trial.witnesses),
                               priority=list(observed), best_observed_priority_on_roll=list(best_by_seed[trial.seed]))
        if is_first and on_incumbent is not None:
            on_incumbent(finish([*stops, "search_in_progress"]))
        return True

    # Spend at most a quarter on initial probes. A small global budget can
    # legally terminate before every family gets its first node.
    remaining = budget - counters["nodes"]
    probe = max(1, remaining // (4 * max(1, len(trials)))) if budget else 0
    adaptive = admission is not None and admission.strategy == "adaptive"
    now = perf_counter()
    probe_deadline = now + (deadline - now) / 3 if adaptive and deadline else None
    progression = raw["progression"]
    cap_itinerary = (adaptive and progression.get("itinerary") and
                     progression.get("goal", {}).get("level") == rules["progression_rules"]["limits"]["level_cap"])
    if cap_itinerary:
        # Expensive cap routes often cannot finish on an equal first probe.
        # Qualify comparison families across the same roll block before widening.
        # Leave a quarter of downstream work for exploration and unfinished pairs.
        blocks = {}
        for trial in trials:
            if trial.family[0] in admission.families:
                blocks.setdefault(trial.family[0], []).append(trial)
        completed = 0
        pilot_ceiling = counters["nodes"] + 3 * remaining // 4
        for block in blocks.values():
            if completed == 2 or cancel.cancelled() or deadline and perf_counter() >= deadline:
                break
            for i, trial in enumerate(block):
                needed = (2-completed)*len(rolls) - i
                left = pilot_ceiling - counters["nodes"]
                if budget and left < needed:
                    break
                share = left // needed if budget else 0
                if not visit(trial, share, "paired_cap_probe") or not trial.witnesses:
                    break
            if all(t.witnesses for t in block):
                completed += 1
    for i, trial in enumerate(trials):
        if trial.visited:
            continue
        if first is not None and probe_deadline is not None and perf_counter() >= probe_deadline:
            break
        share = first_probe(raw, remaining, probe) if i == 0 and admission is not None and budget else probe
        if not visit(trial, min(share, budget - counters["nodes"]) if budget else 0, "probe"):
            break

    if adaptive:
        from .lifecycle_domain import catalog

        def expand(operation, phase):
            before = admission.nodes
            new_families = operation()
            counters["nodes"] += admission.nodes - before
            counters["work_bytes"] = max(counters["work_bytes"], admission.work_bytes)
            new = [Trial(family, seed) for family in catalog(new_families, rules) for seed in rolls] if new_families else []
            trials.extend(new)
            for trial in new:
                if not visit(trial, min(probe, budget - counters["nodes"]) if budget else 0, phase):
                    break
            return len(new)

        def alive():
            return not cancel.cancelled() and (not deadline or perf_counter() < deadline)

        leaders = [t for t in trials if t.witnesses and t.family[0] in admission.families]
        if leaders and alive():
            # Compare leaders on common birth seeds. Prefer covered families, then
            # the weakest paired result; the identity breaks equal ranks stably.
            by_family = {}
            for t in leaders:
                by_family.setdefault(t.family[0], []).append(t)
            priorities = [priority]
            if raw.get("objective", "legacy") in ("overall_pve", "pareto", "legacy"):
                priorities += [lambda t: max(r["checkpoints"][0]["dps"] for r in t.witnesses.values()),
                               lambda t: t.peak]
            centers = {}
            for rank in priorities:
                group = max(by_family.values(), key=lambda rows: (len(rows), min(map(rank, rows))))
                centers[group[0].family[0]] = group[0].family
            for family in centers.values():
                if not alive():
                    break
                allowance = (budget - counters["nodes"]) // (8 * len(centers)) if budget else 0
                expand(lambda: admission.neighbors(family, allowance), "neighbor_probe")

        iteration = 0
        while alive() and not admission.full_coverage() and trials and all(
                t.visited and "node_limit" not in t.stopping_reasons for t in trials):
            # Grow only while measured paired evaluations fit the remaining
            # work. A fresh seed opens the full trait and skill domain again.
            iteration += 1
            remaining = budget - counters["nodes"]
            per_pair = max(1, (counters["nodes"] - admission.nodes) // len(trials))
            capacity = min(10000-len(trials)//len(rolls), remaining // (per_pair * len(rolls)) if budget else 10000)
            if deadline and not budget:
                # A finite work budget fixes panel capacity. The wall clock can
                # still stop the run, without changing decisions before the limit.
                mean_seconds = (perf_counter()-started) / len(trials)
                capacity = min(capacity, int((deadline-perf_counter()) / max(1e-9, mean_seconds * len(rolls))))
            if capacity < 1 or budget and remaining < 8:
                break
            added = expand(lambda: admission.widen(remaining // 8 if budget else 0, capacity, iteration), "widen_probe")
            if not added and (iteration > 1 or admission.runs[-1].get("phase") != "exact_completion"):
                break

    # Refine leaders first, with a reserved share for every unfinished pair.
    # A fresh deeper run spends its whole allocation, including repeated work.
    # Revisit only when enough budget remains to improve the previous limit.
    while not any(reason in stops for reason in ("cancelled", "time_limit")):
        pending = sorted((t for t in trials if "node_limit" in t.stopping_reasons), key=priority, reverse=True)
        if not pending:
            break
        progressed = False
        priority_count = max(1, len(pending) // 4) if adaptive else 0
        for i, trial in enumerate(pending):
            remaining = budget - counters["nodes"]
            remaining_weight = len(pending) - i + max(0, priority_count - i)
            weight = 2 if i < priority_count else 1
            allocation = remaining * weight // remaining_weight
            if allocation <= trial.last_limit:
                continue
            if not visit(trial, allocation, "refine"):
                break
            progressed = True
        if not progressed:
            break

    for trial in trials:
        stops.extend(trial.stopping_reasons)
    if admission is not None:
        if admission.full_coverage():
            stops = [reason for reason in stops if reason != "class_limit"]
        else:
            stops.extend(r["termination"] for r in admission.runs
                         if r["termination"] in ("time_limit", "node_limit", "memory_limit", "cancelled", "admission_capacity"))
    plan = finish(stops)
    label = ("Pilot and paired probes, local attribute search around the strongest covered family, "
             "then double refinement shares for the leading unfinished quarter." if adaptive
             else "equal probes then deeper paired searches")
    plan["refinement"] = {"strategy": label, "trials": history}
    return plan
