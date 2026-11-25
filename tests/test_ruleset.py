import copy
import json
import os
from pathlib import Path

import pytest

from dfo_optimizer.ruleset import DATA, SOURCE_SHA, build_ruleset, coverage, load_ruleset, validate_ruleset


def test_packaged_ruleset_matches_snapshot():
    bundle = load_ruleset()
    assert bundle["source_sha"] == SOURCE_SHA
    assert len(bundle["content_hash"]) == 64
    assert len(bundle["traits"]) == 90
    assert len(bundle["skills"]) == 35
    assert len(bundle["races"]) == 8
    assert [t["id"] for t in bundle["traits"]] == list(range(90))
    rows = {(t["primary"], t["secondary"]): t for t in bundle["traits"]}
    magery = rows["increasedMagery", "intInSpellPoints3"]
    assert magery["cost"] == 10
    assert rows["increasedMagery", "intInSpellPoints2"]["id"] in magery["conflicts"]
    fire = rows["immunity", "toFire"]
    assert rows["lowTolerance", "toFire"]["id"] in fire["conflicts"]
    assert rows["lowTolerance", "toFrost"]["id"] not in fire["conflicts"]
    assert all(t["id"] in t["conflicts"] for t in rows.values())
    assert coverage(bundle)["live_verified"] == []
    assert coverage(bundle)["unsupported"]


def test_combat_bundle_binds_spell_tables_and_equipment_catalog():
    import hashlib
    from dfo_optimizer.ruleset import validate_combat_ruleset

    bundle = validate_combat_ruleset(load_ruleset())
    assert bundle["spell_rules"] == json.loads((DATA / "spell-rules.json").read_text(encoding="utf8"))
    equipment = json.loads((DATA / "equipment.json").read_text(encoding="utf8"))
    content = json.dumps(equipment, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert bundle["equipment_hash"] == hashlib.sha256(content).hexdigest()
    ids = [entry["mechanic_id"] for entry in bundle["mechanics"]]
    assert len(set(ids)) == len(ids)


def test_offline_validate_and_load_reject_corruption(tmp_path):
    bundle = load_ruleset()
    path = tmp_path / "ruleset.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    assert load_ruleset(tmp_path) == bundle == load_ruleset(path)
    altered = copy.deepcopy(bundle)
    altered["traits"][0]["cost"] = 123456
    with pytest.raises(ValueError):
        validate_ruleset(altered)
    with pytest.raises(ValueError):
        validate_ruleset({"source_sha": SOURCE_SHA})


def test_reject_other_source_revision_before_execution(tmp_path):
    with pytest.raises(ValueError, match="commit|revision"):
        build_ruleset(tmp_path, "HEAD", tmp_path / "out")


def test_source_generated_cases_include_distinct_last_winners():
    path = Path(__file__).parent / "fixtures" / "oracle_classes.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["source_sha"] == SOURCE_SHA
    cases = {case["label"]: case for case in data["cases"]}
    assert cases["baseline"]["create_legal"]
    assert not cases["missing_skill"]["create_legal"]
    assert cases["order_light_dark"]["career"]["rapidHealing"] != cases["order_dark_light"]["career"]["rapidHealing"]
    assert cases["material_floor"]["difficulty"] == -12
    assert cases["material_floor"]["advancement"] == 0.3
    assert cases["material_floor"]["magicka_multiplier"] == 3
    assert cases["baseline"]["magicka_multiplier"] == 0.5
    assert cases["baseline"]["starting_spell_set_index"] == 1
    assert cases["no_magic_school"]["starting_spell_set_index"] is None


def test_rebuild_from_pinned_objects_is_byte_reproducible(tmp_path):
    source = os.getenv("DFO_SOURCE", str(Path(__file__).resolve().parents[1] / "vendor" / "dfo-source"))
    bundle = build_ruleset(source, SOURCE_SHA, tmp_path)
    assert bundle == load_ruleset()
    assert (tmp_path / "ruleset.json").read_bytes() == (DATA / "ruleset.json").read_bytes()


def test_reject_output_within_reference_checkout(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        build_ruleset(tmp_path, SOURCE_SHA, tmp_path / "unexpected")
    assert not (tmp_path / "unexpected").exists()
