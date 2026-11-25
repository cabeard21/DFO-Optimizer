import importlib.util
from pathlib import Path

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


def test_inconsistent_metrics_and_missing_workloads_are_detected():
    tool = load()
    runs = [sample("before", 11, 100), sample("after", 10, 99, points=[1])]
    assert not tool.compare(runs)["combat"]["workloads"]["joint"]["matching_work_and_quality"]
    runs[1]["workloads"] = {}
    with pytest.raises(ValueError, match="workload"):
        tool.compare(runs)
