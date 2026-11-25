from dfo_optimizer.encounter_benchmark import run_encounter_benchmark


def test_installed_encounter_suite_times_validated_native_work():
    report = run_encounter_benchmark(samples=1)
    reduced = report["workloads"]["pack"]
    assert reduced["events_per_second"] > 0
    assert reduced["policies_checked"] == len(reduced["frontier"])
    assert reduced["first_replayed_seconds"] >= 0
    assert report["workloads"]["pack_bounded"]["quality"]["exact_points"] > 0
    assert report["workloads"]["dungeon"]["result_hash"]
    assert report["extension_sha256"] and report["peak_rss_bytes"] > 0
