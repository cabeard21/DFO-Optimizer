"""Verify serialized build witnesses against the frozen lifecycle services."""
from collections import defaultdict

from .progression import digest, goal_met
from .progression_replay import require


def replay_document(plan, rules):
    from .lifecycle import (_comparison, _families, _id, _prepare, _progress, _rolls, _route,
                            _specialized, _unknown, _witness, compile_route)

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
    undefined = (not plan["candidates"] and bool(plan.get("final_checkpoint_witnesses")) and
                 plan["frozen_request"].get("objective") in ("damage_per_sp", "resource_sustain"))
    require(
        status == ("optimal_proven" if plan["candidates"] else "no_defined_objective" if undefined else "infeasible_proven")
        if exact
        else status in ("cancelled", "unsupported", "best_found_bounded", "no_feasible_found") or undefined and status == "no_defined_objective",
        "inconsistent lifecycle status",
    )
    raw = plan["frozen_request"]
    require(
        digest(raw) == plan.get("input_hash") and _id(plan) == plan.get("result_hash"),
        "lifecycle result hash mismatch",
    )
    families, _ = _families(raw, rules)
    from .lifecycle_admission import verify_admissions
    verify_admissions(plan, rules)
    rolls = _rolls(raw, families)
    require(
        plan["comparison_hash"] == _comparison(raw, rolls) and plan["paired_rolls"] == rolls,
        "lifecycle comparison mismatch",
    )
    family_map = {n: (s, o, r) for n, s, o, r in families}
    witnesses = [*plan["candidates"], *plan.get("comparison_witnesses", [])]
    if "family_comparisons" in plan:
        from .lifecycle_comparisons import verify_comparisons
        verify_comparisons(plan, witnesses, family_map)
    witnesses.extend(plan.get("final_checkpoint_witnesses", []))
    groups = defaultdict(lambda: defaultdict(list))
    for candidate in witnesses:
        family, seed = candidate["family"], candidate["roll_seed"]
        require(family in family_map and seed in rolls, "unrecognized class/roll")
        groups[family, seed][tuple(candidate["progression_choices"])].append(candidate)
    for (family, seed), route_rows in groups.items():
        start, origin, reason = family_map[family]
        require(reason is None, "class violates the frozen profile")
        realized = start if seed is None else {**start, "roll_seed": seed}
        ctx = _prepare(_progress(raw, realized, rules), rules)
        require(
            not ctx[9] and not _unknown(ctx[0].source_state, realized, encounter="encounter" in raw),
            "unproved starting damage or progression observations",
        )
        for choices, members in route_rows.items():
            route, end = _route(ctx, list(choices), public_choices=True,
                                lifecycle=bool(raw.get("class_admission", {}).get("strategy") or "hp_roll_state" in ctx[0].source_state))
            require(
                not _specialized(route["checkpoints"], encounter="encounter" in raw),
                "unsupported checkpoint specialization",
            )
            require(
                (not ctx[6]["final_stage_only"] or len(route["actions"]) == len(ctx[1])) and goal_met(end, ctx[5]),
                "incomplete lifecycle progression",
            )
            d = compile_route(raw, ctx[0].source_state, route, rules, realized)
            for candidate in members:
                recorded = {**candidate["choices"], "scores": [s["dps"] for s in candidate["checkpoints"]],
                            "spent": candidate["total_spent_gold"] - route["effort"]["spent"]}
                expected = _witness(d, route, recorded, family, origin, seed)
                require(expected == candidate, "lifecycle replay differs from exported plan")
    return {
        "validated": True,
        "valid": True,
        "optimality_reproved": False,
        "routes_checked": len(witnesses),
        "result_hash": plan["result_hash"],
    }
