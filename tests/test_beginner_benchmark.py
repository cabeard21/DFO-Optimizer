import pytest

from dfo_optimizer.beginner_benchmark import compare_admission, origin_profile


def ranked(family, clear=1.0, practice=50):
    return {
        "id": family,
        "metrics": {
            "worst_clear_rate": clear,
            "worst_survival_rate": 1.0,
            "mean_clear_rate": clear,
            "plate_weapon_materials": 3,
            "advancement_multiplier": 0.3,
            "mean_practice": practice,
            "mean_censored_clear_fraction": 0.25,
        },
    }


def test_exact_reduced_comparison_records_first_changed_priority_and_equal_ties():
    exact = [ranked("a"), ranked("b"), ranked("c", practice=55), ranked("d", clear=0.5)]
    tied = compare_admission(exact, [exact[1]], "b")
    assert tied["quality_recovered"] and not tied["tie_break_recovered"]
    assert tied["exact_winners"] == ["a", "b"]
    lower = compare_admission(exact, [exact[2], exact[3]], "c")
    assert lower["first_loss"] == {
        "axis": "mean_practice",
        "reference": 50,
        "retained": 55,
        "absolute_gap": 5,
        "relative_gap": 0.1,
    }
    assert lower["quality_recovered"] is False
    assert compare_admission(exact, [], None)["first_loss"] is None


def test_exact_comparison_refuses_changed_inputs_wrong_winner_or_ambiguous_metrics():
    a, b = ranked("a"), ranked("b", clear=0.5)
    with pytest.raises(ValueError, match="winner"):
        compare_admission([a, b], [a, b], "b")
    with pytest.raises(ValueError, match="metric"):
        compare_admission([a, b], [ranked("b")], "b")
    with pytest.raises(ValueError, match="finite"):
        compare_admission([ranked("a", practice=float("nan"))], [], None)
    with pytest.raises(ValueError, match="unique"):
        compare_admission([a, a], [], None)


def test_role_metric_recovery_excludes_undefined_efficiency_from_both_panels():
    from dfo_optimizer.beginner_benchmark import role_recovery

    a, b = ranked("a"), ranked("b")
    a["metrics"].update(cap_damage_per_second=20, min_hp_fraction=0.1, mean_damage_per_sp=None)
    b["metrics"].update(cap_damage_per_second=10, min_hp_fraction=0.3, mean_damage_per_sp=2)
    measured = role_recovery([a, b], [a])
    assert measured["cap_damage_per_second"]["recovered"]
    assert measured["min_hp_fraction"]["absolute_gap"] == pytest.approx(0.2)
    assert measured["mean_damage_per_sp"]["retained"] is None
    assert measured["mean_damage_per_sp"]["recovered"] is False
    assert role_recovery([a], [a])["mean_damage_per_sp"]["recovered"] is None


def test_origin_profiles_only_a_matching_request_and_groups_prebirth_rows():
    req = {"objective": "pareto", "roll_seeds": [1, 2]}
    frozen = {
        **req,
        "class_admission": {
            "families": [{"id": "c", "start": {"race_id": 1, "class": {"name": "Observed"}}}]
        },
    }
    result = {
        "kind": "lifecycle",
        "frozen_request": frozen,
        "input_hash": "input",
        "result_hash": "plan",
        "source_sha": "src",
        "ruleset_hash": "rules",
        "counters": {"nodes": 9},
        "timings": {"elapsed_seconds": 0.1},
        "class_admission": {"evaluated": 1},
        "gaps": [],
        "status": "best_found_bounded",
        "termination": "class_limit",
        "paired_rolls": [1, 2],
        "validation": {"routes_checked": 2},
        "comparison_witnesses": [],
        "candidates": [{}, {}],
        "paired_family_frontier": {
            "points": [
                {
                    "family": "c",
                    "means": {"final_dps": 4.5},
                    "selectors": ["final_dps"],
                    "rolls": [{"seed": 1, "witness_index": 0}, {"seed": 2, "witness_index": 1}],
                }
            ],
            "axes": ["final_dps"],
            "policy_enumeration_complete": False,
        },
    }
    summary = origin_profile(req, result)
    assert summary["paired_builds"][0]["class"] == {"name": "Observed"}
    assert summary["paired_builds"][0]["policies"][0]["means"] == {"final_dps": 4.5}
    assert summary["validation"] == {"routes_checked": 2}
    with pytest.raises(ValueError, match="frozen request"):
        origin_profile({**req, "roll_seeds": [9]}, result)


def test_case_matrix_rejects_partial_or_duplicate_paired_combat_tapes():
    from dfo_optimizer.beginner_benchmark import check_case_matrix

    panel = {"roll_seeds": [7, 8], "combat_seeds": [3], "cases": ["ordinary"], "variants": ["baseline"]}
    outcomes = [
        {
            "scenario": "ordinary",
            "stage": stage,
            "variant": "baseline",
            "roll_seed": birth,
            "seed": 3,
            "status": "replayed",
        }
        for stage in ("early", "mid", "cap")
        for birth in (7, 8)
    ]
    row = {**ranked("c"), "outcomes": outcomes}
    assert check_case_matrix([row], panel, ("early", "mid", "cap")) == 6
    for bad in ([*outcomes, outcomes[0]], outcomes[1:], [{**outcomes[0], "status": "gap"}, *outcomes[1:]]):
        with pytest.raises(ValueError, match="paired"):
            check_case_matrix([{**row, "outcomes": bad}], panel, ("early", "mid", "cap"))


def test_qualification_panel_uses_unseen_tapes_and_independent_enumeration():
    from dfo_optimizer.beginner_benchmark import qualification_panel, class_product

    frozen = qualification_panel()
    for heldout in ("held_out_pressure", "held_out_dungeon"):
        for kind in ("roll_seeds", "combat_seeds"):
            assert set(frozen["panels"][heldout][kind]).isdisjoint(frozen["panels"]["development"][kind])
    assert len(class_product(frozen["domain"])) == frozen["expected_finite_classes"] == 8
    material = frozen["material_domain"]
    assert len(class_product(material)) == 8
    assert {len(row[3]) for row in class_product(material)} == {6, 7, 8}


def test_benchmark_cli_and_summary_keep_gaps_separate_by_units():
    from dfo_optimizer.beginner_benchmark import quality_summary
    from dfo_optimizer.cli import _parser

    assert _parser().parse_args(["benchmark", "--suite", "beginner"]).suite == "beginner"
    exact = [ranked("a"), ranked("b", clear=0.75), ranked("c", practice=55)]
    checks = [compare_admission(exact, [row], row["id"]) for row in exact]
    checks += [compare_admission(exact, [], None)]
    summary = quality_summary(checks)
    assert summary["winning_metric_recovery_rate"] == 0.25
    assert summary["missing_recommendations"] == 1
    assert summary["worst_first_loss_by_axis"] == {"worst_clear_rate": 0.25, "mean_practice": 5}


def test_benchmark_cross_checks_every_admitted_identity_and_uses_separate_heldout_rows(monkeypatch):
    from itertools import product

    from dfo_optimizer import beginner, beginner_benchmark, beginner_classes
    from dfo_optimizer.beginner_benchmark import class_product, run_beginner_benchmark
    from dfo_optimizer.class_document import ATTRIBUTES
    from dfo_optimizer.ruleset import load_ruleset

    rules = load_ruleset()
    skills = {r["id"]: r["name"] for r in rules["skills"]}
    traits = {r["id"]: r for r in rules["traits"]}

    def roster(mode, *, domain, exhaustive, **settings):
        families = []
        for i, (race, attrs, selected, picks) in enumerate(sorted(class_product(domain))):
            names = [skills[s] for s in selected]
            doc = {
                "attributes": dict(zip(ATTRIBUTES, attrs, strict=True)),
                "skills": {"primary": names[:3], "major": names[3:6], "minor": names[6:]},
            }
            for group, side in (("advantages", "advantage"), ("disadvantages", "disadvantage")):
                doc[group] = [
                    {key: traits[t][key] for key in ("primary", "secondary")}
                    for t in picks
                    if traits[t]["side"] == side
                ]
            families.append({"id": str(i), "start": {"race_id": race, "class": doc}, "origin": "discovered"})
        return {
            "families": families[: domain["top_k"]],
            "counts": {"nodes": 12},
            "proof_scope": {"admission_complete": exhaustive},
        }

    def evaluate(families, *, cases, variants, roll_seeds, combat_seeds, search):
        outcomes = [
            {"scenario": c, "stage": s, "variant": v, "roll_seed": r, "seed": e, "status": "replayed"}
            for c, s, v, r, e in product(
                cases, ("birth", "midgame", "cap"), variants, roll_seeds, combat_seeds
            )
        ]
        rows = [{**ranked(f["id"], practice=10 - int(f["id"])), "outcomes": outcomes} for f in families]
        return {"recommendation": rows[-1], "comparisons": rows, "diagnostics": {}, "result_hash": "test"}

    monkeypatch.setattr(beginner_classes, "beginner_roster", roster)
    monkeypatch.setattr(beginner, "evaluate_roster", evaluate)
    monkeypatch.setattr(beginner_benchmark, "engine", lambda native: native.build_info())
    report = run_beginner_benchmark()
    assert report["workloads"]["held_out_pressure"]["exhaustive"]["cells_per_family"] == 36
    assert report["held_out"]["2"]["comparisons"] == 3
    assert report["held_out"]["2"]["worst_first_loss_by_axis"] == {"mean_practice": 6}
    assert report["determinism"]["same_ranked_result"] and report["determinism"]["same_screening"]
