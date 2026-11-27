"""Fixed finalist, checkpoint and combat-draw comparisons for the beginner guide."""

import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from math import isfinite
from time import perf_counter

from .beginner_scenario_catalog import (
    CASE_IDS,
    VARIANT_CASES,
    VARIANTS,
    scenario_matrix,
)
from .beginner_scenario_trials import (
    Budget,
    PanelLimit,
    ScenarioGap,
    make_request,
    prepare_low_sp,
)
from .encounter import _digest
from .progression_domain import integer, require
from .ruleset import load_ruleset, validate_encounter_ruleset

__all__ = [
    "CASE_IDS",
    "VARIANTS",
    "evaluate_matrix",
    "evaluate_panel",
    "scenario_matrix",
    "verify_matrix",
]


def _panel_digest(prefix, suffix=()):
    """Canonical list encoding, one checkpoint or outcome at a time."""
    nested = bool(suffix)
    digest = sha256(b"[[" if nested else b"[")
    for i, item in enumerate(prefix):
        if i:
            digest.update(b",")
        digest.update(
            json.dumps(
                item, sort_keys=True, allow_nan=False, separators=(",", ":")
            ).encode()
        )
    digest.update(b"]")
    if nested:
        encoder = json.JSONEncoder(sort_keys=True, allow_nan=False, separators=(",", ":"))
        for item in suffix:
            digest.update(b",")
            for chunk in encoder.iterencode(item):
                digest.update(chunk.encode())
        digest.update(b"]")
    return digest.hexdigest()


def _cases(items):
    catalog = {r["id"]: r for r in scenario_matrix()}
    if items is None:
        return list(catalog.values())
    require(
        isinstance(items, (list, tuple)) and 1 <= len(items) <= len(catalog),
        "invalid scenario selection",
    )
    chosen = []
    for item in items:
        if isinstance(item, str):
            require(item in catalog, "unknown scenario")
            chosen.append(catalog[item])
        else:
            require(
                isinstance(item, dict)
                and item.get("id") in catalog
                and "scene" in item,
                "invalid scenario definition",
            )
            chosen.append(deepcopy(item))
    require(len({c["id"] for c in chosen}) == len(chosen), "duplicate scenario")
    return chosen


def _selection(values, choices, label):
    require(
        isinstance(values, (list, tuple)) and 1 <= len(values) <= len(choices),
        f"invalid {label}",
    )
    require(
        all(isinstance(v, str) and v in choices for v in values)
        and len(set(values)) == len(values),
        f"unknown or duplicate {label}",
    )
    return list(values)


def _stage(checkpoint, variant):
    if checkpoint.get("status") in (
        "unavailable",
        "unsupported",
        "unvisited",
        "missing",
    ) or not checkpoint.get("actor"):
        raise ScenarioGap(
            str(
                checkpoint.get("reason")
                or "The progression route has no replayed checkpoint"
            )
        )
    if variant in ("owned_only", "no_spell_purchase"):
        change = checkpoint.get("variants", {}).get(variant)
        if not isinstance(change, dict):
            raise ScenarioGap(f"Missing attained-state acquisition variant {variant}")
        if change.get("status") in ("unsupported", "unavailable"):
            raise ScenarioGap(
                str(change.get("reason") or "Unavailable acquisition policy")
            )
        return {**checkpoint, **change}
    return checkpoint


def _base(stage, case, variant, seed):
    return {k: stage[k] for k in ("family", "roll_seed", "stage", "level")} | {
        "scenario": case["id"],
        "seed": seed,
        "variant": variant,
        "horizon_us": case["scene"]["horizon_us"],
    }


def _report(header, trial, query, preparation, stage):
    trace = trial["trace"]
    policy = query["policies"][0]
    attacks = query["spells"]
    clicks = Counter(attack[3] for attack in trace if attack[1] == "click")
    spell_counts = {attacks[i]["id"]: count for i, count in sorted(clicks.items())}
    paid = {
        key: trial.get(key, 0)
        for key in (
            "melee_swings",
            "melee_hits",
            "incoming_swings",
            "incoming_hits",
            "spent_fatigue",
            "consumables",
            "rest_us",
        )
    }
    return {
        **header,
        "status": "replayed",
        "survived": not trial["dead"],
        "cleared": trial["cleared"],
        "clear_us": trial["end_us"] if trial["cleared"] else None,
        "censored_clear_us": trial["end_us"]
        if trial["cleared"]
        else header["horizon_us"],
        "damage": trial["damage"],
        "spent_sp": trial["spent_sp"],
        "physical_damage": trial.get("melee_damage", 0),
        "initial_sp": trial["initial_sp"],
        "ending_sp": trial["end_sp"],
        "restored_sp": trial["restored_sp"],
        "ending_hp": trial["end_hp"],
        "max_hp": query["actor"]["max_hp"],
        "initial_hp": query["actor"]["hp"],
        "minimum_hp": trial["min_hp"],
        "minimum_sp": trial["min_sp"],
        "casts": trial["casts"],
        "healing": trial["healing"],
        "mitigated": trial["mitigated"],
        "kills": trial["kills"],
        **paid,
        **({"ending_fatigue": trial["end_fatigue"]} if "end_fatigue" in trial else {}),
        "policy_id": _digest(policy["rules"]),
        "spell_uses": spell_counts,
        "loadout": stage.get("loadout", {}),
        "room_entries": [
            {"time_us": e[0], "hp": e[5], "sp": e[6]} for e in trace if e[1] == "room"
        ],
        **({"prelude": preparation} if preparation is not None else {}),
        "trial_hash": _digest({k: v for k, v in trial.items() if k != "trace"}),
        "trace_hash": _digest(trace),
    }


def _batches(checkpoints, cases, variants):
    for index, checkpoint in enumerate(checkpoints):
        for variant in variants:
            for case in cases:
                if case["id"] in VARIANT_CASES[variant]:
                    yield index, checkpoint, variant, case


def _run_batch(
    work, rows, checkpoint, case, variant, seeds, rules_hash, receipts, preparations
):
    heads = [_base(checkpoint, case, variant, seed) for seed in seeds]
    try:
        stage = _stage(checkpoint, variant)
        prep = None
        entry_sp = None
        if case["id"] == "low_sp" and stage.get("refined_entry"):
            entry_sp = min(stage["actor"]["current_sp"], stage["actor"]["max_sp"] // 4)
        elif case["id"] == "low_sp":
            key = _digest([stage["actor"], stage["spells"], stage["career"], seeds[0]])
            if key not in preparations:
                prelude = prepare_low_sp(stage, seeds[0], work)
                work.cache(prelude)
                preparations[key] = prelude
            prep = preparations[key]
        query = make_request(
            stage, case, variant, seeds, prep["ending_sp"] if prep else entry_sp
        )
        query["ruleset_hash"] = rules_hash
        key = _digest([query, prep, stage["loadout"]])
        if key in receipts:
            offset = receipts[key]
            return [{**rows[offset + i], **head} for i, head in enumerate(heads)], 1
        results = work.evaluate(
            query, report=lambda i, trial: _report(heads[i], trial, query, prep, stage)
        )
        work.cache(len(rows))
        receipts[key] = len(rows)
        return results, 0
    except ScenarioGap as exc:
        return [{**h, "status": "unsupported", "reason": str(exc)} for h in heads], 0


def evaluate_matrix(
    checkpoints,
    cases=None,
    seeds=(101, 202),
    *,
    variants=("baseline",),
    max_events=0,
    memory_bytes=64 << 20,
    wall_seconds=0,
    cancel=None,
    ruleset=None,
    _reference_only=False,
    _prefix_rows=None,
):
    """Run the same fixed preparations, policies and combat tapes for every attained family."""
    started = perf_counter()
    require(
        isinstance(checkpoints, (list, tuple)) and 1 <= len(checkpoints) <= 2048,
        "expected 1..2048 checkpoints",
    )
    require(
        isinstance(seeds, (list, tuple)) and 1 <= len(seeds) <= 128,
        "expected 1..128 combat seeds",
    )
    require(
        all(type(s) is int and 0 <= s < 2**32 for s in seeds)
        and len(seeds) == len(set(seeds)),
        "invalid combat seeds",
    )
    require(
        type(wall_seconds) in (int, float)
        and isfinite(wall_seconds)
        and 0 <= wall_seconds <= 86400,
        "invalid wall budget",
    )
    integer(max_events, "event budget", 0, 2**53 - 1)
    integer(memory_bytes, "memory budget", 1, 2**53 - 1)
    if ruleset is None:
        from .encounter_request import _package_rules

        ruleset = _package_rules()
    else:
        validate_encounter_ruleset(ruleset)
    cases = _cases(cases)
    variants = _selection(variants, VARIANTS, "sensitivity variants")
    require(
        len({(s["family"], s["stage"], s["roll_seed"]) for s in checkpoints})
        == len(checkpoints),
        "duplicate checkpoint identity",
    )
    work = Budget(max_events, memory_bytes, wall_seconds, cancel, _reference_only)
    rows = []
    stopped = None
    reused = 0
    required = (
        sum(c["id"] in VARIANT_CASES[v] for c in cases for v in variants)
        * len(seeds)
        * len(checkpoints)
    )
    require(
        required <= 250_000, "finalist panel exceeds 250,000 reported draw outcomes"
    )
    first_unvisited = None
    cached_index = -1
    for index, checkpoint, variant, case in _batches(checkpoints, cases, variants):
        if index != cached_index:
            receipts, preparations = {}, {}
            work.cache_bytes = 0
            cached_index = index
        try:
            if _prefix_rows is not None and len(rows) >= _prefix_rows:
                raise PanelLimit("replay_prefix")
            work.check()
            batch, matched = _run_batch(
                work,
                rows,
                checkpoint,
                case,
                variant,
                seeds,
                ruleset["content_hash"],
                receipts,
                preparations,
            )
            work.retain(batch)
            rows.extend(batch)
            reused += matched
        except PanelLimit as exc:
            stopped = str(exc)
            first_unvisited = _base(checkpoint, case, variant, seeds[0])
            break
    counts = Counter(row["status"] for row in rows)
    config = {"cases": cases, "seeds": list(seeds), "variants": variants}
    coverage = {
        "required": required,
        **{k: counts[k] for k in ("replayed", "unsupported")},
        "unvisited": required - len(rows),
    }
    return {
        "schema_version": 1,
        "ruleset_hash": ruleset["content_hash"],
        "config": config,
        "input_hash": _panel_digest(checkpoints, (config, ruleset["content_hash"])),
        "rows": rows,
        "coverage": coverage,
        "outcomes_hash": _panel_digest(rows),
        "first_unvisited": first_unvisited,
        "termination": stopped or "exhausted",
        "counters": {
            "events": work.events,
            "encounter_batches": work.batches,
            "native_trials": work.trials,
            "replayed_trials": work.replayed,
            "reused_batches": reused,
            "peak_native_work_bytes": work.peak_bytes,
            "peak_matrix_work_bytes": work.peak_matrix_bytes,
        },
        "elapsed_seconds": perf_counter() - started,
    }


evaluate_panel = evaluate_matrix


def verify_matrix(matrix, checkpoints, *, ruleset=None):
    """Reproduce each published outcome, permitting a bounded prefix of verified batches."""
    config = matrix["config"]
    rules = load_ruleset() if ruleset is None else ruleset
    require(
        matrix["input_hash"]
        == _panel_digest(checkpoints, (config, rules["content_hash"])),
        "matrix replay input mismatch",
    )
    rows = matrix["rows"]
    require(
        isinstance(rows, list) and matrix["outcomes_hash"] == _panel_digest(rows),
        "matrix replay identity mismatch",
    )
    expected = evaluate_matrix(
        checkpoints,
        **config,
        ruleset=rules,
        _reference_only=True,
        _prefix_rows=len(rows),
        memory_bytes=max(64 << 20, matrix["counters"]["peak_matrix_work_bytes"]),
    )
    require(rows == expected["rows"], "matrix replay outcome mismatch")
    require(
        matrix["coverage"] == expected["coverage"], "matrix replay coverage mismatch"
    )
    require(
        matrix["first_unvisited"] == expected["first_unvisited"],
        "matrix replay missing suffix mismatch",
    )
    if expected["first_unvisited"] is None:
        require(
            matrix["termination"] == "exhausted", "matrix replay termination mismatch"
        )
    else:
        require(
            matrix["termination"]
            in ("event_limit", "time_limit", "memory_limit", "cancelled"),
            "invalid unvisited matrix replay suffix",
        )
    return {
        "verified": True,
        "outcomes_hash": matrix["outcomes_hash"],
        "rows_checked": sum(r["status"] == "replayed" for r in rows),
    }
