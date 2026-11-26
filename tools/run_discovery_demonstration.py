"""Reproduce the M8 comparison from a frozen discovery request and archive every result."""

import argparse
import json
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from zipfile import ZIP_DEFLATED, ZipFile

from dfo_optimizer.benchmark_host import host, peak_rss_bytes
from dfo_optimizer.build_baselines import resolve_family_baseline
from dfo_optimizer.discovery_presets import discovery_preset
from dfo_optimizer.lifecycle import compare_builds, optimize_build, replay_build
from dfo_optimizer.lifecycle_objectives import refinement_priority
from dfo_optimizer.ruleset import load_ruleset
from dfo_optimizer.workbench_files import export_job, imported


def save_run(archive, label, query):
    started = perf_counter()
    result = optimize_build(query)
    validated = replay_build(result)
    archive_doc, _ = export_job(
        {
            "result": result,
            "request": query,
            "action": "build optimize",
            "mode": "request",
            "ruleset_hash": result["ruleset_hash"],
        },
        {"archive": "1"},
    )
    checked = imported("archive", archive_doc, result["ruleset_hash"])
    if checked["warnings"] or checked["value"]["result"]["result_hash"] != validated["result_hash"]:
        raise ValueError("Archive import failed to reproduce the replayed lifecycle result")
    archive.writestr(label + ".json", json.dumps(archive_doc, separators=(",", ":"), allow_nan=False))
    summary = {
        k: result[k]
        for k in (
            "result_hash",
            "source_sha",
            "ruleset_hash",
            "input_hash",
            "status",
            "termination",
            "counters",
            "timings",
            "paired_rolls",
        )
    }
    summary.update(
        replay=validated,
        end_to_end_seconds=perf_counter() - started,
        peak_rss_bytes=peak_rss_bytes(),
        retained=len(result["candidates"]),
        gaps=result["gaps"][:3],
    )
    if result.get("class_admission"):
        summary["class_admission"] = result["class_admission"]
    rows = result["candidates"]
    if rows:
        best = max(rows, key=lambda r: refinement_priority(r, query["objective"]))
        summary["witness"] = {
            k: best[k]
            for k in (
                "family",
                "final_level",
                "effort",
                "total_spent_gold",
                "excluded_equipment",
                "checkpoints",
            )
        }
    print(label, summary["status"], summary["retained"], round(summary["end_to_end_seconds"], 2), flush=True)
    return result, summary


def cap_encounter():
    control = discovery_preset("enemy_caster")["encounter"]
    evidence = (
        "Pinned enemyBasics.js mobile 33 has level 21 and 30–170 HP. enemyGroups.js identifies the undead group. "
        "Both copies use 160 HP. Positions, Willpower, zero additional tolerance masks, timing, spell recipe, "
        "darkness and the stationary geometry are authored."
    )
    control["scenario"] = {
        "id": "two ancient liches",
        "evidence": evidence,
        "horizon_us": 30_000_000,
        "enemies": [
            {
                "id": f"Ancient Lich {n + 1}",
                "hp": 160,
                "level": 21,
                "willpower": 80,
                "category": "undead",
                "x_mm": 900 + 500 * n,
                "z_mm": 0,
                "evidence": evidence,
            }
            for n in range(2)
        ],
        "incoming": [
            {
                "kind": "bundle",
                "spell": "shaman-bolt",
                "time_us": time,
                "source": enemy,
                "evidence": "Hypothetical hostile Damage Health bundle cast on this fixed schedule.",
            }
            for enemy, time in ((0, 1_500_000), (1, 3_000_000), (0, 5_000_000), (1, 7_000_000))
        ],
    }
    control["hostile_spells"][0]["evidence"] = (
        "Authored single-effect hostile spell used by both hypothetical liches."
    )
    return control


def guided_cap():
    """Exercise the stock guided preset without adding reference families."""
    query = discovery_preset("creation_to_cap")
    started = perf_counter()
    plan = optimize_build(query)
    replay = replay_build(plan)
    witnesses = [*plan["candidates"], *plan["comparison_witnesses"]]
    covered = {k["family"] for k in plan["family_comparisons"] if k["complete_roll_set"]}
    if len(covered) < 2 or any(w["final_level"] != 45 for w in witnesses):
        raise RuntimeError("The guided cap preset requires two complete paired level-45 families")
    return {
        "request": query,
        "class_admission": plan["class_admission"],
        "family_comparisons": plan["family_comparisons"],
        "hash": plan["result_hash"],
        "status": plan["status"],
        "termination": plan["termination"],
        "counters": plan["counters"],
        "timings": plan["timings"],
        "paired_rolls": plan["paired_rolls"],
        "complete_families": len(covered),
        "replay": replay,
        "end_to_end_seconds": perf_counter() - started,
    }


def compare_panel(archive_path, families, seeds):
    """Re-import and compare each identical scenario and roll via the public service."""
    rules = load_ruleset()
    panels = {}
    with ZipFile(archive_path) as archive:
        for seed in seeds:
            for mode in ("direct", "encounter"):
                members = [f"family-{n}-seed-{seed}-{mode}.json" for n in range(1, len(families) + 1)]
                plans = []
                for name in members:
                    doc = imported("archive", json.loads(archive.read(name)), rules["content_hash"])
                    if doc["warnings"]:
                        raise ValueError("Comparison archive ruleset mismatch")
                    plans.append(doc["value"]["result"])
                ranked = compare_builds(plans, ruleset=rules)
                panels[f"seed-{seed}-{mode}"] = {
                    "same_comparison": ranked["same_comparison"],
                    "comparison_hash": plans[0]["comparison_hash"],
                    "compared": [r["result_hash"] for r in ranked["comparisons"]],
                    "retained": len(ranked["candidates"]),
                    "pareto_families": sorted({r["family"] for r in ranked["candidates"]}),
                    "final_checkpoint_only": ranked["final_checkpoint_only"],
                }
    return panels


def verify(directory):
    report = json.loads((directory / "windows-m8-discovery-demo.json").read_text(encoding="utf-8"))
    rules = load_ruleset()
    with ZipFile(directory / "windows-m8-discovery-demo.zip") as archive:
        if set(archive.namelist()) != {label + ".json" for label in report["runs"]}:
            raise ValueError("Archived runs differ from the report")
        for member in archive.namelist():
            doc = json.loads(archive.read(member))
            checked = imported("archive", doc, rules["content_hash"])
            replay = replay_build(doc["result"], ruleset=rules)
            if checked["warnings"] or replay != report["runs"][member.removesuffix(".json")]["replay"]:
                raise ValueError(f"Archived run differs from report: {member}")
            print(member, replay["routes_checked"], "independently replayed witnesses", flush=True)
    comparisons = compare_panel(
        directory / "windows-m8-discovery-demo.zip", report["families"], report["request"]["roll_seeds"]
    )
    if comparisons != report["comparisons"]:
        raise ValueError("Independent build comparison differs from report")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--request", type=Path, default=Path("examples/build-discovery-demo.json"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--verify", action="store_true", help="Import and replay the existing archives in --output"
    )
    options = p.parse_args()
    if options.verify:
        verify(options.output)
        return
    options.output.mkdir(parents=True, exist_ok=True)
    query = json.loads(options.request.read_text(encoding="utf-8"))
    report = {
        "host": host(),
        "request": query,
        "runs": {},
        "scope": "The initial early-development search admits a bounded panel on two paired birth tapes. The two highest early-evaluated admitted families by worst paired final DPS, with stable ID ties, join the three reference families in the cap comparison. The direct and encounter workloads share spells, offers, gold and development. The cap encounter starts at the attained checkpoint and evaluates an independent common fight seed. Classes with an unsupported encounter mechanic retain their gaps without a simulated combat score.",
    }
    runs = report["runs"]
    archive_path = options.output / "windows-m8-discovery-demo.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        discovery, runs["discovery"] = save_run(archive, "discovery", query)
        eligible = [f for f in discovery["family_comparisons"] if f["complete_roll_set"]]
        scores = {f["family"]: min(r["final_dps"] for r in f["rolls"]) for f in eligible}
        admitted = [
            f for f in discovery["frozen_request"]["class_admission"]["families"] if f["id"] in scores
        ]
        selected = sorted(admitted, key=lambda f: (-scores[f["id"]], f["id"]))[:2]
        if len(selected) != 2:
            raise RuntimeError("Two admitted families with complete, replayed early pairs are required")
        families = query["families"] + selected
        report["families"] = families
        del discovery
        rules = load_ruleset()
        for number, family in enumerate(families):
            start = (
                resolve_family_baseline(family["baseline_id"], rules)
                if "baseline_id" in family
                else family["start"]
            )
            canonical = {"id": family["id"], "start": {**start, "profile": "custom"}}
            for seed in query["roll_seeds"]:
                cap = discovery_preset("creation_to_cap")
                cap["progression"]["itinerary"] = {
                    **deepcopy(query["progression"]["itinerary"]),
                    "cycles": 1800,
                }
                cap.pop("class_search")
                cap.pop("class_admission_strategy")
                cap.update(families=[canonical], roll_seeds=[seed])
                cap["search"].update(max_nodes=120_000, wall_seconds=0)
                for mode in ("direct", "encounter"):
                    q = deepcopy(cap)
                    if mode == "encounter":
                        q.update(objective="clear_performance", encounter=cap_encounter())
                        q["spellbook"].pop("allow_unarmed_start", None)
                    label = f"family-{number + 1}-seed-{seed}-{mode}"
                    _, runs[label] = save_run(archive, label, q)
                    if not runs[label]["retained"] and (mode == "direct" or runs[label]["status"] != "unsupported"):
                        raise RuntimeError(f"No validated {mode} witness for {family['id']} seed {seed}")
    report["comparisons"] = compare_panel(archive_path, families, query["roll_seeds"])
    report["guided_cap"] = guided_cap()
    (options.output / "windows-m8-discovery-demo.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
