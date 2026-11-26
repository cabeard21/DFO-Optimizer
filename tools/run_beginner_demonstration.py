"""Reproduce the beginner recommendations, paired comparison and game class exports."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from zipfile import ZIP_DEFLATED, ZipFile

from dfo_optimizer.benchmark_host import host, peak_rss_bytes
from dfo_optimizer.beginner_benchmark import origin_profile
from dfo_optimizer.classes import export_class, import_class
from dfo_optimizer.lifecycle import replay_build
from dfo_optimizer.workbench_files import export_job, imported


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode("utf8")


def save_origin(directory, request_path, result_path):
    from dfo_optimizer.beginner_creation import compliance
    from dfo_optimizer.ruleset import load_ruleset

    request_bytes, result_bytes = request_path.read_bytes(), result_path.read_bytes()
    request, result = json.loads(request_bytes), json.loads(result_bytes)
    report = origin_profile(request, result)
    started = perf_counter()
    report.update(
        independent_replay=replay_build(result),
        replay_elapsed_seconds=perf_counter() - started,
        request_file_sha256=sha256(request_bytes).hexdigest(),
        result_file_sha256=sha256(result_bytes).hexdigest(),
        original_result_bytes=len(result_bytes),
        request=request,
    )
    rules = load_ruleset()
    for row in report["paired_builds"]:
        verdict = compliance(row["class"], row["race_id"], rules, report["paired_rolls"])
        row["beginner_profile"] = {
            k: verdict[k] for k in ("passed", "race", "failures", "plate_weapon_materials", "backup_weapons")
        }
    (directory / "m9-m8-submitted-origin.json").write_bytes(json_bytes(report))


def save_run(directory, thoroughness):
    from dfo_optimizer.beginner import recommend_build, replay_recommendation

    query = {"thoroughness": thoroughness}
    started = perf_counter()
    result = recommend_build(query)
    elapsed = perf_counter() - started
    winner = result.get("recommendation")
    if not winner:
        raise ValueError(f"{thoroughness} did not return a fully qualified beginner build")
    replay = replay_recommendation(result)
    envelope, filename = export_job({"action": "build recommend", "request": query, "result": result,
                                     "ruleset_hash": result["ruleset_hash"], "mode": "request"}, {"archive": "1"})
    if imported("archive", envelope, result["ruleset_hash"])["warnings"]:
        raise ValueError("The recommendation archive has incompatible rules")
    path = directory / f"m9-{thoroughness}-recommendations.zip"
    with ZipFile(path, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("request.json", json_bytes(query))
        archive.writestr("result.json", json_bytes(result))
        archive.writestr("replay.json", json_bytes(replay))
        archive.writestr(filename, json.dumps(envelope, separators=(",", ":"), allow_nan=False))
        for i, row in enumerate([winner, *result.get("alternatives", ())]):
            doc = export_class(row["class"])
            if not import_class(doc, race=row["race_id"], profile="custom")["create_legal"]:
                raise ValueError("recommendation fails the game's character creation checks")
            name = "recommended" if not i else f"alternative-{i}"
            files = {
                f"{name}.dfclass.json": json_bytes(doc),
                f"{name}-checklist.txt": row["guide"]["text"].encode("utf8"),
            }
            for filename, contents in files.items():
                archive.writestr(filename, contents)
                if thoroughness == "standard" and i == 0:
                    (directory / ("m9-standard-" + filename)).write_bytes(contents)
    return {
        "request": query,
        "elapsed_seconds": elapsed,
        "peak_rss_bytes": peak_rss_bytes(),
        "rss_scope": "Process peak through service, independent replay and class export.",
        "host": host(),
        "archive": path.name,
        "archive_sha256": sha256(path.read_bytes()).hexdigest(),
        "fully_evaluated_by_origin": dict(
            Counter(row["origin"] for row in result["comparisons"] if row["status"] == "replayed")
        ),
        "replay": replay,
        **{
            k: result[k]
            for k in (
                "status",
                "termination",
                "ruleset_hash",
                "source_sha",
                "result_hash",
                "timings",
                "diagnostics",
                "sensitivity",
                "assumptions",
                "limitations",
            )
        },
        "picks": [
            {k: row[k] for k in ("id", "role", "race", "metrics")}
            for row in [winner, *result.get("alternatives", ())]
        ],
        "comparisons": [
            {k: row[k] for k in ("id", "origin", "status", "reason", "race", "metrics") if k in row}
            for row in result.get("comparisons", ())
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--origin-request", type=Path, help="submitted M8 request JSON")
    parser.add_argument("--origin-result", type=Path, help="submitted M8 lifecycle result JSON")
    parser.add_argument("--origin-only", action="store_true", help="replay the original M8 archive only")
    parser.add_argument("--thoroughness", choices=("quick", "standard", "thorough"))
    args = parser.parse_args()
    if bool(args.origin_request) != bool(args.origin_result) or args.origin_only and not args.origin_request:
        parser.error("supply both original M8 files to profile them")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.origin_request:
        save_origin(args.output, args.origin_request, args.origin_result)
    if args.origin_only:
        return
    if not args.thoroughness:
        for mode in ("quick", "standard", "thorough"):
            subprocess.run(
                [sys.executable, __file__, "--output", str(args.output), "--thoroughness", mode], check=True
            )
        return
    report = save_run(args.output, args.thoroughness)
    (args.output / f"m9-{args.thoroughness}-comparison.json").write_bytes(json_bytes(report))
    print(args.thoroughness, report["picks"][0]["race"], report["elapsed_seconds"], flush=True)


if __name__ == "__main__":
    main()
