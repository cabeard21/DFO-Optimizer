"""Reproducible single-worker measurements of direct spell and joint equipment search."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from .benchmark_host import engine, host, measure, peak_rss_bytes, summarize


def _area(points):
    """Area dominated relative to zero DPS and zero HP/SP. Supports partial frontiers."""
    height = area = 0.
    ordered = sorted(points, reverse=True)
    for (x, y), (next_x, _) in zip(ordered, [*ordered[1:], (0., 0.)]):
        height = max(height, y)
        area += (x - next_x) * height
    return area


def compare_fronts(exact, bounded):
    exact_area = _area(exact)
    peak_dps = max((x for x, _ in exact), default=0.)
    overlap = len(exact & bounded)
    return {
        "exact_points": len(exact), "bounded_points": len(bounded),
        "exact_points_recovered": overlap,
        "frontier_recall": overlap / len(exact) if exact else None,
        "dominated_area_fraction": _area(bounded) / exact_area if exact_area else None,
        "peak_dps_fraction": max((x for x, _ in bounded), default=0.) / peak_dps if peak_dps else None,
    }


def _inputs():
    state = {
        "caster": {"level": 10, "speed": 65, "destruction_live": 75, "destruction_trained": 75,
                   "destruction_mastered": False, "current_sp": 80, "max_sp": 100,
                   "gold": 500, "has_spellbook": True},
        "target": {"id": "synthetic_fire_resistant_foe", "hp": 60, "willpower": 50, "resistant": 8},
    }
    recipe = {"effect_id": "4,0", "element": 1, "range_type": 1, "base_low": 2,
              "base_high": 6, "plus_low": 3, "plus_high": 5, "per_level": 2}
    domain = {"effect_id": "4,0", "element": [0, 1, 4], "range_type": [1, 2],
              "base_low": [1, 3, 5], "base_high": [2, 4, 6], "plus_low": [1, 3, 5],
              "plus_high": [2, 4, 6], "per_level": [1, 2, 5]}
    return state, recipe, domain


def _inventory(n):
    # Synthetic observed copies with the actual template, affix and roll encodings.
    rows = []
    lines = [("focus", 3), ("potency", 5), ("castSpeed", 5)]
    for i in range(n):
        kind, value = lines[i % len(lines)]
        rows.append({"instance_id": f"bench-{i:03d}", "container": "pack", "acquisition": {"owned": True},
                     "item": {"group": "Jewellery", "templateIndex": 135 + (i // 6) % 3, "rarity": "magic",
                              "currentCondition": 10, "affixes": [{"id": "skill", "param": 22, "value": 5 + i % 6},
                                                                  {"id": kind, "value": value}]}})
    return rows


def _cold(command, request):
    start = perf_counter()
    process = subprocess.run([sys.executable, "-I", "-m", "dfo_optimizer.cli", *command, "--request", "-"],
                             input=json.dumps(request), text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError(f"Cold combat benchmark failed: {process.stderr[:500]}")
    return json.loads(process.stdout), perf_counter() - start


def _workload(service, command, request):
    first, cold = _cold(command, request)
    if not first["candidates"] or first["status"] not in {"evaluated", "optimal_proven", "best_found_bounded"}:
        raise RuntimeError(f"Combat benchmark produced no feasible candidates: {first['status']}")
    timings = []
    for _ in range(7):
        replay, timing = measure(lambda: service(request))
        if replay["result_hash"] != first["result_hash"]:
            raise RuntimeError("The installed CLI and warm service returned different results")
        timings.append(timing)
    points = {(c["metrics"]["dps"], c["metrics"]["damage_per_sp"]) for c in first["candidates"]}
    return {
        "request": request, "request_hash": first["input_hash"], "result_sha256": first["result_hash"],
        "status": first["status"], "termination": first["termination"], "counters": first["counters"],
        "frontier": sorted(points), "cold_cli_seconds": cold, "warm": summarize(timings),
        "peak_rss_bytes_after_workload": peak_rss_bytes(),
    }


def _simple_batch():
    from . import _spells
    from .spell_reference import evaluate_reference
    context = {"level": 10, "live_skill": 75, "climb": 75, "speed": 65, "available_sp": 80, "target_hp": 60,
               "willpower": 50, "power_pct": 0, "pierce": 0, "cast_speed_pct": 0, "focus_pct": 0,
               "resistant": 8, "immune": 0, "low_tolerance": 0, "critical_weakness": 0,
               "resist_mods": [0] * 5, "elemental_resists": [0] * 5, "price_factor": 1.}
    recipes = [(i % 5, 1 + i % 4, i, i, i, i, 1 + i % 7) for i in range(1, 33)]
    checks = [evaluate_reference(context, r) for r in recipes]
    repeats = 2048
    expected = repeats * sum(row["health_loss_sum"] + row["cost_sp"] for row in checks)
    samples = []
    for _ in range(7):
        out, sample = measure(lambda: _spells.benchmark_rows(context, recipes, repeats))
        if out["checksum"] != expected or out["rows"] != repeats * len(recipes):
            raise RuntimeError("Native direct-effect batch disagreed with independent scalar arithmetic")
        samples.append({**sample, "kernel_seconds": out["seconds"]})
    warm = summarize(samples)
    return {"rows": repeats * len(recipes), "checksum": expected, "context": context, "recipes": recipes,
            "warm": warm, "evaluations_per_second": out["rows"] / warm["p50_seconds"]}


def run_combat_benchmark():
    from . import _gear, _spells, gear, spells
    from .native import require_native
    from .ruleset import load_ruleset

    state, recipe, domain = _inputs()
    gear_input = {**state, "career": {}, "mode": "owned_only", "marginals": False}
    search = {"max_nodes": 0, "wall_seconds": 0}
    small = {**gear_input, "inventory": _inventory(4), "domain": domain}
    workloads = {"simple_batch": _simple_batch()}
    workloads["fixed_spell"] = _workload(spells.evaluate_spell, ["evaluate"], {**state, "spell": recipe})
    for key, service, command, request, budget in (
        ("spell", spells.optimize_spells, ["spell", "optimize"], {**state, "domain": domain}, 128),
        ("gear", gear.optimize_gear, ["gear", "optimize"], small, 700),
    ):
        exact_limits = {**search, "exact": True} if key == "gear" else search
        exact = _workload(service, command, {**request, "search": exact_limits})
        bounded = _workload(service, command, {**request, "search": {**search, "max_nodes": budget}})
        if exact["status"] != "optimal_proven":
            raise RuntimeError(f"Reduced {key} benchmark did not exhaust its declared space")
        bounded["quality"] = compare_fronts(set(exact["frontier"]), set(bounded["frontier"]))
        workloads[f"{key}_exact"] = exact
        workloads[f"{key}_bounded"] = bounded
    workloads["spell_full_budget"] = _workload(spells.optimize_spells, ["spell", "optimize"],
                                                {**state, "search": {**search, "max_nodes": 100_000}})
    workloads["gear_owned"] = _workload(gear.optimize_gear, ["gear", "optimize"], {
        **gear_input, "marginals": True, "spell": recipe, "inventory": _inventory(36),
        "search": {**search, "max_nodes": 60_000}})
    workloads["joint_budget"] = _workload(gear.optimize_gear, ["gear", "optimize"], {
        **gear_input, "domain": domain, "inventory": _inventory(36),
        "search": {**search, "max_nodes": 75_000, "max_spells_per_loadout": 128}})
    bundle = load_ruleset()
    return {"schema_version": 1, "workload_version": 1, "suite": "combat", "workers": 1,
            "host": host(), "engine": engine(require_native()), "extensions": {
                mod.__name__: sha256(Path(mod.__file__).read_bytes()).hexdigest() for mod in (_gear, _spells)},
            "source_sha": bundle["source_sha"], "ruleset_hash": bundle["content_hash"],
            "workloads": workloads, "peak_rss_bytes": peak_rss_bytes()}
