"""Search and independently replay frozen, stage-specific online spellcasting builds."""

from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from time import perf_counter
import math

from .lifecycle_domain import catalog, compile_route
from .lifecycle_replay import replay_choices
from .progression import _prepare, _route, digest, goal_met, plan_progression
from .progression_domain import fields, integer, require
from .progression_inputs import resolve_start
from .ruleset import _progression_service_rules
from .spellbook import pack_spell
from .spell_request import _target


def _rules(rules):
    return _progression_service_rules(rules)


def _freeze(request, rules, base_dir, replan):
    from .character import import_character

    if isinstance(request, dict) and "progression_file" in request:
        require(
            not set(request) & {"families", "class_search", "progression"},
            "use a progression file or inline family and schedule",
        )
        filename = request["progression_file"]
        require(isinstance(filename, str) and filename.strip(), "invalid progression file")
        with (Path(base_dir or ".") / filename).open("rb") as handle:
            from .character_files import read_json, MAX_SAVE_BYTES

            frozen = read_json(handle, MAX_SAVE_BYTES, "progression request")
        source = frozen.pop("start", None)
        require(isinstance(source, dict), "progression file has no start")
        frozen["search"] = {"final_stage_only": False, **frozen.get("search", {})}
        if "character_file" in source:
            file = Path(base_dir or ".") / filename
            source["character"] = import_character(
                file.parent / source.pop("character_file"), slot=source.pop("slot", None)
            )
        request = {k: v for k, v in request.items() if k != "progression_file"}
        request.update(families=[{"id": "progression character", "start": source}], progression=frozen)
    allowed = {
        "schema_version",
        "ruleset_hash",
        "description",
        "families",
        "class_search",
        "roll_seeds",
        "progression",
        "checkpoints",
        "target",
        "targets",
        "spellbook",
        "equipment",
        "encounter",
        "budget_gold",
        "search",
        "sensitivity",
    }
    raw = deepcopy(fields(request, allowed, "build request"))
    integer(raw.get("schema_version", 1), "schema_version", 1, 1)
    require(raw.get("ruleset_hash", rules["content_hash"]) == rules["content_hash"], "build ruleset mismatch")
    _target(raw.get("target"))
    if "encounter" in raw:
        from .ruleset import validate_encounter_ruleset
        validate_encounter_ruleset(rules)
        require(isinstance(raw["encounter"],dict), "encounter must be an object")
    require(isinstance(raw.get("targets", {}), dict), "targets must map checkpoint numbers to targets")
    for k, v in raw.get("targets", {}).items():
        require(
            isinstance(k, str) and k.isascii() and k.isdecimal() and str(int(k)) == k, "invalid target checkpoint"
        )
        _target(v)
    require(
        isinstance(raw.get("progression"), dict) and not set(raw["progression"]) & {"start", "ruleset_hash"},
        "supply the shared progression goal and opportunities separately from the family start",
    )
    if "budget_gold" in raw:
        integer(raw["budget_gold"], "gold ceiling", 0, 2**53 - 1)
    require("class_search" in raw or "families" in raw, "build requires class families or a native class search")
    if replan:
        require(
            "class_search" not in raw
            and len(raw.get("families", [])) == 1
            and raw["families"][0].get("start", {}).get("type") == "current_character",
            "replan requires one immutable current character",
        )
    for f in raw.get("families", []):
        require(isinstance(f, dict), "invalid build family")
        start = f.get("start", {})
        require(isinstance(start, dict), "invalid family start")
        if "character_file" in start:
            require(
                "character" not in start and start.get("type") == "current_character", "ambiguous character import"
            )
            start["character"] = import_character(
                Path(base_dir or ".") / start.pop("character_file"), slot=start.pop("slot", None)
            )
        if start.get("type") == "current_character" and "live_observations" in start:
            from .character import apply_request_observations

            start["character"] = apply_request_observations(
                {"character": start["character"], "live_observations": start.pop("live_observations")}
            )["character"]
    return raw


def _controls(raw):
    s = fields(
        raw.get("search", {}),
        {"max_nodes", "wall_seconds", "memory_bytes", "exact", "workers"},
        "lifecycle search",
    )
    require(type(s.get("exact", False)) is bool, "exact must be boolean")
    integer(s.get("workers", 1), "lifecycle workers", 1, 1)
    wall = s.get("wall_seconds", 120)
    require(type(wall) in (float, int) and math.isfinite(wall) and 0 <= wall <= 86400, "invalid wall budget")
    return {
        "max_nodes": integer(s.get("max_nodes", 0 if s.get("exact") else 1_000_000), "max_nodes", 0, 2**62),
        "memory_bytes": integer(s.get("memory_bytes", 256 << 20), "memory_bytes", 1, 2**62),
        "wall_seconds": float(wall),
    }


def _admit_classes(raw, rules, token):
    from .search import optimize_classes

    if "class_search" not in raw:
        return raw
    query = raw["class_search"]
    require(isinstance(query, dict), "class_search must be an object")
    result = optimize_classes({**query, "objective": "examples"}, ruleset=rules, cancel=token.class_token)
    bounded = result["status"] not in ("optimal_proven", "infeasible_proven") or result["counters"].get(
        "leaves", 0
    ) > len(result["candidates"])
    admitted = [
        {"id": c["class_id"], "start": {"type": "new_character", "class": c["class_doc"], "race_id": c["race_id"]}}
        for c in result["candidates"]
    ]
    return {
        **raw,
        "class_admission": {
            "families": admitted,
            "bounded": bounded,
            "status": result["status"],
            "termination": result["termination"],
            "result_hash": result["result_hash"],
            "limits": {
                k: result["proof_scope"][k]
                for k in ("max_nodes", "memory_bytes", "wall_seconds", "top_k", "exact")
            },
            "counters": {k: result["counters"][k] for k in ("nodes", "pruned", "leaves")},
        },
    }


def _families(raw, rules):
    admission = raw.get("class_admission", {})
    fam = [*raw.get("families", []), *admission.get("families", [])]
    bounded = admission.get("bounded", False)
    return list(catalog(fam, rules)) if fam else [], bounded


def _rolls(raw, families):
    seeds = raw.get("roll_seeds")
    fixed = any("rolls" in s or "roll_seed" in s for _, s, _, _ in families if s.get("type") == "new_character")
    current = any(s.get("type") == "current_character" for _, s, _, _ in families)
    if current or fixed:
        require(
            len(families) == 1 and seeds is None,
            "a realized or current start requires a single family without paired rolls",
        )
        return [None]
    seeds = list(range(42, 50)) if seeds is None else seeds
    require(
        isinstance(seeds, list)
        and 1 <= len(seeds) <= 128
        and all(type(i) is int and 0 <= i < 2**32 for i in seeds)
        and len(set(seeds)) == len(seeds),
        "roll_seeds must contain 1..128 distinct uint32 values",
    )
    return seeds


def _comparison(raw, rolls):
    fixed = []
    profiles = {family.get("start", {}).get("profile", "dhargo_pve") for family in raw.get("families", [])}
    if rolls == [None]:
        for family in raw.get("families", []):
            start = family.get("start", {})
            if start.get("type") == "current_character":
                from .character import normalize_character

                fixed.append({"current_snapshot": normalize_character(start["character"])["snapshot_hash"]})
            else:
                fixed.append({k: start[k] for k in ("roll_seed", "rolls") if k in start})
    return digest(
        {
            "target": raw["target"],
            "targets": raw.get("targets", {}),
            "rolls": rolls,
            "realized_starts": fixed,
            "equipment": raw.get("equipment", {}),
            "spellbook": raw.get("spellbook", {}),
            "budget_gold": raw.get("budget_gold"),
            "checkpoints": raw.get("checkpoints"),
            "progression": {k: v for k, v in raw["progression"].items() if k not in ("search", "description")},
            "metric": "one-landed-hit-per-cast checkpoint DPS" if "encounter" not in raw else "damage per encounter horizon second",
            **({"encounter":raw["encounter"]} if "encounter" in raw else {}),
            **({"class_profiles": sorted(profiles)} if "custom" in profiles else {}),
        }
    )


def _progress(raw, start):
    return {
        **raw["progression"],
        "start": start,
        "search": {"final_stage_only": True, **raw["progression"].get("search", {}), "retain_states": True},
    }


def _unknown(source, start, *, encounter=False):
    blockers = []
    for name in ("sp", "gold", "skills", "attributes", "mastered", "known", "career"):
        v = source.get(name)
        if v is None or isinstance(v, list) and None in v:
            blockers.append(f"missing current {name}")
    if start["type"] == "current_character":
        from .character import normalize_character

        snapshot = normalize_character(start["character"])
        blockers.extend(issue for issue in snapshot.get("unknown_mechanics", [])
                        if not encounter or not issue.startswith(("arcanePath:", "martialPath:")))
        blockers.extend(snapshot["observations"].get("worn_equipment_issues", []))
        overlays = {
            "speed",
            "destruction_live",
            "destruction_trained",
            "destruction_mastered",
            "level",
            "focus_pct",
            "cast_speed_pct",
            "power_pct",
            "pierce",
        }.intersection(snapshot["live_observations"])
        if overlays:
            blockers.append(
                "cannot separate temporary or equipment bonuses in live observations: "
                + ", ".join(sorted(overlays))
            )
    if not source.get("career"):
        blockers.append("missing current career")
    elif source["career"].get("abilityFlagsAndSpellPointsBitfield", 0) & 0x3C0:
        if "environmental_magery" not in blockers:
            blockers.append("environmental_magery")
    if source.get("has_spellbook") is not True:
        blockers.append("casting requires a confirmed physical spellbook")
    return blockers


def _specialized(checkpoints, *, encounter):
    for checkpoint in checkpoints:
        state = checkpoint["state"]
        if not encounter and (state.get("arcane_path") or state.get("martial_path")
                              or (state.get("firmament") or {}).get("tree", {}).get("start")):
            return True
    return False


def _witness(d, route, row, name, origin, seed):
    steps = replay_choices(d, row["slots"], row["policies"], row["bought"], row["scores"])
    if "end_hp" in row or "end_sp" in row:
        require([s["encounter"]["end_hp"] for s in steps] == row.get("end_hp") and
                [s["encounter"]["end_sp"] for s in steps] == row.get("end_sp"),
                "native encounter resources differ from independent event replay")
    require(steps[-1]["spent_gold"] == row["spent"], "native spending differs from replay")
    effort = route["effort"]
    return {
        "family": name,
        "baseline_id": origin,
        "roll_seed": seed,
        "progression_choices": route["choices"],
        "actions": route["actions"],
        "checkpoints": steps,
        "effort": effort,
        "total_spent_gold": effort["spent"] + steps[-1]["spent_gold"],
        "final_level": steps[-1]["level"],
        "choices": {k: row[k] for k in ("slots", "policies", "bought")},
        "birth_or_import_hash": d.source.get("snapshot_hash"),
        "unscored_spell_records": sorted(set(d.omitted)),
        "excluded_equipment": {key: list(reasons) for key, reasons in d.domain.filtered.items()},
        "validated": True,
    }


def _numeric(d, opts, token):
    from . import _lifecycle

    return _lifecycle.optimize_route(
        d.stages,
        d.copies,
        d.slots,
        d.declared,
        [pack_spell(recipe) for _, recipe in d.book],
        [[d.names.index(k) for k in policy] for policy in d.scripts],
        d.owned,
        encounters=d.encounters,
        wellspring=[sum(line["value"] for line in it.item.get("affixes", []) if line["id"] == "wellspring")
                    for it in d.domain.items] if d.encounters else None,
        cancel=token,
        **opts,
    )


def _group(row, explicit):
    return row["roll_seed"], tuple(p["stage"] if explicit else p["level"] for p in row["checkpoints"])


def _rank(rows, explicit):
    from . import _lifecycle

    groups = defaultdict(list)
    for row in rows:
        groups[_group(row, explicit)].append(row)
    keep = []
    cap = []
    for members in groups.values():
        coords = [
            [
                *(s["dps"] for s in r["checkpoints"]),
                -r["effort"]["practice"],
                -r["effort"]["rest_passes"],
                -r["effort"]["minutes"],
                -r["total_spent_gold"],
            ]
            for r in members
        ]
        keep.extend(members[j] for j in _lifecycle.frontier_indices(coords))
        best = max(r["checkpoints"][-1]["dps"] for r in members)
        cap.extend(
            {
                "family": r["family"],
                "roll_seed": r["roll_seed"],
                "final_level": r["final_level"],
                "final_dps": best,
                "early_dps": r["checkpoints"][0]["dps"],
                "practice": r["effort"]["practice"],
                "total_spent_gold": r["total_spent_gold"],
            }
            for r in members
            if r["checkpoints"][-1]["dps"] == best
        )
    return keep, cap


def _spread(rows, rolls):
    grouped = defaultdict(dict)
    for r in rows:
        k, s = r["family"], r["roll_seed"]
        grouped[k][s] = max(grouped[k].get(s, 0), r["checkpoints"][-1]["dps"])
    return [
        {
            "family": k,
            "rolls": [{"seed": s, "peak_final_dps": v} for s, v in samples.items()],
            "covered_rolls": list(samples),
            "complete_roll_set": len(samples) == len(rolls),
            "peak_final_dps_min": min(samples.values()),
            "peak_final_dps_max": max(samples.values()),
        }
        for k, samples in grouped.items()
    ]


def _id(plan):
    return digest(
        {
            k: plan.get(k)
            for k in (
                "schema_version",
                "kind",
                "source_sha",
                "engine",
                "input_hash",
                "ruleset_hash",
                "comparison_hash",
                "status",
                "termination",
                "exact",
                "stopping_reasons",
                "paired_rolls",
                "proof_scope",
                "assumptions",
                "families",
                "sensitivity",
                "candidates",
                "final_checkpoint_only",
                "roll_spread",
                "gaps",
            )
        }
    )


def _run(request, rules, base_dir, replan, cancel, *, scope=None, frozen=False):
    from . import _lifecycle

    begin = perf_counter()
    token = cancel if cancel is not None else _lifecycle.CancelToken()
    if scope is None:
        raw = request if frozen else _admit_classes(_freeze(request, rules, base_dir, replan), rules, token)
        limits = _controls(raw)
        families, truncated = _families(raw, rules)
        rolls = _rolls(raw, families)
        if limits["max_nodes"] and len(families) * len(rolls) > 1:
            from .lifecycle_refinement import refine_families

            def search_family(family, seed, allocation):
                return _run(raw, rules, base_dir, replan, cancel, scope=(raw, allocation, [family], [seed]))

            return refine_families(raw, rules, families, rolls, limits, truncated, cancel, begin, search_family)
    else:
        raw, limits, families, rolls = scope
        truncated = False
    term = ["class_limit"] if truncated else []
    if token.cancelled():
        term.append("cancelled")
    counters = dict(
        nodes=0, pruned=0, leaves=0, evaluations=0, cache_hits=0, work_bytes=0, progression_nodes=0, layouts=0
    )
    gaps = []
    rows = []
    first = None

    def seconds_left():
        return max(0.0, limits["wall_seconds"] - (perf_counter() - begin)) if limits["wall_seconds"] else 0.0

    for seed in rolls:
        for name, template, origin, reason in families:
            if token.cancelled() or limits["wall_seconds"] and not seconds_left():
                term.append("cancelled" if token.cancelled() else "time_limit")
                break
            if reason:
                gaps.append({"family": name, "roll_seed": seed, "kind": "profile_exclusion", "reasons": [reason]})
                continue
            start = template if seed is None else {**template, "roll_seed": seed}
            source, _ = resolve_start(start, rules=rules)
            missing = _unknown(source, start, encounter="encounter" in raw)
            if missing:
                gaps.append({"family": name, "roll_seed": seed, "kind": "unsupported", "reasons": missing})
                term.append("unsupported")
                continue
            pquery = _progress(raw, start)
            search = pquery["search"]
            if limits["wall_seconds"]:
                search["wall_seconds"] = (
                    min(seconds_left(), search.get("wall_seconds") or limits["wall_seconds"]) or 1e-12
                )
            if limits["max_nodes"]:
                remaining = limits["max_nodes"] - counters["nodes"]
                if remaining <= 0:
                    term.append("node_limit")
                    break
                search["max_nodes"] = min(remaining, search.get("max_nodes") or remaining)
            search["memory_bytes"] = min(limits["memory_bytes"], search.get("memory_bytes", 64 << 20))
            planned = plan_progression(pquery, ruleset=rules, cancel=token.progression_token)
            work = planned["counters"].get("nodes", 0)
            counters["nodes"] += work
            counters["progression_nodes"] += work
            counters["work_bytes"] = max(counters["work_bytes"], planned["counters"].get("work_bytes", 0))
            if not planned["exact"]:
                term.append(planned["termination"] if planned["termination"] != "exhausted" else "unsupported")
                if planned["excluded_actions"]:
                    gaps.append(
                        {
                            "family": name,
                            "roll_seed": seed,
                            "kind": "unsupported_opportunities",
                            "excluded_actions": {str(k): v for k, v in planned["excluded_actions"].items()},
                        }
                    )
            if not planned["routes"]:
                gaps.append(
                    {
                        "family": name,
                        "roll_seed": seed,
                        "kind": planned["status"],
                        "first_gap": planned["first_gap"],
                    }
                )
            for route in planned["routes"]:
                if token.cancelled() or limits["wall_seconds"] and not seconds_left():
                    term.append("cancelled" if token.cancelled() else "time_limit")
                    break
                if limits["max_nodes"] and counters["nodes"] >= limits["max_nodes"]:
                    term.append("node_limit")
                    break
                if _specialized(route["checkpoints"], encounter="encounter" in raw):
                    term.append("unsupported")
                    gaps.append(
                        {
                            "family": name,
                            "roll_seed": seed,
                            "kind": "unsupported",
                            "reasons": ["active specialization or Firmament effects require checkpoint combat validation"],
                        }
                    )
                    continue
                if route["effort"]["spent"] > raw.get("budget_gold", 2**53 - 1):
                    continue
                if any(action["kind"] == "reset" for action in route["actions"]) and source.get("bank_gold"):
                    term.append("unsupported")
                    gaps.append(
                        {
                            "family": name,
                            "roll_seed": seed,
                            "kind": "unsupported",
                            "reasons": [
                                "joint optional purchases can move a reset fee from carried gold to the bank"
                            ],
                        }
                    )
                    continue
                from .lifecycle_encounter import EncounterGap
                try:
                    d = compile_route(raw, source, route, rules, start)
                except EncounterGap as exc:
                    term.append("unsupported")
                    gaps.append({"family":name, "roll_seed":seed, "kind":"unsupported", "reasons":[str(exc)]})
                    continue
                if not d.scripts:
                    term.append("unsupported")
                    gaps.append(
                        {
                            "family": name,
                            "roll_seed": seed,
                            "kind": "unsupported",
                            "reasons": ["no scored spell records"],
                        }
                    )
                    continue
                stats = _numeric(
                    d,
                    {
                        **limits,
                        "wall_seconds": max(1e-12, seconds_left()) if limits["wall_seconds"] else 0,
                        "max_nodes": limits["max_nodes"] - counters["nodes"] if limits["max_nodes"] else 0,
                    },
                    token,
                )
                for key in ("nodes", "pruned", "leaves", "evaluations", "cache_hits", "layouts"):
                    counters[key] += stats[key]
                counters["work_bytes"] = max(counters["work_bytes"], stats["work_bytes"])
                if stats["termination"] != "exhausted":
                    term.append(stats["termination"])
                if stats["uncertain"]:
                    term.append("unknown_swap_capacity")
                for r in stats["routes"]:
                    rows.append(_witness(d, route, r, name, origin, seed))
                    if first is None:
                        first = perf_counter() - begin
                        token.mark_replayed()
    return _finish(raw, rules, rolls, rows, gaps, counters, term, first, begin, len(rows))


def _finish(raw, rules, rolls, rows, gaps, counters, term, first, begin, checked):
    kept, cap = _rank(rows, "checkpoints" in raw)
    termination = "cancelled" if "cancelled" in term else next(iter(term), "exhausted")
    status = (
        "cancelled"
        if termination == "cancelled"
        else (
            "best_found_bounded"
            if rows
            else "unsupported"
            if termination == "unsupported"
            else "no_feasible_found"
        )
        if term
        else ("optimal_proven" if rows else "infeasible_proven")
    )
    plan = {
        "schema_version": 1,
        "kind": "lifecycle",
        "source_sha": rules["source_sha"],
        "ruleset_hash": rules["content_hash"],
        "engine": "native-cython-cpp17",
        "frozen_request": raw,
        "input_hash": digest(raw),
        "comparison_hash": _comparison(raw, rolls),
        "paired_rolls": rolls,
        "status": status,
        "exact": not term,
        "termination": termination,
        "stopping_reasons": sorted(set(term)),
        "candidates": kept,
        "roll_spread": _spread(rows, rolls),
        "final_checkpoint_only": cap,
        "gaps": gaps,
        "counters": counters,
        "validation": {"routes_checked": checked},
        "timings": {"first_validated_seconds": first, "elapsed_seconds": perf_counter() - begin},
        "proof_scope": "Declared class, birth roll, activity, physical copy, offer, recipe, policy and checkpoint domains.",
        "assumptions": [
            ("Checkpoint DPS measures damage per declared encounter horizon second on the fixed common seed. "
             "Terminal mode considers purchases offered at the terminal checkpoint."
             if "encounter" in raw else
             "Checkpoint DPS measures a funded finite policy on one fresh ordinary foe per landed cast."),
            "Offers require supported physical properties, confirmed availability and a gold-only quote. Other currencies have zero available balance.",
            "Policy SP is reserved across checkpoints and training until an evidenced full refill. Scenario casts grant no training credit. Purchases persist.",
            "Effort uses the independently replayed actions and observed or explicitly declared opportunities.",
        ],
    }
    plan["families"] = plan["roll_spread"]
    plan["budget_scope"] = (
        "Lifecycle nodes cover progression and joint combat. Native class admission has its own reported limits."
    )
    plan["result_hash"] = _id(plan)
    return plan


def _sensitivity(raw, rules, base_dir, replan, cancel):
    plan = _run(raw, rules, base_dir, replan, cancel)
    config = fields(raw.get("sensitivity", {}), {"budget_gold", "max_nodes"}, "sensitivity")
    if config:
        report = []
        for key, values in config.items():
            require(isinstance(values, list) and len(values) <= 12, "sensitivity needs at most 12 values per axis")
            for value in values:
                req = {k: v for k, v in plan["frozen_request"].items() if k != "sensitivity"}
                if key == "max_nodes":
                    req["search"] = {**req.get("search", {}), "max_nodes": value}
                else:
                    req[key] = value
                r = _run(req, rules, base_dir, replan, cancel, frozen=True)
                report.append(
                    {
                        "axis": key,
                        "value": value,
                        "status": r["status"],
                        "result_hash": r["result_hash"],
                        "roll_spread": r["roll_spread"],
                        "frontier_size": len(r["candidates"]),
                    }
                )
        plan["sensitivity"] = report
        plan["result_hash"] = _id(plan)
    return plan


def optimize_build(request, ruleset=None, *, base_dir=None, cancel=None):
    return _sensitivity(request, _rules(ruleset), base_dir, False, cancel)


def replan_build(request, ruleset=None, *, base_dir=None, cancel=None):
    return _sensitivity(request, _rules(ruleset), base_dir, True, cancel)


def _replay_build(plan, rules):
    require(isinstance(plan, dict) and plan.get("kind") == "lifecycle", "invalid lifecycle plan")
    require(
        plan.get("ruleset_hash") == rules["content_hash"] and plan.get("source_sha") == rules["source_sha"],
        "lifecycle ruleset mismatch",
    )
    require(
        plan.get("schema_version") == 1
        and plan.get("engine") == "native-cython-cpp17"
        and isinstance(plan.get("frozen_request"), dict)
        and isinstance(plan.get("candidates"), list)
        and all(isinstance(row, dict) for row in plan["candidates"]),
        "invalid lifecycle witness envelope",
    )
    stops = plan.get("stopping_reasons")
    exact = plan.get("exact")
    status = plan.get("status")
    require(
        type(exact) is bool
        and isinstance(stops, list)
        and all(isinstance(s, str) for s in stops)
        and exact == (not stops)
        and (plan["termination"] == "exhausted") == exact
        and (exact or plan["termination"] in stops),
        "inconsistent lifecycle proof metadata",
    )
    require(
        status == ("optimal_proven" if plan["candidates"] else "infeasible_proven")
        if exact
        else status in ("cancelled", "unsupported", "best_found_bounded", "no_feasible_found"),
        "inconsistent lifecycle status",
    )
    raw = plan["frozen_request"]
    require(
        digest(raw) == plan.get("input_hash") and _id(plan) == plan.get("result_hash"),
        "lifecycle result hash mismatch",
    )
    families, _ = _families(raw, rules)
    rolls = _rolls(raw, families)
    require(
        plan["comparison_hash"] == _comparison(raw, rolls) and plan["paired_rolls"] == rolls,
        "lifecycle comparison mismatch",
    )
    family_map = {n: (s, o, r) for n, s, o, r in families}
    cache = {}
    for candidate in plan["candidates"]:
        family, seed = candidate["family"], candidate["roll_seed"]
        require(family in family_map and seed in rolls, "unrecognized class/roll")
        start, origin, reason = family_map[family]
        require(reason is None, "class violates the frozen profile")
        if (family, seed) not in cache:
            realized = start if seed is None else {**start, "roll_seed": seed}
            ctx = _prepare(_progress(raw, realized), rules)
            require(
                not ctx[9] and not _unknown(ctx[0].source_state, realized, encounter="encounter" in raw),
                "unproved starting damage or progression observations",
            )
            cache[family, seed] = ctx
        ctx = cache[family, seed]
        route, end = _route(ctx, candidate["progression_choices"], public_choices=True)
        require(
            not _specialized(route["checkpoints"], encounter="encounter" in raw),
            "unsupported checkpoint specialization",
        )
        require(
            (not ctx[6]["final_stage_only"] or len(route["actions"]) == len(ctx[1])) and goal_met(end, ctx[5]),
            "incomplete lifecycle progression",
        )
        d = compile_route(raw, ctx[0].source_state, route, rules, start)
        w = candidate["choices"]
        expected = _witness(
            d,
            route,
            {
                **w,
                "scores": [s["dps"] for s in candidate["checkpoints"]],
                "spent": candidate["total_spent_gold"] - route["effort"]["spent"],
            },
            family,
            origin,
            seed,
        )
        require(expected == candidate, "lifecycle replay differs from exported plan")
    return {
        "validated": True,
        "valid": True,
        "optimality_reproved": False,
        "routes_checked": len(plan["candidates"]),
        "result_hash": plan["result_hash"],
    }


def replay_build(plan, *, ruleset=None):
    """Check the serialized witnesses and identity. Search optimality requires a new search."""
    rules = _rules(ruleset)
    try:
        return _replay_build(plan, rules)
    except (KeyError, TypeError, IndexError, AttributeError, OverflowError) as exc:
        raise ValueError("malformed lifecycle witness or frozen request") from exc


def compare_builds(plans, *, ruleset=None):
    rules = _rules(ruleset)
    require(isinstance(plans, list) and len(plans) >= 2, "compare needs at least two plans")
    for p in plans:
        replay_build(p, ruleset=rules)
    require(
        len({p["comparison_hash"] for p in plans}) == 1,
        "build comparison needs the same targets, rolls and objectives",
    )
    rows = [{**r, "plan_index": i} for i, p in enumerate(plans) for r in p["candidates"]]
    keep, cap = _rank(rows, "checkpoints" in plans[0]["frozen_request"])
    return {
        "same_comparison": True,
        "ruleset_hash": rules["content_hash"],
        "candidates": keep,
        "final_checkpoint_only": cap,
        "comparisons": [
            {"result_hash": p["result_hash"], "status": p["status"], "roll_spread": p["roll_spread"]}
            for p in plans
        ],
    }
