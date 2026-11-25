from copy import deepcopy
import json
from pathlib import Path

from dfo_optimizer.lifecycle import optimize_build, replay_build


def test_bounded_refinement_reserves_work_for_each_family_and_roll():
    path = Path(__file__).resolve().parents[1] / "examples" / "build-lifecycle.json"
    request = json.loads(path.read_bytes())
    request["search"] = {"max_nodes": 1000, "wall_seconds": 0}
    frozen = deepcopy(request)
    result = optimize_build(request)
    assert request == frozen
    trials = result["refinement"]["trials"]
    expected = {(f["id"], seed) for f in request["families"] for seed in request["roll_seeds"]}
    assert {(t["family"], t["roll_seed"]) for t in trials if t["phase"] == "probe"} == expected
    assert any(t["phase"] == "refine" for t in trials)
    assert sum(t["nodes"] for t in trials) == result["counters"]["nodes"] <= 1000
    assert result["result_hash"] == optimize_build(request)["result_hash"]
    assert replay_build(result)["validated"]


def test_tiny_or_precancelled_panel_reports_incomplete_roll_coverage():
    from dfo_optimizer import _lifecycle
    path = Path(__file__).resolve().parents[1] / "examples" / "build-lifecycle.json"
    request = {**json.loads(path.read_bytes()), "search": {"max_nodes": 1, "wall_seconds": 0}}
    limited = optimize_build(request)
    assert limited["status"] == "no_feasible_found"
    assert limited["counters"]["nodes"] == 1
    assert len(limited["refinement"]["trials"]) == 1
    token = _lifecycle.CancelToken()
    token.cancel()
    cancelled = optimize_build(request, cancel=token)
    assert cancelled["status"] == "cancelled" and cancelled["counters"]["nodes"] == 0
    assert cancelled["refinement"]["trials"] == []
