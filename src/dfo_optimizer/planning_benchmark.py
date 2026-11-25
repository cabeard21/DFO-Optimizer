"""Frozen end-to-end progression and lifecycle workloads, with independently replayed outputs."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from .benchmark_host import engine, host, measure, peak_rss_bytes, summarize
from .native import require_native
from .project_data import shared_data
from .ruleset import load_ruleset


def _compare(exact, bounded):
    a, b = {tuple(row) for row in exact}, {tuple(row) for row in bounded}
    recovered = len(a & b)
    return {"exact_points": len(a), "bounded_points": len(b), "exact_points_recovered": recovered,
            "frontier_recall": recovered / len(a) if a else None}


def _points(suite, result):
    points = set()
    for row in result["routes" if suite == "progression" else "candidates"]:
        effort = row["effort"]
        values = tuple(effort[k] for k in ("practice", "rest_passes", "minutes"))
        if suite == "lifecycle":
            values = (row["roll_seed"], *(s["dps"] for s in row["checkpoints"]), *values, row["total_spent_gold"])
        else:
            values = (*values, effort["spent"])
        points.add(values)
    return sorted(points)


def _workload(suite, request, directory, samples):
    if suite == "progression":
        from .progression import plan_progression as service
        command = ["progression", "plan"]
        first_key = "first_replayed_seconds"
    else:
        from .lifecycle import optimize_build as service
        command = ["build", "optimize"]
        first_key = "first_validated_seconds"
    start = perf_counter()
    proc = subprocess.run([sys.executable, "-I", "-m", "dfo_optimizer.cli", *command, "--request", "-"],
                          cwd=directory, text=True, capture_output=True, input=json.dumps(request), timeout=300)
    cold = perf_counter() - start
    if proc.returncode:
        raise RuntimeError(f"Installed {suite} benchmark failed: {proc.stderr[:1000]}")
    initial = json.loads(proc.stdout)
    timings = []
    first_replay = []
    for _ in range(samples):
        result, timing = measure(lambda: service(request, base_dir=directory))
        if result["result_hash"] != initial["result_hash"]:
            raise RuntimeError(f"Installed and warm {suite} results differ for the frozen request")
        timings.append(timing)
        if result["timings"][first_key] is not None:
            first_replay.append({"wall_seconds": result["timings"][first_key]})
    counters = {k: v for k, v in result["counters"].items() if "second" not in k}
    warm = summarize(timings)
    finalists = result["routes"] if suite == "progression" else result["candidates"]
    levels = {p["state"]["level"] if suite == "progression" else p["final_level"] for p in finalists}
    return {
        "request": request, "request_hash": result["input_hash"], "result_sha256": result["result_hash"],
        "status": result["status"], "termination": result["termination"], "counters": counters,
        "frontier": _points(suite, result), "final_levels": sorted(levels), "validation": result["validation"],
        "cold_cli_seconds": cold, "warm": warm,
        "nodes_per_wall_second_p50": counters["nodes"] / warm["p50_seconds"],
        "evaluations_per_wall_second_p50": counters.get("evaluations", 0) / warm["p50_seconds"] if "evaluations" in counters else None,
        "first_replayed_seconds": result["timings"][first_key],
        "first_replayed_distribution": summarize(first_replay) if first_replay else None,
        "peak_rss_bytes_after_workload": peak_rss_bytes(),
    }


def run_planning_benchmark(suite, *, samples=5):
    from . import _lifecycle, _progression, _spellbook
    if suite not in ("progression", "lifecycle") or type(samples) is not int or not 1 <= samples <= 100:
        raise ValueError("Choose progression or lifecycle and 1 to 100 samples.")
    directory = shared_data("examples")
    if suite == "progression":
        reduced, representative, budget = "progression-tradeoffs", "progression-creation-to-cap", 3
        modules = (_progression,)
    else:
        reduced, representative, budget = "build-lifecycle", "build-creation-to-cap", 500
        modules = (_progression, _spellbook, _lifecycle)
    def load(name):
        return json.loads((directory / (name + ".json")).read_text(encoding="utf-8"))
    request = load(reduced)
    full = {**request, "search": {**request.get("search", {}), "max_nodes": 0, "wall_seconds": 0}}
    limited = {**full, "search": {**full["search"], "max_nodes": budget}}
    exact = _workload(suite, full, directory, samples)
    if exact["status"] != "optimal_proven" or not exact["frontier"]:
        raise RuntimeError(f"Reduced {suite} benchmark did not prove a nonempty frontier: {exact['status']}")
    bounded = _workload(suite, limited, directory, samples)
    if bounded["status"] == "optimal_proven":
        raise RuntimeError(f"Reduced {suite} budget should truncate the exact search")
    bounded["quality"] = _compare(exact["frontier"], bounded["frontier"])
    workloads = {"reduced_exact": exact, "reduced_bounded": bounded,
                 "representative": _workload(suite, load(representative), directory, samples)}
    if 45 not in workloads["representative"]["final_levels"]:
        raise RuntimeError(f"Representative {suite} benchmark produced no replayed level-45 route")
    bundle = load_ruleset()
    return {"schema_version": 1, "workload_version": 1, "suite": suite, "workers": 1,
            "host": host(), "engine": engine(require_native()), "extensions": {
                m.__name__: sha256(Path(m.__file__).read_bytes()).hexdigest() for m in modules},
            "source_sha": bundle["source_sha"], "ruleset_hash": bundle["content_hash"],
            "workloads": workloads, "peak_rss_bytes": peak_rss_bytes()}
