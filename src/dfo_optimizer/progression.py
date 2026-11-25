"""Offline progression search and independent replay from a frozen character."""
from copy import deepcopy
from hashlib import sha256
import json
from math import isclose, isfinite
from pathlib import Path
from time import perf_counter

from .progression_domain import Domain, Gap, _FIELDS, _spell_data, boolean, evidence, fields, get_recipe, integer, windows
from .progression_replay import _cast_price, goal_met, initial_effort, require, transition
from .ruleset import load_ruleset, validate_progression_ruleset


def digest(obj):
    return sha256(json.dumps(obj, sort_keys=True, ensure_ascii=True, allow_nan=False,
                             separators=(",", ":")).encode()).hexdigest()


_REQUEST = {"schema_version", "ruleset_hash", "start", "stages", "activities", "cycles", "max_events", "goal",
            "search", "checkpoints", "require_starting_damage", "description", "time_model"}


def _freeze(request, base_dir):
    raw = deepcopy(fields(request, _REQUEST, "progression request"))
    integer(raw.get("schema_version", 1), "schema_version", 1, 1)
    start = raw.get("start")
    require(isinstance(start, dict), "provide progression start")
    if "character_file" in start:
        from .character import import_character
        require("character" not in start, "provide either character or character_file")
        file = start.pop("character_file")
        require(isinstance(file, str) and file, "character_file requires a local path")
        start["character"] = import_character(Path(base_dir or ".") / file, slot=start.pop("slot", None))
    if start.get("type") == "current_character" and "live_observations" in start:
        from .character import apply_request_observations, normalize_character
        start["character"] = apply_request_observations({"character": normalize_character(start.get("character")),
            "live_observations": start.pop("live_observations")})["character"]
    return raw


def _limits(raw):
    opts = fields(raw.get("search", {}), ("max_nodes", "memory_bytes", "wall_seconds", "workers",
                      "exact", "retain_states", "final_stage_only"), "progression search")
    exact = boolean(opts.get("exact", False), "search.exact")
    integer(opts.get("workers", 1), "progression workers", 1, 1)
    wall = opts.get("wall_seconds", 0)
    require(type(wall) in (int, float) and isfinite(wall) and 0 <= wall <= 86400, "invalid wall_seconds")
    return {
        "max_nodes": integer(opts.get("max_nodes", 0 if exact else 100000), "max_nodes", 0, 2**62),
        "memory_bytes": integer(opts.get("memory_bytes", 64 << 20), "memory_bytes", 1, 2**62),
        "wall_seconds": float(wall),
        "retain_states": boolean(opts.get("retain_states", False), "retain_states"),
        "final_stage_only": boolean(opts.get("final_stage_only", False), "final_stage_only"),
    }


_DEFAULTS = {
    "skills": [0]*35, "uses": [0]*35, "fractions": [0.]*35, "progress": [0.]*35,
    "spam_recent": [0.]*35, "spam_at": [0]*35, "attributes": [50]*8,
    "primary": [0, 1, 2], "major": [3, 4, 5], "minor": [6, 7, 8, 9, 10, 11], "mastered": [],
    "level": 1, "starting_sum": 150, "current_sum": 150, "reflexes": 2, "advancement_multiplier": 1.,
    "minutes": 0, "last_check": 0, "last_training": 0, "last_rest": -1,
    "pending_level": -1, "pending_pool": -1, "gold": 0, "bank_gold": 0, "sp": 0, "fatigue": 0,
    "arcane_path": -1, "martial_path": -1, "real_ms": 0, "challenge_at": -1, "challenge_level": 0,
    "odometer_h": 0., "odometer_v": 0., "move_mark": [-1.]*35, "move_credit": [0.]*35,
}


def _native_start(d):
    s = {}
    for k, placeholder in _DEFAULTS.items():
        v = d.source_state.get(k)
        if v is None:
            s[k] = deepcopy(placeholder)
        elif k in ("arcane_path", "martial_path") and v != -1:
            s[k] = d.path(k.split("_")[0], v)[0]
        else:
            s[k] = deepcopy(v)
    used = {i for k in ("primary", "major", "minor") for i in (d.source_state.get(k) or [])}
    spare = iter(i for i in range(35) if i not in used)
    for k in ("primary", "major", "minor"):
        if d.source_state.get(k) is None:
            s[k] = [next(spare) for _ in _DEFAULTS[k]]
    s["known"] = sorted(d.spell_ids.index(i) for i in (d.source_state.get("known") or []))
    s["mastered"].sort()
    return s


def _compiled_windows(domain, rows):
    original, compiled, excluded = [], [], {}
    cached = {}
    for n, row in enumerate(rows):
        if id(row) not in cached:
            actions, sources, issues = [], [], []
            for index, action in enumerate(row):
                try:
                    actions.append(domain.compile_action(action))
                    sources.append(index)
                except Gap as exc:
                    issues.append({"alternative": index, "reason": str(exc)})
            cached[id(row)] = (actions, sources, issues)
        actions, indices, issues = cached[id(row)]
        if issues:
            excluded[n] = issues
        if not actions:
            break
        original.append(indices)
        compiled.append(actions)
    return compiled, original, excluded


def _prepare(raw, rules):
    from .progression_inputs import resolve_start
    fields(raw, _REQUEST, "frozen progression request")
    require(isinstance(raw.get("start"), dict) and "character_file" not in raw["start"],
            "frozen progression start must embed its character inputs")
    require(raw.get("ruleset_hash", rules["content_hash"]) == rules["content_hash"], "progression ruleset mismatch")
    start, missing = resolve_start(raw["start"], rules=rules)
    flags = (start.get("career") or {}).get("abilityFlagsAndSpellPointsBitfield", 0)
    start["environmental_magery"] = bool(flags & 0x3C0)
    if raw["start"].get("type") == "current_character":
        from .character import normalize_character
        imported = normalize_character(raw["start"]["character"])
        caster = imported["caster"]
        from .progression_replay import effective
        if start.get("skills") is not None and start.get("mastered") is not None:
            actual = start["skills"][22]
            trained = effective(actual if 22 in start["mastered"] else min(actual, 100))
            live = caster.get("destruction_live")
            start["skill_bonus"] = live - trained if live is not None else 0
            start["practice_modifiers_unknown"] = live is None
        start["practice_modifiers_unknown"] = (start.get("practice_modifiers_unknown", True)
                or bool(imported["unknown_mechanics"]) or caster.get("focus_pct") is None)
        start["focus_pct"] = caster.get("focus_pct") or 0
    goal = raw.get("goal")
    require(isinstance(goal, dict), "provide progression goal")
    rows = windows(raw)
    law = rules["progression_rules"]
    ids, records = _spell_data(start, rows, goal)
    missing = set(missing) | {k for k, v in start.items() if v is None}
    trainers = dict(law["training_skills"])
    trainers.update(law.get("temple_training_skills", {}))
    rates = {}
    if "time_model" in raw:
        model = fields(raw["time_model"], ("seconds_by_kind", "source"), "time_model")
        evidence(model.get("source"))
        rates = fields(model.get("seconds_by_kind"), _FIELDS, "seconds_by_kind")
        require(all(type(v) in (float, int) and isfinite(v) and 0 <= v <= 86400 for v in rates.values()),
                "time estimates require finite nonnegative seconds per event")
        require(rates, "time model has no rates")
    d = Domain(start, missing, law["paths"], ids, records, trainers, set(law.get("temple_training_skills", {})), rates)
    goal = d.compile_goal(goal)
    compiled, original, excluded = _compiled_windows(d, rows)
    limits = _limits(raw)
    checkpoint_levels = raw.get("checkpoints", [5, 10, 15, 20, 25, 30, 35, 40, 45])
    require(isinstance(checkpoint_levels, list), "checkpoints must be an array of levels")
    levels = {integer(i, "checkpoint", 1, 45) for i in checkpoint_levels}
    native_start = _native_start(d)
    blockers = [f"missing goal observation {k}" for k in sorted(set(goal).intersection(missing))]
    positive = boolean(raw.get("require_starting_damage", raw["start"].get("type") == "new_character"),
                       "require_starting_damage")
    if positive:
        eligible = []
        for i in native_start["known"]:
            recipe = get_recipe(records.get(ids[i], {}))
            signature = any(row.get("signature") == ids[i] for row in law["paths"])
            if (recipe and not signature and
                    (recipe[3] > 0 or recipe[5] * (native_start["level"] // recipe[6]) > 0)):
                eligible.append(_cast_price(native_start, {"recipe": recipe, "skill_bonus": start.get("skill_bonus", 0),
                                                            "focus_pct": start.get("focus_pct", 0)}))
        if start["environmental_magery"]:
            blockers.append("starting damage requires a verified environment for this career's environmental magery")
        elif ({"sp", "level", "skills", "known", "mastered"}.intersection(missing) or not eligible
                or start.get("practice_modifiers_unknown") or start.get("has_spellbook") is not True
                or min(eligible) > native_start["sp"]):
            blockers.append("starting damage requires an affordable resolved direct-damage spell")
    return d, rows, compiled, original, excluded, goal, limits, levels, native_start, blockers


def _public_state(d, s):
    out = deepcopy(s)
    for k in d.missing.intersection(out):
        out[k] = None
    if out.get("known") is not None:
        out["known"] = [d.spell_ids[i] for i in out["known"]]
    for key in ("arcane_path", "martial_path"):
        v = out[key]
        out[key] = d.path_rows[v]["id"] if v is not None and v >= 0 else None
    for key in ("max_sp", "hp", "max_hp", "max_fatigue", "race_id", "has_spellbook"):
        out[key] = d.source_state.get(key)
    if s["level"] != d.source_state.get("level") or s["attributes"] != d.source_state.get("attributes"):
        # The source level-up HP roll and live resource overlays require separate evidence.
        out["hp"] = out["max_hp"] = None
        if d.source_state.get("attributes") and s["attributes"][1] != d.source_state["attributes"][1]:
            out["max_sp"] = None
        if d.source_state.get("attributes") and any(s["attributes"][i] != d.source_state["attributes"][i] for i in (0, 4)):
            out["max_fatigue"] = None
    return out


def _same(a, b):
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
    return a == b


def _route(context, choices, *, native=None, public_choices=False):
    d, rows, compiled, original, _, _, limits, levels, start, _ = context
    require(isinstance(choices, list) and len(choices) <= len(compiled), "invalid route length")
    s, effort = start, initial_effort()
    actions, indices, checkpoints = [], [], []
    seconds = 0. if d.time_model else None
    def point(i):
        checkpoints.append({"stage": i, "state": _public_state(d, s), "effort": dict(effort)})
    point(0)
    for n, selected in enumerate(choices):
        integer(selected, "route alternative")
        if public_choices:
            require(selected in original[n], f"unavailable alternative at stage {n+1}")
            j = original[n].index(selected)
        else:
            j = selected
            require(j < len(compiled[n]), "invalid native action index")
        prev = s
        prev_effort = effort
        s, effort = transition(prev, compiled[n][j], effort)
        if seconds is not None:
            kind = compiled[n][j]["kind"]
            units = effort["practice"] - prev_effort["practice"] if kind == "practice" else int(kind != "skip" and prev != s)
            if units:
                rate = d.time_model.get(kind)
                seconds = None if rate is None else seconds + rate * units
        indices.append(original[n][j])
        actions.append(rows[n][indices[-1]])
        if (limits["retain_states"] or n+1 == len(choices) or
                s["level"] in levels and s["level"] != prev["level"] or
                s["mastered"] != prev["mastered"] or s["known"] != prev["known"] or
                any(s[k] != prev[k] for k in ("arcane_path", "martial_path"))):
            point(n+1)
    if native is not None:
        for key, v in s.items():
            if key not in native["state"] or not _same(v, native["state"][key]):
                raise RuntimeError(f"native progression differs from independent replay: {key}")
        if native["effort"] != effort:
            raise RuntimeError("native progression effort differs from independent replay")
    return {"choices": indices, "actions": actions, "checkpoints": checkpoints, "state": _public_state(d, s),
            "effort": effort, "wall_time_to_train_seconds": seconds}, s


def _first_gap(context, prefix, state):
    _, rows, compiled, original, excluded, _, _, _, _, blockers = context
    if blockers:
        return {"stage": 0, "reasons": blockers}
    n = len(prefix["choices"])
    if n == len(rows):
        return {"stage": n, "reasons": ["declared activities ended before the goal"]}
    reasons = list(excluded.get(n, ()))
    if n < len(compiled):
        for i, a in enumerate(compiled[n]):
            try:
                transition(state, a, prefix["effort"])
            except ValueError as exc:
                reasons.append({"alternative": original[n][i], "reason": str(exc)})
    return {"stage": n + 1, "reasons": reasons or ["unexplored continuations remain within the search limits"]}


def _identity(plan):
    # Convert numeric stage IDs to JSON object keys before sorting, including after a disk round trip.
    identity = {k: v for k, v in plan.items() if k not in ("counters", "timings", "frozen_request", "result_hash")}
    return digest(json.loads(json.dumps(identity)))


def plan_progression(request, *, ruleset=None, base_dir=None, cancel=None):
    from . import _progression
    tic = perf_counter()
    rules = validate_progression_ruleset(load_ruleset() if ruleset is None else ruleset)
    raw = _freeze(request, base_dir)
    ctx = _prepare(raw, rules)
    d, rows, stages, _, excluded, goal, limits, _, start, blockers = ctx
    before_search = perf_counter()
    stats = {"results": [], "prefix": {"choices": []}, "termination": "unsupported"}
    if not blockers:
        stats = _progression.search(start, stages, goal, cancel=cancel, **limits)
    searched_at = perf_counter()
    first, routes = None, []
    if not blockers:
        for row in stats["results"]:
            route, end = _route(ctx, row["choices"], native=row)
            if not goal_met(end, goal):
                raise RuntimeError("native route missed its progression goal")
            if limits["final_stage_only"] and len(route["choices"]) != len(rows):
                continue
            routes.append(route)
            if first is None:
                first = perf_counter() - tic
    prefix = end = None
    if not routes:
        prefix, end = _route(ctx, stats["prefix"]["choices"], native=stats["prefix"] if not blockers else None)
    term = stats["termination"]
    exact = term == "exhausted" and not excluded and not blockers
    if term == "cancelled":
        status = "cancelled"
    elif routes:
        status = "optimal_proven" if exact else "best_found_bounded"
    elif blockers or excluded and term == "exhausted":
        status = "unsupported"
    else:
        status = "infeasible_proven" if exact else "no_feasible_found"
    plan = {"kind": "progression_plan", "schema_version": 1, "engine": "native-cython-cpp17",
            "source_sha": rules["source_sha"], "ruleset_hash": rules["content_hash"],
            "input_hash": digest(raw), "frozen_request": raw, "status": status, "exact": exact,
            "termination": term, "routes": routes, "prefix": prefix if not routes else None,
            "first_gap": None if routes else _first_gap(ctx, prefix, end),
            "excluded_actions": excluded, "missing_observations": sorted(d.missing), "goal_blockers": blockers,
            "proof_scope": "Online snapshot and declared finite opportunities, rolls, stage order and resource evidence.",
            "effort_scope": "Practice actions include trainer sessions. Personal game minutes and qualifying raise passes "
                             "are reported separately. Opportunity availability is conditional on the request.",
            "resource_scope": "Stationary practice assumes zero locomotion and no incoming damage or extra casts. "
                              "Motion debits the supplied measured fatigue cost. Night recovery declares an absolute "
                              "resource floor at an uninterrupted bed or camp. Unmodeled gains are excluded.",
            "wall_time_to_train_seconds": routes[0]["wall_time_to_train_seconds"] if routes else None,
            "next_decision": next(iter((routes[0] if routes else prefix)["actions"]), None),
            "validation": {"finalists_checked": len(routes), "prefix_checked": not bool(routes)},
            "counters": {k:v for k,v in stats.items() if k not in ("results", "prefix", "termination")},
            "timings": {"first_replayed_seconds": first, "native_seconds": searched_at-before_search,
                        "replay_seconds": perf_counter()-searched_at, "elapsed_seconds": perf_counter()-tic}}
    plan["result_hash"] = _identity(plan)
    return plan


def replay_progression(document, *, ruleset=None):
    """Recreate inputs and check each public action, checkpoint, objective and saved identity."""
    rules = validate_progression_ruleset(load_ruleset() if ruleset is None else ruleset)
    require(isinstance(document, dict) and document.get("kind") == "progression_plan"
            and document.get("schema_version") == 1, "invalid progression plan")
    require(document.get("ruleset_hash") == rules["content_hash"], "progression replay ruleset mismatch")
    raw = document.get("frozen_request")
    require(isinstance(raw, dict) and digest(raw) == document.get("input_hash"), "frozen progression request hash mismatch")
    require({"source_sha","status","termination","routes","prefix","first_gap","result_hash"} <= document.keys(),
            "incomplete progression result")
    require(document["source_sha"] == rules["source_sha"], "progression replay source mismatch")
    ctx = _prepare(raw, rules)
    routes = document.get("routes")
    require(isinstance(routes, list), "missing progression routes")
    for route in routes:
        require(isinstance(route, dict), "malformed progression route")
        actual, state = _route(ctx, route.get("choices"), public_choices=True)
        require(actual == route and goal_met(state, ctx[5]), "progression route or checkpoint mismatch")
        require(not ctx[9], "unsupported starting goal")
        if ctx[6]["final_stage_only"]:
            require(len(route["choices"]) == len(ctx[1]), "incomplete final-stage route")
    prefix = document.get("prefix")
    if not routes:
        require(isinstance(prefix, dict), "missing replayable prefix")
        actual, state = _route(ctx, prefix.get("choices"), public_choices=True)
        require(ctx[9] or not goal_met(state, ctx[5]) or
                ctx[6]["final_stage_only"] and len(prefix["choices"]) < len(ctx[1]) or
                document["termination"] in ("node_limit", "memory_limit", "time_limit", "cancelled"),
                "empty frontier contains a completed goal")
        require(actual == prefix and document.get("first_gap") == _first_gap(ctx, actual, state),
                "progression prefix or reachability gap mismatch")
    else:
        require(prefix is None and document.get("first_gap") is None, "unexpected prefix or first gap on completed plan")
    require(document.get("result_hash") == _identity(document), "progression result hash mismatch")
    return {"valid": True, "result_hash": document["result_hash"], "routes_checked": len(routes),
            "prefix_checked": prefix is not None, "ruleset_hash": rules["content_hash"]}
