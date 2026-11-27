"""Compare two installed wheels on the same host using identical frozen workloads."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
import tempfile
import venv


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def command(executable, *args, directory, env, payload=None):
    process = subprocess.run([executable, *args], cwd=directory, env=env, text=True,
                             input=payload, stdout=subprocess.PIPE, check=True)
    return json.loads(process.stdout)


@contextmanager
def install_directory(path):
    if path is None:
        with tempfile.TemporaryDirectory(prefix="dfo-paired-bench-") as temporary:
            yield Path(temporary)
        return
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=False)
    yield path


def install(directory, wheel, env, *, driver_pip=False):
    venv.EnvBuilder(with_pip=not driver_pip).create(directory)
    bindir = directory / ("Scripts" if os.name == "nt" else "bin")
    python = bindir / ("python.exe" if os.name == "nt" else "python")
    installer = [sys.executable, "-I", "-m", "pip", "--python", python] if driver_pip else [python, "-I", "-m", "pip"]
    subprocess.run([*installer, "install", "--no-index", "--no-deps", "--no-cache-dir", "--no-compile", wheel],
                   check=True, cwd=directory, env=env, stdout=subprocess.DEVNULL)
    return python


def summarize(python, suite, directory, env):
    prefix = ("-I", "-m", "dfo_optimizer.cli")
    report = command(python, *prefix, "benchmark", "--suite", suite, "--workers", "1",
                     directory=directory, env=env)
    compact = {key: report[key] for key in ("suite", "workload_version", "ruleset_hash",
                                            "source_sha", "peak_rss_bytes") if key in report}
    samples = {}
    for name, row in report["workloads"].items():
        if suite == "encounter":
            for field in ("ruleset_hash", "source_sha"):
                if compact.setdefault(field, row[field]) != row[field]:
                    raise ValueError(f"{suite} workloads differ on {field}")
        evidence = {k: row[k] for k in ("rows", "checksum", "nodes", "leaves", "pruned", "quality",
                                        "verified", "returned", "status", "termination", "frontier",
                                        "final_levels", "validation", "eligible_trait_count",
                                        "policies_checked", "seeds") if k in row}
        evidence["counters"] = {k: v for k, v in row.get("counters", {}).items()
                                if "seconds" not in k and "bytes" not in k}
        inputs = {k: row[k] for k in ("request", "context", "recipes", "input_patterns", "copies") if k in row}
        evidence["input_sha256"] = row.get("input_hash") if suite == "encounter" else digest(inputs)
        if name == "mechanics_batch":
            evidence["batch_sha256"] = row["result_sha256"]
        if name in ("class_exact", "class_bounded"):
            actual = command(python, *prefix, "class", "optimize", "--request", "-",
                             directory=directory, env=env, payload=json.dumps(row["request"]))
            if actual["result_hash"] != row["result_sha256"]:
                raise ValueError(f"{name} differed when replaying the benchmark request")
            # Class IDs bind the ruleset hash. Compare each external race and
            # ordered game document independently of changes to the ruleset.
            evidence["ordered_classes_sha256"] = digest([
                [candidate["race_id"], candidate["class_doc"]] for candidate in actual["candidates"]])
        samples[name] = {"p50_ms": 1000 * row["warm"]["p50_seconds"], "evidence": evidence,
                         "result_sha256": row.get("result_sha256", row.get("result_hash"))}
    return {**compact, "workloads": samples}, report["host"]


def compare(runs):
    result = {}
    for suite in sorted({r["suite"] for r in runs}):
        sample = [r for r in runs if r["suite"] == suite]
        names = sample[0]["workloads"].keys()
        if any(r["workload_version"] != sample[0]["workload_version"] or r["workloads"].keys() != names
               for r in sample):
            raise ValueError(f"{suite} workload names or versions differ between runs")
        groups = [[r for r in sample if r["version"] == label] for label in ("before", "after")]
        rss_before, rss_after = [median(r["peak_rss_bytes"] for r in g) for g in groups]
        workloads = {}
        for name in names:
            old, new = [median(r["workloads"][name]["p50_ms"] for r in g) for g in groups]
            evidences = {digest(r["workloads"][name]["evidence"]) for r in sample}
            workloads[name] = {"before_p50_ms": old, "after_p50_ms": new,
                               "p50_change_percent": 100 * (new / old - 1),
                               "regression_investigation": new > old * 1.10,
                               "matching_work_and_quality": len(evidences) == 1}
        result[suite] = {"before_peak_rss_bytes": rss_before, "after_peak_rss_bytes": rss_after,
                         "rss_growth_investigation": rss_after > rss_before * 1.20, "workloads": workloads}
    return result


def compact_runs(records):
    """Store one copy of each work/quality snapshot across all timed repetitions."""
    catalog = {}
    compact = []
    for run in records:
        workloads = {}
        for name, sample in run["workloads"].items():
            key = digest(sample["evidence"])
            catalog[key] = sample["evidence"]
            workloads[name] = {k: v for k, v in sample.items() if k != "evidence"}
            workloads[name]["evidence_sha256"] = key
        compact.append({**run, "workloads": workloads})
    return compact, catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("--before", "--after", "--output"):
        parser.add_argument(flag, type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3, help="paired runs per wheel (default 3)")
    parser.add_argument("--compact", action="store_true", help="store repeated work/quality evidence once by digest")
    parser.add_argument("--work-dir", type=Path,
                        help="create a new directory for the two isolated environments and retain them for replay; "
                             "install offline through the invoking Python's pip")
    parser.add_argument("--suites", nargs="+", choices=["smoke", "combat", "progression", "lifecycle","encounter"],
                        default=["smoke", "combat"], help="baseline suites supported by both releases")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 50 or args.output.suffix.lower() != ".json":
        parser.error("choose 1..50 repetitions and a JSON output path")
    wheels = {k: getattr(args, k).resolve(strict=True) for k in ("before", "after")}
    if args.output.resolve() in wheels.values():
        parser.error("choose an output path separate from the wheels")
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env["PYTHONNOUSERSITE"] = "1"
    records = []
    with install_directory(args.work_dir) as cwd:
        pythons = {k: install(cwd / k, v, env, driver_pip=args.work_dir is not None) for k, v in wheels.items()}
        for n in range(args.repeats):
            for tag in (("after", "before") if n % 2 else ("before", "after")):
                for suite in dict.fromkeys(args.suites):
                    row, host = summarize(pythons[tag], suite, cwd, env)
                    records.append({"version": tag, **row})
    summaries = compare(records)
    data = {"schema_version": 1, "workers": 1, "host": host, "repetitions_per_wheel": args.repeats,
            "wheels": {k: {"filename": v.name, "sha256": hashlib.sha256(v.read_bytes()).hexdigest()}
                       for k, v in wheels.items()}, "runs": records, "summary": summaries}
    if args.compact:
        data["schema_version"] = 2
        data["runs"], data["evidence_by_sha256"] = compact_runs(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, allow_nan=False)+"\n", encoding="utf8")
    print(json.dumps(summaries, indent=2))
    if any(not w["matching_work_and_quality"] for s in summaries.values() for w in s["workloads"].values()):
        raise SystemExit("Workload inputs, observed output or deterministic work differ. See comparison JSON.")


if __name__ == "__main__":
    main()
