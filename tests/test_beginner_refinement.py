import gzip
import hashlib
import json
from pathlib import Path

import pytest

from dfo_optimizer.beginner import parse_request, recommend_build, replay_recommendation


def test_refined_profile_is_strict_and_legacy_request_keeps_its_meaning():
    assert "require_fast_advancement" not in parse_request({})
    request = parse_request({"schema_version": 2})
    assert request["schema_version"] == 2
    assert request["require_fast_advancement"] is True
    with pytest.raises(ValueError, match="0.30"):
        parse_request({"schema_version": 2, "require_fast_advancement": False})


def test_refined_work_limit_is_shared_and_replayable():
    result = recommend_build({"schema_version": 2, "search": {"max_nodes": 1}})
    assert result["profile"] == "first_spellcaster_v2"
    assert result["recommendation"] is None
    assert result["diagnostics"]["nodes"] <= 1
    assert replay_recommendation(result)["verified"]


def test_submitted_archive_fixture_keeps_its_envelope_and_strict_request():
    from dfo_optimizer.workbench_files import imported

    raw = gzip.decompress(Path(__file__).with_name("fixtures").joinpath("beginner-submitted-archive.json.gz").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == "d862c387053f5fa4df6a9fcc39d0bfd6c7cbd0e6b1aa2d1312d90d0ed26aa0d8"
    archive = json.loads(raw)
    result = imported("archive", archive, archive["ruleset_hash"])["value"]["result"]
    assert result["recommendation"]["race"] == "Wood Elf"
    assert result["recommendation"]["metrics"]["cap_damage_per_second"] == pytest.approx(49.849041743)
    assert result["frozen_request"]["require_fast_advancement"]


def test_submitted_class_runs_optimized_native_panel_and_replays():
    from dfo_optimizer.beginner import CancelToken
    from dfo_optimizer.beginner_refinement import _fixtures, run
    from dfo_optimizer.ruleset import _progression_service_rules

    rules = _progression_service_rules(None)
    archived = next(row for row in _fixtures(rules, None) if row["origin"] == "submitted_archive")
    query = parse_request({"schema_version": 2, "search": {"wall_seconds": 0}})
    result = run(query, rules, CancelToken(), fixed=[archived])
    winner = result["recommendation"]
    assert winner["metrics"]["advancement_multiplier"] == .30
    assert result["diagnostics"]["spell_nodes"] > 0
    assert winner["refinement"]["gear"]["theoretical"]["status"] == "replayed"
    assert winner["refinement"]["arcane"]["paths"]["soulbinder"]["sp_restored"] > 0
    assert replay_recommendation(result)["families_checked"] == 1
