"""Serial benchmark for the pinned class rules. Timings and work totals are separate."""

from array import array
from hashlib import sha256
import json
import subprocess
import sys
from time import perf_counter

from .benchmark_host import engine, host, measure, peak_rss_bytes, summarize


def _batch_digest(result):
    digest = sha256()
    for field in ("points", "advancement"):
        values = result[field]
        if sys.byteorder == "big":
            values = array(values.typecode, values)
            values.byteswap()
        digest.update(values.tobytes())
    return digest.hexdigest()


def _mechanics(native, repeats):
    # Each input has a different HP branch, signed cost and/or rounding outcome.
    patterns = [(4, 2, -6, -12), (8, 6, -4, 2), (30, 10, -44, -12), (26, 22, 0, 40)]
    copies = 16_384
    hp, advantages, disadvantages = (array("i", (row[i] for row in patterns)) * copies for i in range(3))
    expected = array("i", (row[3] for row in patterns)) * copies
    advance = array("d", (0.3 + (2.7 * (p + 12)) / 52 for p in expected))

    def evaluate():
        return native.evaluate_batch(hp, advantages, disadvantages)

    def check(result):
        if result["rows"] != len(expected) or result["points"] != expected or result["advancement"] != advance:
            raise RuntimeError("Native mechanics workload failed its independent point or advancement check.")

    result, cold = measure(evaluate)
    check(result)
    samples = []
    for _ in range(repeats):
        result, timing = measure(evaluate)
        check(result)
        samples.append(timing)
    warm = summarize(samples)
    return {
        "rows": len(expected), "verified": True, "input_patterns": patterns, "copies": copies,
        "cold": cold, "cold_scope": "first batch call in this process", "warm": warm,
        "evaluations_per_second": len(expected) / warm["p50_seconds"],
        "result_sha256": _batch_digest(result),
    }


def _exact_request(bundle):
    by_name = {(t["primary"], t["secondary"]): t["id"] for t in bundle["traits"]}
    materials = ("steel", "elven", "dwarven", "mithril", "silver", "adamantium", "ebony", "iron")
    traits = [by_name["increasedMagery", "intInSpellPoints3"]]
    traits.extend(by_name["forbiddenMaterial", material] for material in materials)
    return {
        "race_ids": [1, 2], "hp_values": [30], "trait_ids": traits,
        "exact": True, "objective": "examples", "top_k": 10,
    }


def _verify_exact(result):
    common = {"steel", "elven", "dwarven", "mithril", "silver", "iron"}
    expected = {(race, frozenset(common | {other})) for race in (1, 2) for other in ("adamantium", "ebony")}
    obtained = {
        (item["race_id"], frozenset(v["secondary"] for v in item["class_doc"]["disadvantages"]))
        for item in result["candidates"]
    }
    if result["status"] != "optimal_proven" or obtained != expected or len(result["candidates"]) != 4:
        raise RuntimeError("Reduced search failed its independent four-class exact result check.")


def _cold_cli(request):
    # Run the normal installed entry point in a fresh interpreter. OS file caches may be warm.
    start = perf_counter()
    process = subprocess.run(
        [sys.executable, "-I", "-m", "dfo_optimizer.cli", "class", "optimize", "--request", "-"],
        input=json.dumps(request), text=True, capture_output=True, check=False,
    )
    wall = perf_counter() - start
    if process.returncode:
        raise RuntimeError(f"Cold installed CLI failed ({process.returncode}): {process.stderr.strip()}")
    return json.loads(process.stdout), {"wall_seconds": wall}


def _search(bundle, request, repeats, *, exact):
    from .search import optimize_classes

    first, cold = _cold_cli(request)
    if exact:
        _verify_exact(first)
    candidates = first["candidates"]
    if not candidates or any(c["difficulty_points"] != -12 or c["advancement_multiplier"] != 0.3 for c in candidates):
        raise RuntimeError("Class benchmark requires a returned example at the difficulty floor.")
    fields = ("nodes", "leaves", "pruned", "work_bytes")
    work = {k: first["counters"][k] for k in fields}
    samples = []
    for _ in range(repeats):
        result, sample = measure(lambda: optimize_classes(request, ruleset=bundle))
        if result["result_hash"] != first["result_hash"] or work != {k: result["counters"][k] for k in fields}:
            raise RuntimeError("Installed CLI and warm service disagreed on results or deterministic work.")
        samples.append(sample)
    return {
        **work, "request": request, "request_hash": first["input_hash"], "result_sha256": first["result_hash"],
        "eligible_trait_count": len(first["proof_scope"]["eligible_trait_ids"]),
        "status": first["status"], "termination": first["termination"], "returned": len(candidates),
        "verified": True, "quality": "All four expected classes" if exact else "Feasible examples at the locked floor",
        "first_feasible_seconds": first["counters"]["first_feasible_seconds"],
        "cold_scope": "fresh installed CLI process including startup and JSON output", "cold": cold,
        "warm": summarize(samples),
    }


def run_benchmark(suite="smoke"):
    from .native import require_native
    from .ruleset import load_ruleset

    if suite not in ("foundation", "smoke"):
        raise ValueError("Choose the foundation or smoke benchmark suite.")
    native = require_native()
    bundle = load_ruleset()
    repeats = 7
    workloads = {"mechanics_batch": _mechanics(native, repeats)}
    if suite == "smoke":
        workloads["class_exact"] = _search(bundle, _exact_request(bundle), repeats, exact=True)
        workloads["class_bounded"] = _search(bundle, {"top_k": 20, "max_nodes": 100_000}, repeats, exact=False)
    return {
        "schema_version": 1, "workload_version": 1, "suite": suite, "workers": 1,
        "host": host(), "engine": engine(native), "source_sha": bundle["source_sha"],
        "ruleset_hash": bundle["content_hash"], "catalog": {k: len(bundle[k]) for k in ("traits", "races", "skills")},
        "repeats": repeats, "seed": None, "workloads": workloads, "peak_rss_bytes": peak_rss_bytes(),
        "rss_scope": "peak resident bytes of the benchmark process over all workloads",
    }
