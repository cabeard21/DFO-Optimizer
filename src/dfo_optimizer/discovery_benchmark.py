"""Frozen downstream admission checks, independent of native screening features."""

import json
from math import isclose
from statistics import mean
import subprocess
import sys
from time import perf_counter

from .benchmark_host import engine, host, peak_rss_bytes
from .lifecycle import optimize_build, replay_build
from .lifecycle_objectives import ranking_coordinates
from .native import require_native
from .progression import digest
from .ruleset import DATA
from .search import optimize_classes


def _equivalent(a, b):
    return len(a) == len(b) and all(
        x == y if type(x) is int and type(y) is int else isclose(x, y, rel_tol=1e-9, abs_tol=1e-12)
        for x, y in zip(a, b, strict=True)
    )


def compare_points(exact, found):
    exact, found = [tuple(v) for v in exact], [tuple(v) for v in found]
    if not exact:
        raise ValueError("admission qualification requires a feasible exhaustive reference")
    distinct = []
    for point in exact:
        if not any(_equivalent(point, earlier) for earlier in distinct):
            distinct.append(point)
    hits = sum(any(_equivalent(point, candidate) for candidate in found) for point in distinct)
    result = {
        "recall": hits / len(distinct),
        "exact_points": distinct,
        "found_points": sorted(set(found)),
    }
    if len(distinct[0]) == 1:
        best = max(p[0] for p in distinct)
        retained = max((p[0] for p in found), default=None)
        hit = retained is not None and _equivalent((best,), (retained,))
        if retained is not None and retained > best and not hit:
            raise RuntimeError("bounded result exceeds its exhaustive reference")
        result.update(
            scalar_success=hit,
            regret=0.0 if hit else ((best - retained) / abs(best) if best and retained is not None else None),
        )
    return result


def qualification(rows):
    scalars = [r for r in rows if "scalar_success" in r and not r.get("reference")]
    refs = [r for r in rows if r.get("reference")]
    pareto = [r for r in rows if "scalar_success" not in r and not r.get("reference")]
    regrets = [r["regret"] for r in scalars]
    measurable = bool(regrets) and None not in regrets
    result = {
        "designated_recovery": mean(r["recall"] for r in refs) if refs else None,
        "scalar_recovery": mean(int(r["scalar_success"]) for r in scalars) if scalars else None,
        "mean_regret": mean(regrets) if measurable else None,
        "worst_regret": max(regrets) if measurable else None,
        "pareto_recall": mean(r["recall"] for r in pareto) if pareto else None,
    }
    gates = {
        "designated_recovery": 1.0,
        "scalar_recovery": 0.95,
        "mean_regret": 0.005,
        "worst_regret": 0.02,
        "pareto_recall": 0.9,
    }
    result["targets"] = gates
    result["passed"] = all(
        result[k] is not None and (result[k] <= target if k.endswith("regret") else result[k] >= target)
        for k, target in gates.items()
    )
    return result


def frozen_panel(panel):
    """Keep exact comparison opportunities independent of future UI preset updates."""
    payload = json.loads((DATA / "discovery-qualification-v1.json").read_text(encoding="utf8"))
    if digest(payload) != "cc1a6bfacd1facc807a1850d2eb0dbef3edc8dfe791e66337321e3281c200362":
        raise ValueError("discovery qualification inputs differ from their versioned contents")
    return payload["panels"][panel]


def paired_points(result):
    frontier = result.get("paired_family_frontier", {})
    witnesses = [*result["candidates"], *result["comparison_witnesses"]]
    checkpoint = "stage" if "checkpoints" in result["frozen_request"] else "level"
    groups = {}
    for p in frontier.get("points", ()):
        panels = [[s[checkpoint] for s in witnesses[r["witness_index"]]["checkpoints"]] for r in p["rolls"]]
        axes = p.get("axes", frontier["axes"])
        key = json.dumps([axes, panels], separators=(",", ":"))
        # All reported means are nonnegative. -1 denotes an undefined outcome
        # for this equality check and is never used to rank funded performance.
        groups.setdefault(key, []).append([p["means"][k] if p["means"][k] is not None else -1 for k in axes])
    return groups


def compare_paired(exact, candidate):
    if exact.get("paired_optimum"):
        return compare_points(exact["paired_optimum"], candidate["paired_optimum"])
    groups = {
        k: compare_points(points, candidate["paired_frontiers"].get(k, []))
        for k, points in exact["paired_frontiers"].items()
    }
    total = sum(len(row["exact_points"]) for row in groups.values())
    if not total:
        raise ValueError("no feasible paired-family qualification reference")
    hits = sum(round(row["recall"] * len(row["exact_points"])) for row in groups.values())
    return {"recall": hits / total, "matched": hits, "total": total, "panels": groups}


def gate_both(rows, paired):
    per_roll, prebirth = qualification(rows), qualification(paired)
    return {
        **per_roll,
        "per_roll_passed": per_roll["passed"],
        "paired_family": prebirth,
        "passed": per_roll["passed"] and prebirth["passed"],
    }


def _trial(query):
    start = perf_counter()
    result = optimize_build(query)
    elapsed = perf_counter() - start
    replay_build(result)
    report = {
        k: result[k]
        for k in (
            "status",
            "termination",
            "input_hash",
            "result_hash",
            "class_admission",
            "counters",
            "timings",
        )
    }
    count = result["class_admission"]["evaluated"]
    best = {}
    observations = []
    for trial in result["refinement"]["trials"]:
        score, seed = trial.get("priority"), trial["roll_seed"]
        if score and (seed not in best or score > best[seed]):
            best[seed] = score
            observations.append({k: trial[k] for k in ("elapsed_seconds", "roll_seed", "family", "priority")})
    report.update(
        elapsed_seconds=elapsed,
        process_peak_rss_bytes=peak_rss_bytes(),
        best_replayed_priority_by_elapsed_time=observations,
        service_seconds_per_evaluated_family=elapsed / count if count else None,
    )
    values = [row["mean_score"] for row in result["family_comparisons"] if row.get("mean_score") is not None]
    points = {
        str(seed): [
            ranking_coordinates(r, query["objective"]) for r in result["candidates"] if r["roll_seed"] == seed
        ]
        for seed in query["roll_seeds"]
    }
    return {
        "paired_optimum": [(max(values),)] if values else [],
        "paired_frontiers": paired_points(result),
        "points": points,
        "report": report,
        "exact": result["exact"],
        "stopping_reasons": result["stopping_reasons"],
    }


def _isolated_trial(query):
    # RSS high-water marks from two searches in the same process cannot be compared.
    child = subprocess.run(
        [sys.executable, "-m", "dfo_optimizer.discovery_benchmark"],
        input=json.dumps(query),
        capture_output=True,
        text=True,
        check=False,
    )
    if child.returncode:
        raise RuntimeError(f"discovery qualification failed: {child.stderr[-1800:]}")
    return json.loads(child.stdout)


def run_discovery_benchmark(*, panel="qualify"):
    binary = engine(require_native())
    broad = {"profile": "spellcaster_discovery_v1", "max_nodes": 250_000, "top_k": 32}
    start = perf_counter()
    classes = optimize_classes(broad)
    elapsed = perf_counter() - start
    c = classes["counters"]
    samples, screened_samples, short_samples, workloads = [], [], [], {}
    paired = {"adaptive": [], "screen_only": [], "adaptive_3000_nodes": []}
    for case in frozen_panel(panel):
        name, q = case["name"], case["request"]
        objective, seeds = q["objective"], q["roll_seeds"]
        exact_q = {
            **q,
            "class_admission_strategy": "exhaustive",
            "class_search": {**q["class_search"], "top_k": 1000},
            "search": {**q["search"], "exact": True, "max_nodes": 0, "wall_seconds": 0},
        }
        exact = _isolated_trial(exact_q)
        if not exact["exact"]:
            raise RuntimeError(
                f"incomplete exhaustive qualification case {name}: {exact['stopping_reasons']}"
            )
        bounded = _isolated_trial(q)
        screened = _isolated_trial({**q, "class_admission_strategy": "diverse"})
        # The default may afford every reduced family. Measure the same adaptive
        # strategy under a binding work ceiling as a separate sensitivity case.
        short = _isolated_trial({**q, "search": {**q["search"], "max_nodes": 3000}})
        complete, limited = exact["report"], bounded["report"]
        checks = []
        panel_checks = []
        short_checks = []
        for seed in seeds:
            points = [[tuple(v) for v in plan["points"][str(seed)]] for plan in (exact, bounded, screened)]
            check = {
                **compare_points(points[0], points[1]),
                "reference": case["designated_reference"],
                "roll_seed": seed,
            }
            checks.append(check)
            panel_checks.append(
                {
                    **compare_points(points[0], points[2]),
                    "reference": check["reference"],
                    "roll_seed": seed,
                }
            )
            short_checks.append(
                {
                    **compare_points(points[0], short["points"][str(seed)]),
                    "reference": check["reference"],
                    "roll_seed": seed,
                }
            )
        for mode, trial in (("adaptive", bounded), ("screen_only", screened), ("adaptive_3000_nodes", short)):
            paired[mode].append(
                {
                    **compare_paired(exact, trial),
                    "case": name,
                    "objective": objective,
                    "reference": case["designated_reference"],
                }
            )
        samples.extend(checks)
        screened_samples.extend(panel_checks)
        short_samples.extend(short_checks)
        ratios = {
            label: limited[k] / complete[k] if complete[k] else None
            for label, k in (
                ("runtime", "elapsed_seconds"),
                ("peak_rss_running_process", "process_peak_rss_bytes"),
            )
        }
        for label, k in (
            ("native_work_bytes", "work_bytes"),
            ("evaluations", "evaluations"),
            ("nodes", "nodes"),
        ):
            ratios[label] = (
                limited["counters"][k] / complete["counters"][k] if complete["counters"][k] else None
            )
        workloads[f"{name}/{objective}"] = {
            "request": q,
            "exhaustive": complete,
            "adaptive": limited,
            "screen_only": screened["report"],
            "adaptive_relative_to_exact": ratios,
            "quality": checks,
            "screen_only_quality": panel_checks,
            "adaptive_3000_nodes": short["report"],
            "adaptive_3000_nodes_quality": short_checks,
        }
    return {
        "schema_version": 1,
        "workload_version": 1,
        "suite": "discovery",
        "panel": panel,
        "workers": 1,
        "ruleset_hash": classes["ruleset_hash"],
        "source_sha": classes["source_sha"],
        "host": host(),
        "engine": binary,
        "input_panel_hash": digest([case["request"] for case in workloads.values()]),
        "broad_class": {
            "request": broad,
            "elapsed_seconds": elapsed,
            "native_counters": c,
            "class_nodes_per_second": c["nodes"] / elapsed,
            "screened_per_second": c["unique_screened"] / elapsed,
            "result_hash": classes["result_hash"],
            "admitted": len(classes["candidates"]),
        },
        "workloads": workloads,
        "quality": gate_both(samples, paired["adaptive"]),
        "screen_only_quality": gate_both(screened_samples, paired["screen_only"]),
        "adaptive_3000_nodes_quality": gate_both(short_samples, paired["adaptive_3000_nodes"]),
        "paired_family_quality": paired,
        "peak_rss_bytes": peak_rss_bytes(),
    }


if __name__ == "__main__":
    json.dump(_trial(json.load(sys.stdin)), sys.stdout, allow_nan=False)
