import json
import zipfile
from pathlib import Path

import pytest

from dfo_optimizer.character import import_character, list_character_slots, normalize_character


FIXTURE = Path(__file__).parent / "fixtures" / "character" / "export.zip"


def snapshot(**overrides):
    return {
        "v": 1, "characterId": "fixture", "name": "Arden", "level": 5, "raceId": 1,
        "stats": {"speed": 60}, "skills": [40] * 35, "masteredSkills": [],
        "health": 14, "maxHealth": 22, "magicka": 14, "maxMagicka": 30, "career": {},
        "items": [{"templateIndex": 132, "group": "MiscItems"},
                  {"templateIndex": 275, "value": 120}],
        "goldPieces": 8, "spells": [18], **overrides,
    }


def test_resources_ownership_and_unknown_online_values():
    doc = normalize_character(snapshot())
    assert doc["caster"]["gold"] == 128
    assert doc["caster"]["has_spellbook"] is True
    assert doc["caster"]["current_sp"] is None
    assert doc["observations"]["resources"]["magicka"] == 14
    assert doc["observations"]["spells"]["unresolved_indices"] == [18]
    assert doc["caster"]["destruction_live"] == 40
    assert normalize_character(doc) == doc


def test_mastery_and_actual_item_copies():
    skills = [45] * 35
    skills[22] = 175
    item = {"group": "Jewellery", "templateIndex": 135, "uid": "acquired", "equipSlot": 4,
            "rarity": "magic",
            "affixes": [{"id": "skill", "param": 34, "value": 8}, {"id": "castSpeed", "value": 6}]}
    doc = normalize_character(snapshot(skills=skills, masteredSkills=[22], items=[item],
                                       otherItems=[{"templateIndex": 5}]))
    assert doc["gear"]["base_caster"]["destruction_live"] == 127
    assert doc["caster"]["cast_speed_pct"] == 6
    assert doc["gear"]["base_caster"]["cast_speed_pct"] == 0
    assert doc["gear"]["items"][0]["item"] == item
    assert [i["container"] for i in doc["gear"]["items"]] == ["pack", "repair"]
    assert doc["gear"]["items"][0]["instance_id"] != doc["gear"]["items"][1]["instance_id"]
    assert normalize_character(snapshot(skills=skills))["caster"]["destruction_live"] == 100


def test_observations_require_attribution_and_do_not_change_saved_vitals():
    doc = normalize_character(snapshot())
    doc.pop("snapshot_hash")
    doc["live_observations"] = {"current_sp": {"value": 30, "source": "Character sheet", "observed_at_ms": 123}}
    out = normalize_character(doc)
    assert out["caster"]["current_sp"] == 30
    assert out["observations"]["resources"]["magicka"] == 14
    assert out["gear"]["base_caster"]["current_sp"] == 30
    assert normalize_character(out) == out
    doc["live_observations"]["current_sp"].pop("source")
    with pytest.raises(ValueError, match="source"):
        normalize_character(doc)


def test_upstream_export_and_raw_slot_match(tmp_path):
    slots = list_character_slots(FIXTURE)
    assert [s["slot"] for s in slots] == [0, 1]
    assert slots[0]["observed_at_ms"] == 1780000000000
    with pytest.raises(ValueError, match="--slot"):
        import_character(FIXTURE)
    with pytest.raises(ValueError, match="slot"):
        import_character(FIXTURE, slot=44)
    selected = import_character(FIXTURE, slot=0)
    assert selected["observations"]["spells"]["unresolved_indices"] == [18]
    assert len(selected["observations"]["spells"]["records"]) == 1
    assert selected["gear"]["items"][0]["item"]["equipSlot"] == 4
    with zipfile.ZipFile(FIXTURE) as archive:
        for filename in ("SaveData.txt", "SaveInfo.txt"):
            (tmp_path / filename).write_bytes(archive.read(f"Saves/SAVE0/{filename}"))
    bare = import_character(tmp_path / "SaveData.txt")
    folder = import_character(tmp_path)
    assert bare["observations"] == folder["observations"] == selected["observations"]
    assert folder["gear"] == selected["gear"]
    portable = tmp_path / "portable.json"
    portable.write_text(json.dumps(selected), encoding="utf-8")
    assert import_character(portable) == selected


@pytest.mark.parametrize("bad", [
    {"v": 2}, {"v": True}, {"kind":"character","schema_version":True,"caster":{}},
    snapshot(items="invalid"), snapshot(items=[{"uid":"000000000000000a"},{"uid":"000000000000000a"}]),
    snapshot(skills=[True] * 35), snapshot(masteredSkills=[99]), snapshot(spells=[False]),
    snapshot(magicka=-1), snapshot(stats={"speed": True}),
])
def test_invalid_inputs(bad):
    with pytest.raises(ValueError):
        normalize_character(bad)


def test_tamper_and_bad_archive(tmp_path):
    doc = normalize_character(snapshot())
    doc["caster"]["level"] += 1
    with pytest.raises(ValueError, match="hash"):
        normalize_character(doc)
    archive = tmp_path / "bad.zip"
    archive.write_bytes(b"broken zip")
    with pytest.raises(ValueError, match="ZIP"):
        import_character(archive)
    with zipfile.ZipFile(archive, "w") as f:
        f.writestr("../Saves/SAVE2/SaveData.txt", json.dumps(snapshot()))
    with pytest.raises(ValueError, match="slot"):
        import_character(archive)


def test_material_unsupported_effects_and_class_restrictions_follow_import():
    active = [{"kind":"fortifyAttribute","stat":"speed"}, {"kind":"conceal","ended":True}]
    save = snapshot(career={"abilityFlagsAndSpellPointsBitfield": 1 << 6}, activeEffects=active)
    assert normalize_character(save)["unknown_mechanics"] == ["active_effect:fortifyAttribute", "environmental_magery"]


def test_equipment_does_not_reenter_as_live_numeric_stats():
    saved = snapshot(items=[{"group":"Jewellery", "templateIndex":135,"equipSlot":4,
                             "rarity": "magic", "affixes":[{"id":"skill","param":34,"value":8},
                                                          {"id":"castSpeed","value":6}]}])
    imported = normalize_character(saved)
    assert imported["caster"]["speed"] == 60
    assert imported["caster"]["cast_speed_pct"] == 6
    assert imported["gear"]["base_caster"]["speed"] == 60
    assert imported["gear"]["base_caster"]["focus_pct"] == 0


def test_unreviewed_worn_power_keeps_material_cast_fields_unknown():
    imported = normalize_character(snapshot(items=[{"group":"Jewellery", "templateIndex":135,
                                                   "equipSlot":4,"sigil":{"rank":1}}]))
    assert imported["caster"]["cast_speed_pct"] is None
    assert imported["gear"]["base_caster"]["speed"] == 60


def test_checked_neutral_worn_item_has_no_effect_on_direct_spell():
    character = import_character(FIXTURE, slot=0)
    assert character["caster"]["speed"] == 65
    assert character["caster"]["destruction_live"] == 52
    assert character["caster"]["focus_pct"] == 0


def test_portable_field_observation_validation_and_isolation():
    original = {"kind":"character","schema_version":1,
                "caster":{"level":3,"current_sp":5,"max_sp":44},
                "live_observations":{"current_sp":{"value":20,"source":"character sheet","observed_at_ms":100}}}
    doc = normalize_character(original)
    assert doc["caster"]["current_sp"] == 20
    assert original["caster"]["current_sp"] == 5
    assert normalize_character(doc) == doc
    with pytest.raises(ValueError, match="maximum"):
        normalize_character({**original,"live_observations":{},"caster":{"max_sp":1,"current_sp":2}})


def test_cards_and_json_are_checked(tmp_path):
    (tmp_path / "SaveData.txt").write_text(json.dumps(snapshot()), encoding="utf-8")
    card = tmp_path / "SaveInfo.txt"
    card.write_text('{"characterId":"wrong"}', encoding="utf-8")
    with pytest.raises(ValueError, match="disagree"):
        import_character(tmp_path)
    card.write_text('{"dateAndTime":{"realTime":"bad"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="time"):
        list_character_slots(tmp_path)
    card.write_text('{"realTime":0,"realTime":1}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        list_character_slots(tmp_path)


def test_oversized_raw_and_archive_rejected_before_loading(tmp_path, monkeypatch):
    from dfo_optimizer import character_files
    small = tmp_path / "sample.json"
    small.write_text(json.dumps(snapshot()), encoding="utf-8")
    monkeypatch.setattr(character_files, "MAX_SAVE_BYTES", 20)
    with pytest.raises(ValueError, match="limit"):
        import_character(small)
    with pytest.raises(ValueError, match="limit"):
        import_character(FIXTURE, slot=0)


@pytest.mark.parametrize("uid", [3, "legacy", "ABCDEF0123456789"])
def test_nonledger_uid_is_scoped_to_its_copy(uid):
    imported = normalize_character(snapshot(items=[{"uid":uid},{"uid":uid}]))
    rows = imported["gear"]["items"]
    assert [row["instance_id"] for row in rows] == ["save:pack:0", "save:pack:1"]
    assert rows[0]["item"]["uid"] == uid


def test_single_observation_freezes_new_snapshot_and_preserves_input():
    from dfo_optimizer.character import apply_request_observations
    character = normalize_character(snapshot())
    obs = {"current_sp":{"value":33, "source":"sheet", "observed_at_ms":1234}}
    result = apply_request_observations({"character":character, "live_observations": obs})
    assert result["character"]["caster"]["current_sp"] == 33
    assert result["character"]["gear"]["base_caster"]["current_sp"] == 33
    assert result["character"]["snapshot_hash"] != character["snapshot_hash"]
    assert character["live_observations"] == {}
    assert character["caster"]["current_sp"] is None
    assert "live_observations" not in result
    assert normalize_character(result["character"]) == result["character"]
    with pytest.raises(ValueError, match="character"):
        apply_request_observations({"caster": {}, "live_observations": obs})


def test_raw_career_validated_before_worn_item_fold():
    with pytest.raises(ValueError, match="career"):
        normalize_character(snapshot(career="bad", items=[{"templateIndex":109, "equipSlot":21, "material":513}]))


def test_overlay_validates_base_caster_before_assignment():
    with pytest.raises(ValueError, match="caster"):
        normalize_character({"kind":"character","schema_version":1,"caster":{},"gear":{"base_caster":"bad"},
                             "live_observations":{"current_sp":{"value":42,"source":"sheet","observed_at_ms":0}}})


def test_version_skewed_slot_card_cannot_relabel_v1_payload(tmp_path):
    (tmp_path / "SaveData.txt").write_text(json.dumps(snapshot()), encoding="utf8")
    (tmp_path / "SaveInfo.txt").write_text('{"saveVersion":2}', encoding="utf8")
    with pytest.raises(ValueError, match="version"):
        import_character(tmp_path)
