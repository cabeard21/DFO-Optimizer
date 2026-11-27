"""Budgeted beginner recommendations on a versioned, paired combat panel."""

import json
from copy import deepcopy
from importlib.resources import files
from statistics import fmean
from time import perf_counter

from .beginner import COMBAT_SEEDS, BIRTH_SEEDS, _Budget, _project, _settings, parse_request
from .beginner_classes import _family, manual_classes
from .beginner_progression import CheckpointCache
from .beginner_ranking import construction, pick_builds, ranking_key
from .beginner_report import (
    ASSUMPTIONS, LIMITATIONS, METRICS, PanelArchive, checked_metrics, compact_stage, publish,
    result_identity, retained_size,
)
from .beginner_scenarios import evaluate_matrix
from .character import _hash
from .progression_domain import require

PROFILE = "first_spellcaster_v2"
TUNING_SEED = 701
TUNING_CASES = ("physical", "resistant", "multiple", "sustained")
MAIN_VARIANTS = ("baseline", "owned_only", "higher_pressure")
RATES = ("worst_clear_rate", "worst_survival_rate", "mean_clear_rate")


def _scenarios(rules):
    from .beginner_refined_assets import asset_law

    settings = _settings(rules, BIRTH_SEEDS, COMBAT_SEEDS, None, MAIN_VARIANTS)
    cases = deepcopy(settings["scenarios"])
    caster = next(case for case in cases if case["id"] == "enemy_caster")
    for spell in caster["hostile_spells"]:
        spell["element"] = 4
    return {**settings, "profile": PROFILE, "scenarios": cases, "tuning_seed": TUNING_SEED,
            "access": ["owned", "representative", "theoretical"], "low_sp": "fresh quarter-pool entry",
            "asset_law_hash": asset_law()[1]}


def _fixtures(rules, comparison):
    archived = json.loads(files("dfo_optimizer").joinpath("data/beginner-submitted-class.json").read_text(encoding="utf-8"))
    if comparison is None:
        return [*manual_classes(ruleset=rules), *(
            _family(archived["class"], race, "submitted_archive" if race == archived["race_id"] else "race_comparison",
                    rules, BIRTH_SEEDS) for race in dict.fromkeys((archived["race_id"], 1, 5))
        )]
    ref = _family(comparison["class"], comparison["race_id"], "fast_reference", rules, BIRTH_SEEDS)
    require(ref["compliance"]["passed"] and ref["compliance"]["difficulty_points"] == -12,
            "Compare slower builds from a legal 0.30× beginner class")
    edited = []
    for label, start in (("selected", comparison), ("archive", archived)):
        doc = start["class"]
        for index, trait in enumerate(doc["disadvantages"]):
            if trait["primary"] == "forbiddenMaterial":
                relaxed = {**doc, "disadvantages": doc["disadvantages"][:index] + doc["disadvantages"][index + 1:]}
                family = _family(relaxed, start["race_id"], label + "_keeps_" + trait["secondary"], rules, BIRTH_SEEDS)
                if family["compliance"]["passed"]:
                    edited.append(family)
    archived_ref = _family(archived["class"], archived["race_id"], "archived_reference", rules, BIRTH_SEEDS)
    return [ref, archived_ref, *edited]


def _matrix(stages, cases, seeds, variants, rules, budget):
    if budget.stop():
        return {"rows": [], "coverage": {"required": 1, "replayed": 0}, "termination": budget.stop()}
    matrix = evaluate_matrix(stages, cases, seeds, variants=variants, max_events=budget.remaining(),
                             wall_seconds=max(1e-12, budget.seconds()), memory_bytes=max(1, budget.memory // 2),
                             cancel=budget.token.encounter, ruleset=rules)
    for key in ("encounter_batches", "replayed_trials"):
        budget.used[key] += matrix["counters"][key]
    budget.used["encounter_events"] += matrix["counters"]["events"]
    return matrix


def _summary(rows):
    usable = [row for row in rows if row["status"] == "replayed"]
    if not usable or len(usable) != len(rows):
        return {"draws": len(usable), "status": "incomplete"}
    elapsed = sum(r["censored_clear_us"] for r in usable)
    return {"draws": len(rows), "status": "replayed", "survival": fmean(r["survived"] for r in rows),
            "clear": fmean(r["survived"] and r["cleared"] for r in rows),
            "mean_min_hp_fraction": fmean(r["minimum_hp"] / r["max_hp"] for r in rows),
            "mean_hp_lost": fmean(r["initial_hp"] - r["ending_hp"] for r in rows),
            "dps": sum(r["damage"] for r in rows) * 1_000_000 / elapsed if elapsed else None,
            "sp_spent": fmean(r["spent_sp"] for r in rows), "sp_restored": fmean(r["restored_sp"] for r in rows),
            "melee_damage": fmean(r["physical_damage"] for r in rows), "outcomes_hash": _hash(rows)}


def _quality(metrics):
    return (metrics.get("clear", -1), metrics.get("survival", -1), metrics.get("mean_min_hp_fraction", -1),
            metrics.get("dps") or 0, metrics.get("sp_restored", 0) - metrics.get("sp_spent", 0))


def _matrix_summary(matrix):
    coverage = matrix["coverage"]
    if coverage["required"] != coverage["replayed"]:
        return {"draws": coverage["replayed"], "status": "incomplete"}
    return _summary(matrix["rows"])


def _depleted(stage):
    return {**stage, "actor": {**stage["actor"], "current_sp": 0}}


def _paths(stages, settings, rules, budget):
    from .beginner_refined_paths import variants

    cap = [stage for stage in stages if stage["stage"] == "cap"]
    choices = [variants(stage, rules) for stage in cap]
    cases = [case for case in settings["scenarios"] if case["id"] in TUNING_CASES]
    diagnostics = {}
    for name in choices[0]:
        if all(name in group for group in choices):
            trial = _matrix([choices[0][name]], cases, (TUNING_SEED,), ("baseline",), rules, budget)
            diagnostics[name] = _matrix_summary(trial)
    winner = max(diagnostics, key=lambda name: _quality(diagnostics[name]), default="none")
    tuned = [*filter(lambda stage: stage["stage"] != "cap", stages), *(group[winner] for group in choices)]
    checks = {}
    for name in diagnostics:
        matrix = _matrix([group[name] for group in choices], cases, settings["combat_seeds"],
                         ("baseline",), rules, budget)
        checks[name] = _matrix_summary(matrix)
    return tuned, {"selected": winner, "paths": checks, "tuning": diagnostics,
                   "coverage": "Soulbinder records the untrapped kill refund. Soul Lance and trap-enhanced returns are outside this panel."}


def _prepare_stages(stages, mode, settings, rules, budget):
    from .beginner_refined_assets import prepare, prepare_options, tune

    cases = [case for case in settings["scenarios"] if case["id"] in ("physical", "low_sp")]
    sustained = next(case for case in settings["scenarios"] if case["id"] == "sustained")
    results = []
    for stage in stages:
        options = prepare_options({**stage, "refined_entry": True}, mode, rules, budget)
        owned = prepare(stage, "owned", rules, budget)
        options = [{**candidate, "refined_entry": True, "variants": {"owned_only": owned}}
                   for candidate in options]
        if stage["stage"] == "birth":
            results.append(options[0])
            continue
        scores = []
        for candidate in options:
            matrix = _matrix([_depleted(candidate)], cases, (TUNING_SEED,), ("baseline",), rules, budget)
            scores.append(_quality(_matrix_summary(matrix)))
        selected = options[max(range(len(options)), key=scores.__getitem__)]
        results.append(tune(selected, sustained, rules, budget))
    return results


def _evaluate(family, cache, settings, rules, budget):
    start, permanent = family["start"], family["compliance"]
    base = {"id": family["id"], "origin": family["origin"], "race_id": start["race_id"],
            "race": permanent["race"], "class": start["class"], "permanent": permanent}
    stages, rolls, policy, gap = _project(family, cache, settings, budget)
    if gap or budget.stop():
        return {**base, "status": "incomplete", "reason": str(gap or budget.stop())}
    practical = _prepare_stages(stages, "representative", settings, rules, budget)
    practical, arcane = _paths(practical, settings, rules, budget)
    outcomes, gear, paired = _evaluate_access(stages, practical, arcane, settings, rules, budget)
    panel = outcomes["rows"]
    coverage = outcomes["coverage"]
    if coverage["required"] != coverage["replayed"] or not panel:
        reason = next((r["reason"] for r in panel if r["status"] == "unsupported"), outcomes["termination"])
        return {**base, "status": "incomplete", "reason": str(reason), "coverage": coverage}
    ancillary = [gear["theoretical"], *arcane["paths"].values(), *paired,
                 *(r for stages in gear["same_spellbook"].values() for r in stages.values()),
                 *(r for stages in gear["no_magicka"].values() for r in stages.values())]
    if any(r["status"] != "replayed" for r in ancillary):
        return {**base, "status": "incomplete", "reason": budget.stop() or "Incomplete capped comparison"}
    for roll in rolls:
        roll["stages"] = [compact_stage(s) for s in practical if s["roll_seed"] == roll["seed"]]
    progress = {"policy": policy, "rolls": rolls, "representative_seed": BIRTH_SEEDS[0]}
    return {**base, "status": "replayed", "coverage": coverage, "outcomes": panel,
            "outcomes_hash": _hash(panel), "progression": progress,
            "metrics": checked_metrics(permanent, rolls, panel),
            "refinement": {"arcane": arcane, "gear": gear,
                           "magic_pressure": {stage: _summary([r for r in panel if r["scenario"] == "enemy_caster"
                                               and r["stage"] == stage and r["variant"] == "baseline"])
                                              for stage in ("birth", "midgame", "cap")}}}


def _evaluate_access(original, practical, arcane, settings, rules, budget):
    from .beginner_refined_assets import hold_book
    from .beginner_refined_paths import variants

    matrix = _matrix(practical, settings["scenarios"], settings["combat_seeds"], MAIN_VARIANTS, rules, budget)
    rows = matrix["rows"]
    stages = {s["stage"] for s in practical}
    match = {(r["stage"], r["scenario"], r["roll_seed"], r["seed"]) for r in rows if r["variant"] == "owned_only"}
    gear = {name: {stage: _summary([r for r in rows if r["variant"] == variant and r["stage"] == stage
                                    and (stage, r["scenario"], r["roll_seed"], r["seed"]) in match])
                   for stage in sorted(stages)} for name, variant in (("representative", "baseline"), ("owned", "owned_only"))}
    gear["stage_loadouts"] = [compact_stage(s)["loadout_details"] for s in practical if s["roll_seed"] == BIRTH_SEEDS[0]]
    gear["access"] = {s["stage"]: s.get("asset_access", {}) for s in practical if s["roll_seed"] == BIRTH_SEEDS[0]}
    gear_cases = [case for case in settings["scenarios"] if case["id"] in ("physical", "low_sp", "sustained")]
    owned_match = []
    for selected in practical:
        fork = hold_book(selected["variants"]["owned_only"], selected)
        owned_match.append({**fork, "refined_entry": True, "actor": selected["actor"],
                            "spell_policy": selected.get("spell_policy", "steady"),
                            "state": {**fork["state"], "known": selected["state"]["known"],
                                      "arcane_path": selected["state"]["arcane_path"]}})
    fixed_book = _matrix(owned_match, gear_cases, settings["combat_seeds"], ("baseline",), rules, budget)
    paired = [_matrix_summary(fixed_book)]
    case_ids = {case["id"] for case in gear_cases}
    gear["same_spellbook"] = {stage: {
        "representative": _summary([r for r in rows if r["stage"] == stage and r["variant"] == "baseline" and r["scenario"] in case_ids]),
        "owned": _summary([r for r in fixed_book["rows"] if r["stage"] == stage])} for stage in sorted(stages)}
    theoretical = _prepare_stages([s for s in original if s["stage"] == "cap"], "theoretical", settings, rules, budget)
    path = arcane["selected"]
    theoretical = [variants(s, rules).get(path, s) for s in theoretical]
    theoretical_result = _matrix(theoretical, settings["scenarios"], settings["combat_seeds"], ("baseline",), rules, budget)
    gear["theoretical"] = _matrix_summary(theoretical_result)
    gear["theoretical_loadout"] = compact_stage(theoretical[0])["loadout_details"]
    physical = next(case for case in settings["scenarios"] if case["id"] == "physical")
    gear["no_magicka"] = {}
    for name, pool in (("representative", practical), ("owned", owned_match), ("theoretical", theoretical)):
        fallback = _matrix([_depleted(s) for s in pool], [physical], settings["combat_seeds"], ("baseline",), rules, budget)
        paired.append(_matrix_summary(fallback))
        gear["no_magicka"][name] = {stage: _summary([r for r in fallback["rows"] if r["stage"] == stage])
                                     for stage in sorted({s["stage"] for s in pool})}
    return matrix, gear, paired


def _selection(rows):
    leader, _ = pick_builds(rows)
    if leader is None:
        return None, []
    best = leader["metrics"]
    close = [r for r in rows if all(r["metrics"][k] >= best[k] - .05 for k in RATES)
             and (r["metrics"]["cap_damage_per_second"] or 0) >= .95 * (best["cap_damage_per_second"] or 0)]

    def flexibility(row):
        gear = row["refinement"]["gear"]
        access = row["permanent"]["catalog_eligibility"]["by_family"]
        owned = gear["owned"]
        upgrades = sum(len(set(pool.get("eligible_weapon_metals", ())) & set(pool.get("eligible_plate_metals", ())))
                       for pool in gear["access"].values())
        return (-upgrades, -row["metrics"]["plate_weapon_materials"], -sum(x["eligible"] for x in access.values()),
                -sum(x.get("clear", 0) for x in owned.values()), ranking_key(row))

    winner = min(close, key=flexibility)
    _, alternatives = pick_builds(rows, preferred=winner)
    if leader["id"] != winner["id"]:
        alternatives = [{**leader, "role": "Combat lead", "alternative_axis": "mean_clear_rate"},
                        *(r for r in alternatives if construction(r) != construction(leader))]
    return winner, alternatives[:3]


def _public(req, settings, rules, budget, archive, first, termination):
    slower = "compare_slower" in req
    if slower:
        leader, others, sensitivity = None, [], []
    else:
        leader, others, sensitivity = publish(archive, _selection)
    checked = [r for r in archive.rows if r["status"] == "replayed"]
    summary = ("Compare these slower classes against your checked 0.30× reference."
               if slower else
               f"Choose {leader['race']} and import the class. Close-scoring builds are ranked by practical equipment flexibility."
               if leader else "The run has no fully checked class on the required panel.")
    result = {"schema_version": 2, "kind": "beginner_recommendation", "profile": PROFILE,
              "source_sha": rules["source_sha"], "ruleset_hash": rules["content_hash"], "frozen_request": req,
              "evaluation": settings, "comparison_hash": _hash(settings), "recommendation": leader,
              "alternatives": others, "comparisons": archive.rows, "sensitivity": sensitivity,
              "slower_comparison": archive.rows if slower else [], "summary": summary,
              "sensitivity_notes": [], "matched_decisions": [],
              "assumptions": [*ASSUMPTIONS,
                              "Representative checkpoints are independent conditional equipment and spell-access scenarios. No drop or purchase availability is claimed.",
                              "Low-magicka fights start fresh at no more than a quarter of capacity. The theoretical panel has separate equipment and spell access."],
              "limitations": [*LIMITATIONS, "The capped choices cover supported ordinary combat. High Elf paralysis immunity and Wood Elf archery are outside this scenario panel."],
              "metric_definitions": {**METRICS, "selection": "Close combat results favor gear flexibility and owned-gear clear performance."},
              "status": "cancelled" if termination == "cancelled" else "best_found_bounded" if checked else "incomplete",
              "termination": termination, "exact": False,
              "diagnostics": {**budget.used, "nodes": budget.nodes, "fully_evaluated": len(checked), "retained_bytes": archive.bytes},
              "timings": {"elapsed_seconds": perf_counter() - budget.start, "first_validated_seconds": first}}
    return {**result, "result_hash": result_identity(result)}


def _screen(family, cache, settings, rules, budget):
    start = {**family["start"], "roll_seed": BIRTH_SEEDS[0]}
    value = cache.project(start, levels=(1,), family=family["id"], max_nodes=budget.remaining(),
                          wall_seconds=max(1e-12, budget.seconds()), memory_bytes=max(1, budget.memory // 4),
                          cancel=budget.token.lifecycle.progression_token)
    if value["status"] != "complete":
        return {}
    cases = [case for case in settings["scenarios"] if case["id"] in ("physical", "enemy_caster", "multiple")]
    trial = _matrix(value["checkpoints"], cases, (TUNING_SEED,),
                    ("baseline",), rules, budget)
    return _summary(trial["rows"])


def _waves(req, rules, budget, cache, settings, seen, controls):
    from .beginner_classes import refined_roster

    mode = req["thoroughness"]
    slower = "compare_slower" in req
    wave = 0
    while not budget.stop():
        roster = refined_roster(mode, ruleset=rules, roll_seeds=BIRTH_SEEDS, wave=wave, slower=slower,
                               max_nodes=max(1, budget.remaining() // 5), memory_bytes=max(1, budget.memory // 4),
                               wall_seconds=max(1e-12, budget.seconds()), cancel=budget.token.lifecycle.class_token)
        counts = roster["counts"]
        budget.used["class_nodes"] += counts["nodes"]
        for key in ("screened", "legal"):
            budget.used["class_" + key] += counts[key]
        budget.used["waves"] += 1
        generated = [f for f in roster["families"] if f["origin"] == "discovered" and f["id"] not in seen]
        budget.used["generated_admitted"] += len(generated)
        head, tail = (controls[:2], controls[2:]) if slower and wave == 0 else (controls, [])
        yield from head
        if not generated:
            yield from tail
            return
        batch_size = {"quick": 8, "standard": 12, "thorough": 20}[mode]
        for index in range(0, len(generated), batch_size):
            batch = generated[index:index + batch_size]
            scores = {}
            for family in batch:
                if budget.stop():
                    return
                scores[family["id"]] = _screen(family, cache, settings, rules, budget)
                budget.used["combat_screened"] += 1
            promoted = sorted(batch, key=lambda f: _quality(scores[f["id"]]), reverse=True)
            yield from promoted[:max(1, len(batch) // 2)]
            if tail:
                yield from tail
                tail = []
            yield from promoted[max(1, len(batch) // 2):]
        controls = []
        wave += 1
        if mode == "quick" or slower:
            return


def run(req, rules, token, *, on_incumbent=None, fixed=None):
    budget = _Budget(req["search"], token)
    settings = _scenarios(rules)
    budget.memory -= retained_size(settings, set())
    cache = CheckpointCache(rules, cache_bytes=max(0, min(16 << 20, budget.memory // 8)))
    archive, seen, first, stop = PanelArchive(), set(), None, None
    controls = _fixtures(rules, req.get("compare_slower")) if fixed is None else []
    families = _waves(req, rules, budget, cache, settings, seen, controls) if fixed is None else fixed
    for family in families:
        if budget.stop():
            break
        if family["id"] in seen or not family["compliance"]["passed"]:
            continue
        seen.add(family["id"])
        row = _evaluate(family, cache, settings, rules, budget)
        if not archive.append(row, budget.memory // 3):
            stop = "memory_limit"
            break
        if row["status"] == "replayed" and first is None:
            first = perf_counter() - budget.start
            if on_incumbent and "compare_slower" not in req:
                on_incumbent(_public(req, settings, rules, budget, archive, first, "checked_preview"))
    return _public(req, settings, rules, budget, archive, first, stop or budget.stop() or "panel_complete")


def replay(result, rules, token):
    req = parse_request(result["frozen_request"])
    require(result.get("kind") == "beginner_recommendation" and result.get("schema_version") == 2
            and result.get("exact") is False and result.get("result_hash") == result_identity(result)
            and req == result["frozen_request"] and result["evaluation"] == _scenarios(rules)
            and result["comparison_hash"] == _hash(result["evaluation"])
            and result["ruleset_hash"] == rules["content_hash"] and result["source_sha"] == rules["source_sha"],
            "Refined recommendation identity mismatch")
    rows = [r for r in result["comparisons"] if r["status"] == "replayed"]
    require(len({r["id"] for r in rows}) == len(rows) <= 2048, "Invalid checked recommendation roster")
    families = [_family(r["class"], r["race_id"], r["origin"], rules, BIRTH_SEEDS) for r in rows]
    if "compare_slower" not in req:
        require(all(f["compliance"]["difficulty_points"] == -12 for f in families), "Invalid 0.30× roster")
    checked = run({**req, "search": {**req["search"], "wall_seconds": 0, "max_nodes": 500_000_000}},
                  rules, token, fixed=families)
    if token.cancelled():
        return {"verified": False, "status": "cancelled", "result_hash": result["result_hash"]}
    require(checked["comparisons"] == rows and all(checked[k] == result[k] for k in
            ("recommendation", "alternatives", "sensitivity", "summary", "assumptions", "limitations", "metric_definitions"))
            and result["slower_comparison"] == (result["comparisons"] if "compare_slower" in req else []),
            "Independent refined recommendation replay differs")
    return {"verified": True, "result_hash": result["result_hash"], "families_checked": len(rows),
            "outcomes_checked": sum(r["coverage"]["replayed"] for r in rows),
            "scope": "Paired outcomes and recommendations from the fully covered roster."}
