import pytest

from dfo_optimizer.beginner_equipment import bind_physical_player
from dfo_optimizer.physical_encounter import PhysicalGap


def checkpoint():
    def item(index, group):
        return {"templateIndex": index, "group": group, "material": 0,
                "currentCondition": 25, "maxCondition": 100}
    return {"state": {"level": 1, "race_id": 1, "attributes": [50] * 8, "skills": [20] * 35,
                      "career": {}, "arcane_path": -1, "martial_path": -1, "fatigue": 93},
            "loadout": {"RightHand": "knife", "ChestArmor": "cuirass"},
            "inventory": [{"instance_id": "knife", "item": item(113, "Weapons")},
                          {"instance_id": "cuirass", "item": item(102, "Armor")},
                          {"instance_id": "staff", "item": item(115, "Weapons")},
                          {"instance_id": "shield", "item": item(109, "Armor")}]}


def test_physical_player_uses_chosen_physical_copy_and_only_equipped_armor():
    cp = checkpoint()
    fighter = bind_physical_player(cp)
    assert fighter["weapon"]["currentCondition"] == 25
    assert fighter["fatigue"] == 93
    assert [item["templateIndex"] for item in fighter["armor"]] == [102]
    assert bind_physical_player(cp, {})["armor"] == []
    assert bind_physical_player(cp, {})["weapon"] is None


@pytest.mark.parametrize("layout", [{"RightHand": "missing"}, {"RightHand":"staff","LeftHand":"shield"},
                                     {"LeftHand": "knife","RightHand": "knife"}, {"Head":"knife"}])
def test_illegal_or_unowned_layout_cannot_improve_survival(layout):
    with pytest.raises(ValueError):
        bind_physical_player(checkpoint(), layout)


def test_missing_condition_and_unsupported_effect_stay_visible():
    cp = checkpoint()
    del cp["inventory"][0]["item"]["currentCondition"]
    with pytest.raises(PhysicalGap, match="condition"):
        bind_physical_player(cp)
    cp = checkpoint()
    cp["inventory"][1]["item"]["customEnchantments"] = [{"id": "unknown"}]
    with pytest.raises(PhysicalGap, match="effect"):
        bind_physical_player(cp)


def test_combat_reads_earned_mastered_skill_through_source_soft_cap():
    cp = checkpoint()
    cp["state"]["skills"][:2] = [200, 150]
    cp["state"]["mastered"] = [0]
    assert bind_physical_player(cp)["skills"][:2] == [140, 100]
