"""Reduced-domain admission checks for a class selected before its birth rolls."""

from collections import defaultdict
from itertools import product
import json
from math import isfinite
from statistics import fmean
from time import perf_counter

from .benchmark_host import engine, host, peak_rss_bytes
from .class_document import ATTRIBUTES
from .progression import digest
from .ruleset import DATA


# Independent of the service's sorting function. A positive sign favors larger values.
PRIORITIES = (
    ("worst_clear_rate", 1),
    ("worst_survival_rate", 1),
    ("mean_clear_rate", 1),
    ("plate_weapon_materials", 1),
    ("advancement_multiplier", -1),
    ("mean_practice", -1),
    ("mean_censored_clear_fraction", -1),
)


def qualification_panel():
    panel = json.loads((DATA / "beginner-qualification-v1.json").read_bytes())
    if digest(panel) != "0dfd9aad459e7b87c065606ff6ca97c9eab240d067319dd579025d287a61a1bd":
        raise ValueError("beginner qualification inputs differ from the versioned panel")
    return panel


def class_product(domain):
    """Enumerate every declared combination in the two small, conflict-free domains."""
    required = set(domain["required_trait_ids"])
    optional = sorted(set(domain["trait_ids"]) - required)
    packages = [
        tuple(sorted(required | {t for t, take in zip(optional, selected, strict=True) if take}))
        for selected in product((False, True), repeat=len(optional))
    ]
    return {
        (race, attributes, skills, traits)
        for race in domain["race_ids"]
        for attributes in product(*(domain["attribute_domains"][a] for a in ATTRIBUTES))
        if sum(attributes) == 400
        for skills in product(*domain["skill_domains"])
        if len(set(skills)) == 12
        for traits in packages
    }


def check_case_matrix(rows, panel, stages):
    expected = set(
        product(panel["cases"], stages, panel["variants"], panel["roll_seeds"], panel["combat_seeds"])
    )
    for row in rows:
        outcomes = row["outcomes"]
        keys = {
            (r["scenario"], r["stage"], r["variant"], r["roll_seed"], r["seed"])
            for r in outcomes
            if r["status"] == "replayed"
        }
        if keys != expected or len(outcomes) != len(expected):
            raise ValueError("qualification requires each paired scenario outcome exactly once")
    return len(expected)


def _coordinates(rows):
    coordinates = {}
    for row in rows:
        identifier, metrics = row["id"], row["metrics"]
        if identifier in coordinates:
            raise ValueError("reference family identities must be unique")
        values = tuple(metrics.get(axis) for axis, _ in PRIORITIES)
        if any(type(x) not in (int, float) or not isfinite(x) for x in values):
            raise ValueError("qualification requires complete, finite paired metrics")
        coordinates[identifier] = tuple(x * sign for x, (_, sign) in zip(values, PRIORITIES, strict=True))
    return coordinates


def _frontier(coordinates):
    """A small, independent reference on comparable classes and identical opportunities."""
    points = set(coordinates.values())
    return {
        point
        for point in points
        if not any(
            other != point and all(a >= b for a, b in zip(other, point, strict=True)) for other in points
        )
    }


def role_recovery(exact_rows, admitted_rows):
    """Measure each specialist ceiling before applying the UI's distinct-build rule."""
    report = {}
    for axis in ("cap_damage_per_second", "min_hp_fraction", "mean_damage_per_sp"):
        optima = []
        for rows in (exact_rows, admitted_rows):
            values = [r["metrics"].get(axis) for r in rows]
            optima.append(max((x for x in values if x is not None), default=None))
        reference, retained = optima
        gap = reference - retained if reference is not None and retained is not None else None
        report[axis] = {
            "reference": reference,
            "retained": retained,
            "recovered": reference == retained if reference is not None else None,
            "absolute_gap": gap,
            "relative_gap": gap / abs(reference) if gap is not None and reference else None,
        }
    return report


def compare_admission(exact_rows, admitted_rows, elected):
    exact, admitted = _coordinates(exact_rows), _coordinates(admitted_rows)
    if not exact:
        raise ValueError("the reduced domain needs a feasible reference")
    if any(exact.get(name) != value for name, value in admitted.items()):
        raise ValueError("bounded family or paired metric differs from its exhaustive reference")
    best = max(exact.values())
    winners = sorted(k for k, v in exact.items() if v == best)
    found = max(admitted.values(), default=None)
    if elected != min((k for k, v in admitted.items() if v == found), default=None):
        raise ValueError("service winner differs from independent lexicographic ranking")
    first_loss = None
    if found is not None and found != best:
        for (axis, sign), reference, retained in zip(PRIORITIES, best, found, strict=True):
            if reference != retained:
                gap = reference - retained
                first_loss = {
                    "axis": axis,
                    "reference": reference * sign,
                    "retained": retained * sign,
                    "absolute_gap": gap,
                    "relative_gap": gap / abs(reference) if reference else None,
                }
                break
    exact_front = _frontier(exact)
    return {
        "enumerated": len(exact),
        "admitted": len(admitted),
        "exact_winners": winners,
        "elected": elected,
        "quality_recovered": best == found,
        "tie_break_recovered": elected == winners[0],
        "first_loss": first_loss,
        "exhaustive_distinct_pareto_vectors": len(exact_front),
        "pareto_recall": len(exact_front.intersection(admitted.values())) / len(exact_front),
        "specialist_ceilings": role_recovery(exact_rows, admitted_rows),
    }


def quality_summary(checks):
    worst = {}
    for check in checks:
        loss = check["first_loss"]
        if loss:
            worst[loss["axis"]] = max(worst.get(loss["axis"], 0), loss["absolute_gap"])
    return {
        "comparisons": len(checks),
        "missing_recommendations": sum(r["elected"] is None for r in checks),
        "winning_metric_recovery_rate": fmean(r["quality_recovered"] for r in checks),
        "deterministic_winner_recovery_rate": fmean(r["tie_break_recovered"] for r in checks),
        "mean_pareto_recall": fmean(r["pareto_recall"] for r in checks),
        "worst_first_loss_by_axis": worst,
    }


def _construction(family, skills, traits):
    start = family["start"]
    doc = start["class"]
    return (
        start["race_id"],
        tuple(doc["attributes"][k] for k in ATTRIBUTES),
        tuple(skills[name] for group in ("primary", "major", "minor") for name in doc["skills"][group]),
        tuple(
            sorted(
                traits[(p["primary"], p.get("secondary") or "")]
                for group in ("advantages", "disadvantages")
                for p in doc[group]
            )
        ),
    )


def _family_trial(families, panel, evaluate):
    start = perf_counter()
    result = evaluate(
        families, **panel, search={"wall_seconds": 0, "max_nodes": 50_000_000, "memory_bytes": 256 << 20}
    )
    elapsed = perf_counter() - start
    rows = result["comparisons"]
    if {r["id"] for r in rows} != {f["id"] for f in families}:
        raise ValueError("finite benchmark family coverage differs from the declared domain")
    cells = check_case_matrix(rows, panel, ("birth", "midgame", "cap"))
    report = {
        "elapsed_seconds": elapsed,
        "seconds_per_family": elapsed / len(families),
        "cells_per_family": cells,
        "result_hash": result["result_hash"],
        "peak_process_rss_bytes": peak_rss_bytes(),
        "diagnostics": result["diagnostics"],
        "eligible_rows": [{"id": r["id"], "metrics": r["metrics"]} for r in rows],
    }
    return rows, result["recommendation"]["id"], report


def run_beginner_benchmark():
    from .beginner import evaluate_roster
    from .beginner_classes import beginner_roster
    from .native import require_native
    from .ruleset import load_ruleset

    fixture = qualification_panel()
    rules = load_ruleset()
    skills = {r["name"]: r["id"] for r in rules["skills"]}
    traits = {(r["primary"], r.get("secondary") or ""): r["id"] for r in rules["traits"]}
    workloads = {}
    heldout = defaultdict(list)
    repetition = {}
    for name, panel in fixture["panels"].items():
        domain_name = fixture["domain_for_panel"].get(name, "domain")
        domain = fixture[domain_name]
        expected = class_product(domain)

        def admit(cap, exhaustive):
            start = perf_counter()
            roster = beginner_roster(
                "standard",
                ruleset=rules,
                roll_seeds=panel["roll_seeds"],
                domain={**domain, "top_k": cap},
                exhaustive=exhaustive,
                max_nodes=1_000_000,
            )
            elapsed = perf_counter() - start
            found = [r for r in roster["families"] if r["origin"] == "discovered"]
            return found, {
                "seconds": elapsed,
                "proof_scope": roster["proof_scope"],
                "counters": roster["counts"],
                "ids": [f["id"] for f in found],
            }

        exact, admission = admit(len(expected) + 1, True)
        census = {_construction(r, skills, traits) for r in exact}
        if (
            census != expected
            or len(census) != len(exact)
            or not admission["proof_scope"]["admission_complete"]
        ):
            raise ValueError("native enumeration differs from independent finite class census")
        exact_rows, exact_winner, exact_report = _family_trial(exact, panel, evaluate_roster)
        compare_admission(exact_rows, exact_rows, exact_winner)
        limited = {}
        for size in fixture["bounded_panel_sizes"]:
            found, screening = admit(size, False)
            rows, winner, bounded_report = _family_trial(found, panel, evaluate_roster)
            check = compare_admission(exact_rows, rows, winner)
            limited[str(size)] = {"admission": screening, "downstream": bounded_report, "quality": check}
            if name == "development" and size == fixture["bounded_panel_sizes"][0]:
                repeat_families, repeat_screen = admit(size, False)
                _, _, repeat_report = _family_trial(repeat_families, panel, evaluate_roster)
                same_screen = all(
                    repeat_screen[k] == screening[k] for k in ("ids", "counters", "proof_scope")
                )
                same_result = repeat_report["result_hash"] == bounded_report["result_hash"]
                if not same_screen or not same_result:
                    raise ValueError(
                        "Repeated fixed-work beginner search changed its result or native screening"
                    )
                repetition = {
                    "panel": name,
                    "size": size,
                    "same_ranked_result": same_result,
                    "same_screening": same_screen,
                    "result_hash": repeat_report["result_hash"],
                }
            if name.startswith("held_out"):
                heldout[str(size)].append(check)
        workloads[name] = {
            "scenario": panel,
            "domain": domain_name,
            "exhaustive_admission": admission,
            "exhaustive": exact_report,
            "bounded": limited,
        }
    return {
        "schema_version": 1,
        "suite": "beginner",
        "workers": 1,
        "host": host(),
        "engine": engine(require_native()),
        "source_sha": rules["source_sha"],
        "ruleset_hash": rules["content_hash"],
        "input_hash": digest(fixture),
        "determinism": repetition,
        "scope": fixture["scope"],
        "finite_domains": {k: fixture[k] for k in ("domain", "material_domain")},
        "workloads": workloads,
        "held_out": {size: quality_summary(checks) for size, checks in heldout.items()},
    }


def origin_profile(request, result):
    """Summarize the submitted M8 archive without copying its repeated 12k-action traces."""
    frozen = result.get("frozen_request", {})
    if (
        result.get("kind") != "lifecycle"
        or {k: v for k, v in frozen.items() if k != "class_admission"} != request
    ):
        raise ValueError("the submitted lifecycle result and frozen request differ")
    families = {entry["id"]: entry["start"] for entry in frozen["class_admission"]["families"]}
    frontier = result["paired_family_frontier"]
    policies = defaultdict(list)
    for point in frontier["points"]:
        policies[point["family"]].append({k: point[k] for k in ("selectors", "means", "rolls")})
    return {
        **{
            k: result[k]
            for k in (
                "input_hash",
                "result_hash",
                "source_sha",
                "ruleset_hash",
                "status",
                "termination",
                "counters",
                "timings",
                "class_admission",
                "paired_rolls",
                "validation",
                "gaps",
            )
        },
        "per_roll_candidates": len(result["candidates"]),
        "comparison_witnesses": len(result["comparison_witnesses"]),
        "axes": frontier["axes"],
        "policy_enumeration_complete": frontier["policy_enumeration_complete"],
        "paired_builds": [
            {
                "id": key,
                "race_id": families[key]["race_id"],
                "class": families[key]["class"],
                "policies": value,
            }
            for key, value in sorted(policies.items())
        ],
    }
