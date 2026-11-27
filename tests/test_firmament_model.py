import json
from pathlib import Path

import pytest

from dfo_optimizer.character import import_character
from dfo_optimizer.firmament import firmament_catalog, optimize_firmament, validate_allocation
from dfo_optimizer.firmament_projection import maximum_sp_reference, project_reference, tree_vectors


def test_catalog_contains_pinned_tree_geometry_and_law():
    catalog = firmament_catalog()
    assert len(catalog["nodes"]) == 518
    assert len(catalog["starts"]) == 7
    mage = catalog["nodes"]["mg.start"]
    assert mage["name"] == "The Mage"
    assert mage["stats"]["intelligence"] == 2
    assert "mg.start" in catalog["nodes"]["mg.bt"]["adjacent"]


def test_craft_before_stars_and_disconnected_allocations():
    tree = {"start": "mg.start", "keys": ["mg.bt"]}
    result = validate_allocation(tree, 2, 1)
    assert (result["stars_left"], result["craft_left"]) == (2, 0)
    assert validate_allocation(tree, 2, 0)["stars_left"] == 1
    with pytest.raises(ValueError, match="connected"):
        validate_allocation({"start": "mg.start", "keys": ["wr.bt"]}, 3, 1)


def test_saved_character_extends_tracked_tree_in_native_search():
    character = import_character(Path(__file__).parent / "fixtures/character/export.zip", slot=0)
    result = optimize_firmament({
        "character": character,
        "tree": {"start": "mg.start", "keys": ["mg.bt"]},
        "stars": 3,
        "craft": 1,
        "target": {"id": "practice", "hp": 60, "willpower": 40},
        "spell_index": 0,
        "search": {"exact": True},
    })
    assert result["engine"] == "native-cython-cpp17"
    assert result["exact"]
    assert result["nodes"] > 1
    assert result["baseline"]["tree"]["keys"] == ["mg.bt"]
    assert result["baseline"]["available_sp"] > 0
    assert result["candidates"]
    assert all("mg.bt" in row["tree"]["keys"] for row in result["candidates"])


def test_scalar_projection_matches_the_pinned_game_runtime():
    fixture = json.loads((Path(__file__).parent / "fixtures/firmament-oracle.json").read_bytes())
    catalog = firmament_catalog()
    assert fixture["source_sha"] == catalog["source_sha"]
    for case in fixture["cases"]:
        query, expected = case["input"], case["expected"]
        state = validate_allocation(query["tree"], query["stars"], query["craft"])
        assert state["stars_left"] == expected["left"]["stars"]
        assert state["craft_left"] == expected["left"]["craft"]
        basis = (query["speed"], query["intelligence"], query["destruction"], 0, 12, 0, query["stars"])
        gains, prices = tree_vectors(state["tree"], catalog)
        context = project_reference({"speed": query["speed"], "live_skill": query["destruction"],
                                     "power_pct": 0, "pierce": 0, "cast_speed_pct": 0}, basis, gains, prices)
        assert context["live_skill"] == expected["skill"]
        assert context["power_pct"] == expected["spellPower"]
        assert context["pierce"] == expected["spellPierce"]
        assert context["firmament_cost_pct"] == expected["destructionCost"]
        assert (35 * (100 - context["firmament_cost_pct"]) + 50) // 100 == expected["castCost"]
        assert 1 + (context["speed"] - 50) / 200 + context["cast_speed_pct"] / 100 == pytest.approx(
            expected["speedRate"]
        )
        assert maximum_sp_reference(basis, gains, prices, 0) == expected["magicka"]
