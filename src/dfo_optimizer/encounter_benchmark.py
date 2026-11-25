"""Time complete native encounter policy searches and independently replayed results."""
from hashlib import sha256
from importlib.machinery import EXTENSION_SUFFIXES
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from .benchmark_host import host, measure, peak_rss_bytes, summarize
from .encounter import evaluate_encounter, optimize_encounter, replay_encounter
from .planning_benchmark import _compare
from .project_data import shared_data


def _frontier(rows):
    axes = ("cleared_trials", "dead_trials", "kills_per_minute", "mean_damage",
            "mean_sp_spent", "censored_mean_clear_us")
    return sorted({tuple(row["metrics"][key] for key in axes) for row in rows})


def _workload(request, fixed, samples):
    action, service = ("evaluate", evaluate_encounter) if fixed else ("optimize", optimize_encounter)
    start = perf_counter()
    proc = subprocess.run([sys.executable, "-I", "-m", "dfo_optimizer.cli", "encounter", action, "--request", "-"],
                          input=json.dumps(request), capture_output=True, text=True, timeout=180)
    cold = perf_counter() - start
    if proc.returncode:
        raise RuntimeError(f"Installed encounter benchmark failed: {proc.stderr[:1000]}")
    first = json.loads(proc.stdout)
    checked = replay_encounter(first)
    warm = []
    kernel = []
    for _ in range(samples):
        result, sample = measure(lambda: service(request))
        if result["result_hash"] != first["result_hash"] or result["counters"] != first["counters"]:
            raise RuntimeError("Encounter result or deterministic work changed between samples")
        warm.append(sample)
        kernel.append({"wall_seconds": result["timings"]["native_seconds"]})
    if not checked["valid"] or not checked["policies_checked"] or not first["counters"]["events"]:
        raise RuntimeError("Encounter workload requires checked native work")
    times = summarize(warm)
    native_times = summarize(kernel)
    return {
        "input_hash": first["input_hash"], "ruleset_hash": first["ruleset_hash"], "source_sha": first["source_sha"],
        "result_hash": first["result_hash"], "status": first["status"], "termination": first["termination"],
        "frontier": _frontier(first["frontier"]), "policies_checked": checked["policies_checked"],
        "seeds": first["seed_scope"]["seeds"], "counters": first["counters"], "cold_cli_seconds": cold,
        "warm": times, "native": native_times, "first_replayed_seconds": first["timings"]["first_replayed_seconds"],
        "events_per_second": first["counters"]["events"] / times["p50_seconds"],
        "native_events_per_second": first["counters"]["events"] / native_times["p50_seconds"],
        "peak_rss_bytes": peak_rss_bytes(),
    }


def run_encounter_benchmark(*, samples=5):
    from . import _encounter
    if type(samples) is not int or not 1 <= samples <= 100:
        raise ValueError("Encounter benchmark needs 1 to 100 warm samples.")
    binary = Path(_encounter.__file__)
    if not binary.name.endswith(tuple(EXTENSION_SUFFIXES)):
        raise RuntimeError("Install a native wheel before running this benchmark.")
    workloads = {}
    for key in ("miss", "pack", "dungeon"):
        path = shared_data("examples") / f"encounter-{key}.json"
        request = json.loads(path.read_text(encoding="utf8"))
        workloads[key] = _workload(request, key == "miss", samples)
        if key == "pack":
            if len(request["policies"]) < 2:
                raise RuntimeError("Pack benchmark requires multiple competing policies")
            bounded = {**request, "search": {**request.get("search", {}), "max_policies": 1}}
            workloads["pack_bounded"] = _workload(bounded, False, samples)
            workloads["pack_bounded"]["quality"] = _compare(workloads[key]["frontier"],
                                                            workloads["pack_bounded"]["frontier"])
    return {"suite": "encounter", "schema_version": 1, "workload_version": 1, "workers": 1, "host": host(),
            "extension_sha256": sha256(binary.read_bytes()).hexdigest(), "workloads": workloads,
            "peak_rss_bytes": peak_rss_bytes()}
