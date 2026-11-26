"""Search and independently replay frozen, stage-specific online spellcasting builds."""

from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from time import perf_counter
import math

from .lifecycle_domain import catalog, compile_route
from .lifecycle_replay import replay_choices
from .lifecycle_objectives import OBJECTIVES, check_native_metrics, ranking_coordinates, validate_objective
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
        "class_admission_strategy",
        "objective",
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
    validate_objective(raw)
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
    from .lifecycle_admission import strategy
    strategy(raw)
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


def _admit_classes(raw, rules, token, limits, begin, frozen):
    from .lifecycle_admission import ClassAdmission, diagnostic_panel, strategy

    if strategy(raw):
        request = {k: v for k, v in raw.items() if k != "class_admission"}
        admission = ClassAdmission(request, rules, token, limits, begin)
        admission.initial()
        return admission.freeze(), admission
    return (raw if frozen else diagnostic_panel(raw, rules, token)), None


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
            **({"objective": raw["objective"]} if raw.get("objective", "legacy") != "legacy" else {}),
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
            **({"class_profiles": sorted(profiles)} if "custom" in profiles and raw.get("objective", "legacy") == "legacy" else {}),
        }
    )


def _progress(raw, start, rules=None):
    progression = raw["progression"]
    if "itinerary" in progression:
        from .discovery_presets import bind_itinerary
        progression = bind_itinerary(progression, start, rules)
    return {
        **progression,
        "start": start,
        "search": {"final_stage_only": True, **progression.get("search", {}), "retain_states": True},
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
    check_native_metrics(row, steps, d.objective)
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
        objective=d.objective,
        wellspring=[sum(line["value"] for line in it.item.get("affixes", []) if line["id"] == "wellspring")
                    for it in d.domain.items] if d.encounters else None,
        cancel=token,
        **opts,
    )


def _group(row, explicit):
    return row["roll_seed"], tuple(p["stage"] if explicit else p["level"] for p in row["checkpoints"])


def _rank(rows, explicit, objective="legacy", cap_witnesses=None):
    from . import _lifecycle

    groups = defaultdict(list)
    for row in rows:
        groups[_group(row, explicit)].append(row)
    keep = []
    cap = []
    for members in groups.values():
        coords = [ranking_coordinates(r, objective) for r in members]
        indices = _lifecycle.frontier_indices(coords)
        # A free cast or unfinished fight has no denominator or eligible ending pool.
        if objective in ("damage_per_sp", "resource_sustain"):
            indices = [j for j in indices if coords[j][0] >= 0]
        keep.extend(members[j] for j in indices)
        best = max(r["checkpoints"][-1]["dps"] for r in members)
        if cap_witnesses is not None:
            selected = set(indices)
            cap_witnesses.extend(r for i, r in enumerate(members)
                                 if i not in selected and r["checkpoints"][-1]["dps"] == best)
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
                *(("sensitivity_budget",) if "sensitivity_budget" in plan else ()),
                *(("objective", "final_checkpoint_witnesses") if "objective" in plan else ()),
                *(("class_admission",) if "class_admission" in plan else ()),
                *(("family_comparisons", "comparison_witnesses") if "family_comparisons" in plan else ()),
                *(("paired_family_frontier",) if "paired_family_frontier" in plan else ()),
            )
        }
    )


def _run(request, rules, base_dir, replan, cancel, *, scope=None, frozen=False, on_incumbent=None):
    from . import _lifecycle

    begin = perf_counter()
    token = cancel if cancel is not None else _lifecycle.CancelToken()
    if scope is None:
        raw = request if frozen else _freeze(request, rules, base_dir, replan)
        limits = _controls(raw)
        raw, admission = _admit_classes(raw, rules, token, limits, begin, frozen)
        families, truncated = _families(raw, rules)
        rolls = _rolls(raw, families)
        prospective = raw.get("objective", "legacy") != "legacy" and rolls != [None]
        if admission is not None or prospective or limits["max_nodes"] and len(families) * len(rolls) > 1:
            from .lifecycle_refinement import refine_families

            def search_family(family, seed, allocation):
                return _run(raw, rules, base_dir, replan, token, scope=(raw, allocation, [family], [seed]))

            return refine_families(raw, rules, families, rolls, limits, truncated, token, begin, search_family,
                                   admission=admission, on_incumbent=on_incumbent)
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
            pquery = _progress(raw, start, rules)
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
            internal = {"_lifecycle": True} if raw.get("class_admission", {}).get("strategy") or pquery.get("project_creation_vitals") else {}
            planned = plan_progression(pquery, ruleset=rules, cancel=token.progression_token, **internal)
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
                if d.encounter_gaps:
                    term.append("unsupported")
                    gaps.append({"family":name, "roll_seed":seed, "kind":"unsupported_options",
                                 "reasons":list(d.encounter_gaps)})
                    if not d.scripts:
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
    return _finish(raw, rules, rolls, rows, gaps, counters, term, first, begin, len(rows),
                   internal=scope is not None and bool(raw.get("class_admission", {}).get("strategy")))


def _finish(raw, rules, rolls, rows, gaps, counters, term, first, begin, checked, *, internal=False):
    objective = raw.get("objective", "legacy")
    cap_witnesses = None if objective == "legacy" else []
    kept, cap = _rank(rows, "checkpoints" in raw, objective, cap_witnesses)
    termination = "cancelled" if "cancelled" in term else next(iter(term), "exhausted")
    measured = {"termination": termination, "stopping_reasons": sorted(set(term)), "candidates": kept,
                "gaps": gaps, "counters": counters, "validation": {"routes_checked": checked},
                "timings": {"first_validated_seconds": first, "elapsed_seconds": perf_counter() - begin}}
    if cap_witnesses is not None:
        measured["final_checkpoint_witnesses"] = cap_witnesses
    if internal:
        return measured
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
    if rows and not kept and termination != "cancelled":
        status = "no_defined_objective"
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
        **measured,
        "roll_spread": _spread(rows, rolls),
        "final_checkpoint_only": cap,
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
    if raw.get("objective", "legacy") != "legacy":
        plan["objective"] = {"id": objective, "definition": OBJECTIVES[objective]}
    plan["families"] = plan["roll_spread"]
    plan["budget_scope"] = (
        "Lifecycle nodes cover progression and joint combat. Native class admission has its own reported limits."
    )
    plan["result_hash"] = _id(plan)
    return plan


def _sensitivity(raw, rules, base_dir, replan, cancel, on_incumbent=None):
    if isinstance(raw, dict) and raw.get("sensitivity"):
        from .lifecycle_admission import strategy
        if strategy(raw):
            from .discovery_sensitivity import run_variants

            def run(query, *, on_incumbent=None):
                return _run(query, rules, base_dir, replan, cancel, on_incumbent=on_incumbent)

            plan = run_variants(raw, run, cancel, on_incumbent)
            plan["result_hash"] = _id(plan)
            return plan
    plan = _run(raw, rules, base_dir, replan, cancel, on_incumbent=on_incumbent)
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


def optimize_build(request, ruleset=None, *, base_dir=None, cancel=None, on_incumbent=None):
    return _sensitivity(request, _rules(ruleset), base_dir, False, cancel, on_incumbent)


def replan_build(request, ruleset=None, *, base_dir=None, cancel=None):
    return _sensitivity(request, _rules(ruleset), base_dir, True, cancel)




def replay_build(plan, *, ruleset=None):
    """Check the serialized witnesses and identity. Search optimality requires a new search."""
    rules = _rules(ruleset)
    try:
        from .lifecycle_archive import replay_document
        return replay_document(plan, rules)
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
    rows = [{**r, "plan_index": i} for i, p in enumerate(plans)
            for r in (*p["candidates"], *p.get("final_checkpoint_witnesses", []))]
    reference = plans[0]["frozen_request"]
    keep, cap = _rank(rows, "checkpoints" in reference, reference.get("objective", "legacy"))
    paired = {}
    if all("paired_family_frontier" in p for p in plans):
        from .lifecycle_family_frontier import compare_paired
        paired["paired_family_frontier"] = compare_paired(plans)
    return {
        "same_comparison": True,
        "ruleset_hash": rules["content_hash"],
        "candidates": keep,
        "final_checkpoint_only": cap,
        **paired,
        "comparisons": [
            {"result_hash": p["result_hash"], "status": p["status"], "roll_spread": p["roll_spread"]}
            for p in plans
        ],
    }
