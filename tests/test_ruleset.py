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


def test_progression_bundle_binds_extracted_mechanics():
    from dfo_optimizer.ruleset import validate_progression_ruleset
    bundle = validate_progression_ruleset(load_ruleset())
    assert bundle["progression_rules"] == json.loads((DATA / "progression-rules.json").read_text(encoding="utf8"))
    assert bundle["extraction_version"] >= 3
    assert any(row["mechanic_id"] == "spell.stock_records" for row in bundle["mechanics"])


def test_encounter_bundle_binds_the_permanent_catalog_and_mechanic_audit():
    from dfo_optimizer.ruleset import validate_encounter_ruleset
    bundle = validate_encounter_ruleset(load_ruleset())
    assert bundle["permanent_rules"] == json.loads((DATA / "permanent-rules.json").read_text(encoding="utf8"))
    rows = json.loads((DATA / "encounter-mechanics.json").read_text(encoding="utf8"))
    assert rows and all(row in bundle["mechanics"] for row in rows)
    assert {"progression.oghma", "progression.firmament", "encounter.firmament"} <= {
        row["mechanic_id"] for row in rows
    }
    assert bundle["content_hash"] == (DATA / "encounter-release.sha256").read_text(encoding="ascii").strip()
    assert bundle["encounter_paths"] == json.loads((DATA / "encounter-paths.json").read_text(encoding="utf8"))
    altered = copy.deepcopy(bundle)
    altered["permanent_rules"]["oghma"]["pool"] += 1
    with pytest.raises(ValueError, match="hash"):
        validate_encounter_ruleset(altered)


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


def test_admission_authenticates_the_exact_detached_snapshot():
    from dfo_optimizer.ruleset import freeze_ruleset
    supplied = load_ruleset()
    frozen = freeze_ruleset(supplied)
    assert frozen == supplied
    supplied["traits"][0]["cost"] += 1
    assert supplied != frozen
    with pytest.raises(ValueError, match="hash"):
        freeze_ruleset(supplied)


def test_service_admission_checks_every_json_type_and_does_not_retain_the_callers_object():
    from dfo_optimizer.ruleset import _service_rules
    supplied = load_ruleset()
    rules = _service_rules(supplied)
    assert rules == supplied and rules is not supplied
    supplied["permanent_rules"]["oghma"]["pool"] = 30.0
    assert type(rules["permanent_rules"]["oghma"]["pool"]) is int
    with pytest.raises(ValueError, match="hash"):
        _service_rules(supplied)
    supplied = load_ruleset()
    supplied["mechanics"][0]["live_verified"] = 0  # Equal to False in Python.
    with pytest.raises(ValueError, match="hash"):
        _service_rules(supplied)


def test_native_rules_equality_is_order_independent_and_preserves_json_number_forms():
    from dfo_optimizer import _native
    base = {"n":[1, 0.0, False], "v":None}
    assert _native.same_json_tree({"v":None, "n":[1, 0.0, False]}, base)
    for different in [[1, -0.0, False], [True, 0.0, False], [1., 0.0, False], [1, 0.0, 0]]:
        assert not _native.same_json_tree({"n":different, "v":None}, base)
    assert not _native.same_json_tree({"n":base["n"], "another":None}, base)


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


def test_explicit_oracle_scratch_is_isolated_and_cleaned(tmp_path, monkeypatch):
    from dfo_optimizer.ruleset import adapter_directory
    monkeypatch.setenv("DFO_ORACLE_SCRATCH", str(tmp_path))
    with adapter_directory() as first, adapter_directory() as second:
        assert first.parent == second.parent == tmp_path
        assert first != second
        (first / "probe.json").write_bytes(b"{}")
    assert not first.exists() and not second.exists()
