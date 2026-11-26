import pytest

from dfo_optimizer import beginner
from dfo_optimizer.cli import _parser
from dfo_optimizer.workbench_services import ACTIONS, is_discovery, search_token


def test_one_click_entry_and_fixed_work_reproduction():
    assert _parser().parse_args(["build", "recommend"]).request is None
    assert "build recommend" in ACTIONS and is_discovery("build recommend", {})
    defaults = beginner.parse_request({})
    assert defaults["thoroughness"] == "standard" and defaults["search"]["wall_seconds"] == 120
    assert beginner.parse_request({"search": {"wall_seconds": 0, "max_nodes": 5000}})["search"]["wall_seconds"] == 0


@pytest.mark.parametrize("raw", [
    [], {"thoroughness": "unlimited"}, {"force_plate": False}, {"search": {"max_nodes": False}},
    {"search": {"wall_seconds": float("nan")}}, {"search": {"max_nodes": 0, "wall_seconds": 0}},
    {"search": {"memory_bytes": -1}}, {"search": {"budget_gold": 100}},
])
def test_invalid_inputs_fail_before_any_search(raw):
    with pytest.raises(ValueError):
        beginner.parse_request(raw)


def test_pre_cancelled_job_has_no_winner_and_charges_no_work():
    token = search_token("build recommend", {})
    token.cancel()
    out = beginner.recommend_build({}, cancel=token)
    assert out["termination"] == "cancelled"
    assert not out["exact"] and out["recommendation"] is None
    assert out["diagnostics"]["nodes"] == 0
    assert out["frozen_request"]["thoroughness"] == "standard"


def test_stale_or_modified_archive_fails_before_replay():
    token = beginner.CancelToken()
    token.cancel()
    result = beginner.recommend_build({}, cancel=token)
    with pytest.raises(ValueError, match="identity"):
        beginner.replay_recommendation({**result, "recommendation": {"id": "spoof"}})
    from dfo_optimizer.beginner_report import result_identity
    from dfo_optimizer.character import _hash

    stale = {**result["evaluation"], "physical_law_hash": "other game settings", "scenarios": []}
    altered = {**result, "evaluation": stale, "comparison_hash": _hash(stale)}
    with pytest.raises(ValueError, match="panel"):
        beginner.replay_recommendation({**altered, "result_hash": result_identity(altered)})


def test_recommendation_can_be_replayed_from_archive_on_a_small_real_panel():
    from dfo_optimizer.beginner_classes import manual_classes
    from dfo_optimizer.lifecycle import compare_builds, replay_build

    families = manual_classes(roll_seeds=[42])
    panel = beginner.evaluate_roster(families, roll_seeds=[42], combat_seeds=[101],
                                     cases=["enemy_caster"], variants=["baseline"])
    assert len(panel["comparisons"]) == 2
    assert panel["diagnostics"]["fully_evaluated"] == 2
    assert panel["recommendation"]["guide"]["text"]
    assert replay_build(panel)["outcomes_checked"] == 6
    assert len(compare_builds([panel, panel])["recommendations"]) == 2


def test_installed_cli_exports_the_recommended_class_with_race_checked(tmp_path):
    import json

    from dfo_optimizer.beginner_classes import manual_classes
    from dfo_optimizer.cli import _export_source
    from dfo_optimizer.ruleset import load_ruleset
    rules = load_ruleset()
    family = manual_classes()[0]
    row = {"id":family["id"], "class":family["start"]["class"], "race_id":family["start"]["race_id"]}
    result = {"kind":"beginner_recommendation", "recommendation":row, "alternatives":[],
              "ruleset_hash":rules["content_hash"]}
    path = tmp_path / "first-build.json"
    path.write_text(json.dumps(result))
    args = _parser().parse_args(["class","export","--result",str(path)])
    assert _export_source(args,rules) == row["class"]
    result["recommendation"]["race_id"] = 99
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="identity"):
        _export_source(args,rules)


def test_binding_outer_budget_report_and_unchecked_class_do_not_masquerade_as_infeasible():
    from dfo_optimizer.beginner_classes import manual_classes

    result = beginner.evaluate_roster(manual_classes(), search={"max_nodes": 1, "wall_seconds": 0})
    assert result["diagnostics"]["nodes"] <= 1
    assert result["termination"] == "node_limit"
    assert result["recommendation"] is None and result["status"] == "incomplete"


def test_explicit_class_roster_reauthenticates_permanent_properties_and_identity():
    from dfo_optimizer.beginner_classes import manual_classes
    families = manual_classes()
    corrupt = {**families[0], "compliance": {**families[0]["compliance"], "plate_weapon_materials": 999}}
    with pytest.raises(ValueError, match="permanent"):
        beginner.evaluate_roster([corrupt], search={"max_nodes": 1})
    with pytest.raises(ValueError, match="identity"):
        beginner.evaluate_roster([families[0], {**families[1], "id":families[0]["id"]}], search={"max_nodes": 1})


def test_replay_honors_the_workbench_cancellation_token():
    from dfo_optimizer.workbench_services import execute
    token = beginner.CancelToken()
    token.cancel()
    result = beginner.recommend_build({}, cancel=token)
    replay = search_token("build replay", result)
    assert replay is not None
    replay.cancel()
    assert execute("build replay", result, replay)["termination"] == "cancelled"
