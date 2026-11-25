from dfo_optimizer.benchmark import run_benchmark


def test_smoke_checks_native_results_and_records_work():
    report = run_benchmark()
    assert report["engine"]["native"]
    assert report["workers"] == 1
    assert report["peak_rss_bytes"] > 0
    assert len(report["ruleset_hash"]) == 64
    batch = report["workloads"]["mechanics_batch"]
    assert batch["rows"] > 1000 and batch["evaluations_per_second"] > 0
    assert batch["verified"]
    assert batch["result_sha256"] == "cbea3ee92b3bfbd9c4010532ebf4a5af83109e74ea8c31baccfbc38de5270875"
    exact = report["workloads"]["class_exact"]
    # Portable work budgets from the serial baseline. Better pruning may reduce them.
    assert exact["verified"] and 0 < exact["nodes"] <= 78 and exact["leaves"] == 4
    assert exact["warm"]["p50_seconds"] <= exact["warm"]["p95_seconds"]
    assert exact["cold"]["wall_seconds"] > 0 and len(exact["result_sha256"]) == 64
    full = report["workloads"]["class_bounded"]
    assert 0 < full["nodes"] <= 252 and full["verified"] and full["returned"] == full["leaves"] == 20
