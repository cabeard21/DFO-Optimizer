import json
from pathlib import Path

import pytest

from dfo_optimizer.equipment import equipment_catalog, gear_catalog_scope, inspect_item, legal_catalog_items


def item(index, **extras):
    return {"templateIndex": index, **extras}


def inspect(index, **extras):
    return inspect_item(item(index, **extras), career={})


def test_catalog_shapes_and_occupancy():
    cat = equipment_catalog()
    assert len(cat["slots"]) == 27
    assert cat["slots"]["RightHand"] == 19
    assert cat["templates"]["135"]["group"] == "Jewellery"
    assert inspect(135)["placements"] == [{"slot": 4, "mask": 16}, {"slot": 5, "mask": 32}]
    assert inspect(115, material=0)["placements"] == [{"slot": 19, "mask": (1 << 19) | (1 << 21)}]
    assert inspect_item(item(129, material=0), career={}, bow_left_hand=True)["placements"] == [{"slot": 21, "mask": 1 << 21}]
    assert inspect(140)["placements"] == []


def test_source_restriction_and_retained_worn():
    career = {"forbiddenMaterialsFlags": 2}
    assert inspect_item(item(109, material=513), career=career)["placements"] == []
    assert inspect_item(item(102, material=256), career=career)["placements"]
    kept = inspect_item(item(109, material=513), career=career, worn_slot=21)
    assert kept["placements"] == [{"slot": 21, "mask": 1 << 21}]
    assert kept["keep_only"]
    assert inspect(135, currentCondition=0)["placements"] == []
    assert inspect(135, currentCondition=1)["placements"]


@pytest.mark.parametrize("index,slot", [(520, 18), (522, 12), (525, 15)])
def test_reviewed_rri_light_armor_slots_and_career_restrictions(index, slot):
    armor = item(index, group="Armor", material=513, rriVariant=True)
    assert inspect_item(armor, career={})["placements"] == [{"slot": slot, "mask": 1 << slot}]
    assert not inspect_item(armor, career={"weaponArmorShieldsBitfield": 1 << 6})["placements"]
    assert inspect_item(armor, career={"weaponArmorShieldsBitfield": 1 << 8})["placements"]
    assert not inspect_item(armor, career={"forbiddenMaterialsFlags": 2})["placements"]
    assert not list(legal_catalog_items({}, theoretical=True, template_indices=[index]))


def test_unknown_career_and_unsupported_effect_are_visible():
    assert not inspect_item(item(113, material=0), career=None)["placements"]
    assert inspect(135, enchantments=[{"type": 1, "param": 44}])["unsupported"]
    assert inspect(135, sigil={"rank": 1})["unsupported"]
    assert inspect(999999)["unsupported"]


def test_legal_catalog_generator_keeps_price_unknown():
    for theoretical in (False, True):
        rows = list(legal_catalog_items({}, theoretical=theoretical, access=["tier6_pile_level45_luck50"]))
        assert rows and all(r["acquisition"]["price"] is None for r in rows)
        assert len({r["instance_id"] for r in rows}) == len(rows)
        assert all(r["container"] == "catalog" and r["acquisition"]["owned"] is False
                   and r["acquisition"]["hypothetical"] is theoretical for r in rows)
    assert any(r["item"].get("affixes") for r in rows)


def test_source_oracle_independent_rows():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "equipment_oracle.json").read_text())
    for case in fixture["eligibility"]:
        report = inspect_item(case["item"], career=case["career"])
        assert bool(report["placements"]) == case["can_equip"]
    for case in fixture["modifiers"]:
        report = inspect_item(case["item"], career={})
        assert report["unsupported"] == []
        for field, expected in case["expected"].items():
            assert report["modifiers"][field] == expected


@pytest.mark.parametrize("data", [{"group": []}, {"templateIndex": True}, {"templateIndex": 113, "material": "steel"}])
def test_reject_malformed_input(data):
    with pytest.raises(ValueError):
        inspect_item(data, career={})


def test_catalog_is_detached_and_requires_explicit_access():
    assert not list(legal_catalog_items({}, theoretical=False))
    a = equipment_catalog()
    a["slots"].clear()
    assert len(equipment_catalog()["slots"]) == 27
    assert "tier 6" in gear_catalog_scope(False)
    assert "Theoretical" in gear_catalog_scope(True)


def test_all_constructed_rolls_respect_templates_and_legal_ranges():
    character = {"gear": {"career": {"forbiddenMaterialsFlags": 1}}}
    rolls = list(legal_catalog_items(character, theoretical=True))
    constructed = [r["item"] for r in rolls if r["instance_id"].startswith("catalog-ideal-")]
    assert {i["group"] for i in constructed} == {"Armor","Weapons","Jewellery","MensClothing","WomensClothing"}
    assert {i["rarity"] for i in constructed} == {"magic","rare"}
    for i in constructed:
        report = inspect_item(i, career=character["gear"]["career"])
        assert report["placements"] and not report["unsupported"], i
    assert all(i.get("material") != 0 for i in constructed if i["group"] == "Weapons")
    assert all(i["item"]["templateIndex"] == 135 for i in legal_catalog_items({}, theoretical=True, template_indices=[135]))


@pytest.mark.parametrize("item_data,issue", [
    ({"templateIndex": 135, "rarity": "aetheric"}, "unsupported_rarity"),
    ({"templateIndex": 135, "rarity": "magic", "affixes": [{"id":"focus","value":3}]}, "affix_count"),
    ({"templateIndex": 135, "rarity": "magic", "affixes": [{"id":"unknown","value":3}]}, "affix:unknown"),
    ({"templateIndex": 135, "rarity": "magic", "affixes": [{"id":"skill","param":22,"value":99}]}, "affix_value"),
    ({"templateIndex": 135, "rarity": "magic", "affixes": [{"id":"skill","param":44,"value":6}]}, "affix_parameter"),
    ({"templateIndex": 135, "rarity": "magic", "affixes": [{"id":"damage","value":6}]}, "affix_group"),
    ({"templateIndex": 135, "rarity": "magic", "affixes": [{"id":"skill","param":22,"value":6}]*2}, "duplicate_affix"),
    ({"templateIndex": 135, "rarity": "magic", "sockets":["ruby"]}, "socket_layout"),
    ({"templateIndex": 135, "rarity": "rare", "sockets":["ruby"]}, "socket_affixes"),
    ({"templateIndex": 135, "rarity": "rare", "affixes":[]}, "unverified_rare_flavour"),
    ({"templateIndex": 135, "affixes":[{"id":"focus","value":4}]}, "unclassified_roll"),
    ({"templateIndex": 135, "rarity": "legendary", "legendary": "unknown"}, "unverified_legendary_record"),
    ({"templateIndex": 135, "enchantments":[{"type":10, "param":55}]}, "unknown_enchantment_parameter"),
    ({"templateIndex": 135, "artifact":True}, "artifact"),
    ({"templateIndex": 135, "magic":True}, "unknown_magic_effects"),
    ({"templateIndex": 135, "enchantments":[{"type":10, "param":22}]}, "unverified_enchantments"),
    ({"templateIndex": 135, "magic":True, "enchantments":[{"type":10, "param":22}]*2}, "unverified_enchantments"),
    ({"templateIndex": 135, "enchantments":[{"enchantCost":1,"type":10,"param":22}]}, "maker_enchantments"),
    ({"templateIndex": 135, "rarity":"rare","sockets":["empty"],"bound":True}, "socket_layout"),
    ({"templateIndex": 135, "customEnchantments":[{"type":1, "param":6}]}, "customEnchantments"),
])
def test_invalid_roll_or_unsupported_power_cannot_enter_ranking(item_data,issue):
    assert issue in inspect_item(item_data, career={})["unsupported"]


def test_enhances_skill_is_separate_from_counted_legendary_affixes():
    report = inspect(135, magic=True, enchantments=[{"type":10,"param":22}])
    assert not report["unsupported"]
    assert report["modifiers"]["destruction"] == 0
    assert report["modifiers"]["enhanced_destruction"] == 15
    legendary = equipment_catalog()["legendary"]["graveward"]
    piece = item(124, group="Weapons", material=1, legendary="graveward", rarity="legendary",
                 affixes=legendary["affixes"], enchantments=[legendary["enchantment"]])
    report = inspect_item(piece, career={})
    assert report["legendary_id"] == "graveward"
    assert not report["unsupported"]


def test_ruleset_masks_condition_and_keep_slot_rejections():
    assert inspect_item(item(113), career={"forbiddenMaterialsFlags":1})["reasons"] == ["unknown_material"]
    assert inspect_item(item(109), career={"forbiddenMaterialsFlags":1})["reasons"] == ["unknown_material"]
    assert inspect(113, material=258)["reasons"] == ["invalid_material"]
    assert inspect_item(item(135), career={}, worn_slot=0)["reasons"] == ["invalid_worn_slot"]
    with pytest.raises(ValueError):
        inspect(135,currentCondition=10**400)


@pytest.mark.parametrize("settings", [{"catalog": []}, {"template_indices":[False]}, {"access":["unknown"]}])
def test_invalid_catalog_selectors(settings):
    if "catalog" in settings:
        with pytest.raises(ValueError):
            list(legal_catalog_items(settings["catalog"], theoretical=True))
    else:
        with pytest.raises(ValueError):
            list(legal_catalog_items({}, theoretical=True, **settings))


@pytest.mark.parametrize("fields", [{"rarity":[]}, {"rarity":"legendary","legendary":{}},
                                     {"affixes":[{"id":"stat","param":{},"value":2}]}])
def test_reject_malformed_roll_types(fields):
    with pytest.raises(ValueError):
        inspect(135, **fields)


@pytest.mark.parametrize("gear", [[], None, {"career":[]}, {"career":{"forbiddenMaterialsFlags":True}},
                                 {"career":{"forbiddenMaterialsFlags":"x"}},
                                 {"career":{"weaponArmorShieldsBitfield":2**32}}])
def test_reject_invalid_career_before_material_generation(gear):
    with pytest.raises(ValueError):
        list(legal_catalog_items({"gear":gear}, theoretical=True, template_indices=[113]))
