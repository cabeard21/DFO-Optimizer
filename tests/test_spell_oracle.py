"""Black-box spell parity against observations from the pinned JavaScript runtime."""
import json
from pathlib import Path

import pytest

from dfo_optimizer.ruleset import DATA, SOURCE_SHA

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "spell-oracle.json"


def vectors():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_spell_oracle_covers_maker_host_and_all_targets():
    fixture = vectors()
    assert fixture["source_sha"] == SOURCE_SHA
    facts = json.loads((DATA / "spell-rules.json").read_text(encoding="utf-8"))
    assert facts["effect"]["key"] == "4,0"
    assert facts["effect"]["target_mask"] == 30
    assert facts["effect"]["element_mask"] == 31
    host = {row["id"]: row for row in fixture["host"]}
    assert host["normal"]["ready"] and host["normal"]["charged"] > 0
    assert host["free"]["cast"] and host["free"]["charged"] == 0
    assert host["insufficient"]["ready"] is False
    assert host["touch_miss"]["ready"] and not host["touch_miss"]["cast"]
    assert host["changed_skill"]["charged"] == host["changed_skill"]["ready_cost"]
    assert host["drained_after_ready"]["charged"] == 2 < host["drained_after_ready"]["ready_cost"]
    impact = fixture["host_impact"]
    assert impact["hurt"] == impact["landed_damage"] > impact["taken"] == impact["initial_hp"]
    assert {row["request"]["spell"]["range_type"] for row in fixture["casts"]} == {1, 2, 3, 4}


def test_all_direct_casts_match_independent_runtime():
    from dfo_optimizer.spells import evaluate_spell

    for vector in vectors()["casts"]:
        result = evaluate_spell(vector["request"])
        assert result["candidates"], vector["id"]
        actual = result["candidates"][0]["metrics"]
        assert actual["effect_sp"] == vector["editor_cost"]["sp"], vector["id"]
        for field, expected in vector["expected"].items():
            if expected is None:
                assert actual[field] is None, (vector["id"], field)
            elif field in ("expected_damage", "expected_health_loss", "dps", "damage_per_sp", "damage_per_sp_if_cast",
                         "kill_probability", "potency", "release_seconds", "recovery_seconds", "cast_rate"):
                assert actual[field] == pytest.approx(expected, rel=1e-12, abs=1e-12), (vector["id"], field)
            else:
                assert actual[field] == expected, (vector["id"], field)
