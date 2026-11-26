import importlib.util
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

import pytest


tool = Path(__file__).resolve().parents[1] / "tools/compare_release_benchmarks.py"


def load():
    spec = importlib.util.spec_from_file_location("release_comparison", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample(label, ms, rss, *, nodes=122, points=None):
    return {"version": label, "suite": "combat", "workload_version": 1, "peak_rss_bytes": rss,
            "workloads": {"joint": {"p50_ms": ms, "evidence": {"nodes": nodes, "frontier": points or [1, 2]},
                                    "result_sha256": "new-hash" if label == "after" else "old-hash"}}}


def test_report_uses_median_and_keeps_telemetry_out_of_domain_comparisons():
    runs = [sample("before", 12, 140), sample("after", 14, 150), sample("before", 10, 100),
            sample("after", 15, 155), sample("before", 11, 120), sample("after", 16, 160)]
    result = load().compare(runs)["combat"]
    assert result["workloads"]["joint"]["before_p50_ms"] == 11
    assert result["workloads"]["joint"]["after_p50_ms"] == 15
    assert result["workloads"]["joint"]["regression_investigation"]
    assert result["workloads"]["joint"]["matching_work_and_quality"]
    assert result["rss_growth_investigation"]


def test_compact_evidence_retains_every_distinct_snapshot_and_sample():
    module = load()
    runs = [sample("before",12,140), sample("after",14,150), sample("after",13,151,nodes=123)]
    compact, catalog = module.compact_runs(runs)
    assert len(catalog)==2
    for original, recorded in zip(runs, compact, strict=True):
        before = original["workloads"]["joint"]
        after = recorded["workloads"]["joint"]
        assert catalog[after["evidence_sha256"]] == before["evidence"]
        assert (after["p50_ms"],after["result_sha256"]) == (before["p50_ms"],before["result_sha256"])


def test_inconsistent_metrics_and_missing_workloads_are_detected():
    tool = load()
    runs = [sample("before", 11, 100), sample("after", 10, 99, points=[1])]
    assert not tool.compare(runs)["combat"]["workloads"]["joint"]["matching_work_and_quality"]
    runs[1]["workloads"] = {}
    with pytest.raises(ValueError, match="workload"):
        tool.compare(runs)


def test_encounter_comparison_keeps_frozen_request_replayed_policies_and_result_identity(monkeypatch):
    module = load()
    workload = {"input_hash":"request","result_hash":"result","ruleset_hash":"rules","source_sha":"source",
                "policies_checked":2,"seeds":[42,97],"warm":{"p50_seconds":0.001},
                "counters":{"policies":2,"events":13},"frontier":[[1,0,5.0]]}
    report = {"suite":"encounter","workload_version":1,"peak_rss_bytes":100,"host":{},
              "workloads":{"pack":workload}}
    monkeypatch.setattr(module, "command", lambda *_, **kwargs: report)
    summary, _ = module.summarize("python","encounter",Path("."),{})
    row = summary["workloads"]["pack"]
    assert row["result_sha256"] == "result"
    assert row["evidence"]["seeds"] == [42,97]
    assert row["evidence"]["policies_checked"] == 2
    assert row["evidence"]["input_sha256"] == "request"
    assert (summary["ruleset_hash"],summary["source_sha"]) == ("rules","source")


def test_explicit_install_directory_is_new_and_survives_for_replay():
    module = load()
    target = Path(gettempdir()) / f"dfo-paired-unit-{uuid4().hex}"
    with module.install_directory(target) as directory:
        assert directory == target.resolve()
        (directory / "snapshot").write_text("kept")
    try:
        assert (target / "snapshot").read_text() == "kept"
        with pytest.raises(FileExistsError):
            with module.install_directory(target):
                pytest.fail("existing install directory was reused")
    finally:
        (target / "snapshot").unlink()
        target.rmdir()


def test_explicit_offline_wheel_install_bootstraps_from_the_driver(monkeypatch):
    module = load()
    invoked = []
    tmp_path = Path("hypothetical-env")
    class Builder:
        def __init__(self, *, with_pip):
            assert not with_pip
        def create(self, directory):
            assert directory == tmp_path
    monkeypatch.setattr(module.venv, "EnvBuilder", Builder)
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kwargs: invoked.append(argv))
    wheel = tmp_path / "local.whl"
    python = module.install(tmp_path, wheel, {}, driver_pip=True)
    assert invoked == [[module.sys.executable, "-I", "-m", "pip", "--python", python, "install",
                        "--no-index", "--no-deps", "--no-cache-dir", "--no-compile", wheel]]
