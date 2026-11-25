"""Replay consumed artifacts and account-bound Firmament choices at the exact stage."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from dfo_optimizer.progression import plan_progression, replay_progression


def base():
    path = Path(__file__).resolve().parents[1] / "examples" / "progression-tradeoffs.json"
    return json.loads(path.read_text())


@pytest.mark.parametrize("artifact_fields", [{"artifact":True}, {}])
def test_consuming_one_observed_oghma_at_cap_clips_stats_and_clears_the_latch(artifact_fields):
    q = base()
    save = q["start"]["character"]
    save["level"] = 45
    save["items"].append({"group":"Books",**artifact_fields,"enchantments":[{"type":26,"param":5}]})
    action = {"kind":"oghma","copy":"save:pack:1","allocation":[0,30,0,0,0,0,0,0]}
    q.update(stages=[[action]], goal={"attributes":{"1":100}})
    result = plan_progression(q)
    assert result["status"] == "optimal_proven" and replay_progression(result)["valid"]
    end = result["routes"][0]["state"]
    assert end["level"] == 45 and end["attributes"][1] == 100
    assert end["oghma_remaining"] == [] and end["pending_level"] == -1
    assert save["stats"]["intelligence"] == 70 and len(save["items"]) == 2
    second = deepcopy(q)
    second["search"]["final_stage_only"] = True
    second["stages"] *= 2
    assert not plan_progression(second)["routes"]


def test_an_item_name_cannot_establish_an_oghma_artifact():
    q = base()
    q["start"]["character"]["items"].append({"group":"Books","name":"Oghma Infinium","artifact":True})
    q.update(stages=[[{"kind":"oghma","copy":"save:pack:1","allocation_order":list(range(8))}]],
             goal={"attributes":{"0":100}})
    result = plan_progression(q)
    assert result["status"] == "unsupported" and "artifact" in str(result["first_gap"])


def test_firmament_sign_and_connected_life_star_use_observed_craft_purse():
    q = base()
    empty = {"start":None, "keys":[]}
    mage = {"start":"mg.start", "keys":[]}
    target = {"start":"mg.start", "keys":["mg.bt"]}
    q["start"]["firmament"] = {"tree":empty, "renown":1, "profession_ranks":[8]+[0]*9,
                              "source":"Synthetic account tree and purses", "observed_at_ms":100,
                              "access":True, "character_id":q["start"]["character"]["characterId"]}
    q.update(stages=[[{"kind":"firmament","from":empty,"node":"mg.start"}],
                     [{"kind":"firmament","from":mage,"node":"mg.bt"}]], goal={"firmament":target})
    out = plan_progression(q)
    assert out["status"] == "optimal_proven" and replay_progression(out)["valid"]
    final = out["routes"][0]["state"]["firmament"]
    assert final["tree"] == target and final["craft_left"] == final["stars_left"] == 0
    assert out["routes"][0]["checkpoints"][0]["state"]["firmament"]["tree"] == empty
    q["start"]["firmament"]["profession_ranks"] = [0]*10
    assert "points" in str(plan_progression(q)["first_gap"])
    q["stages"][1][0]["node"] = "wr.k"
    assert "connected" in str(plan_progression(q)["first_gap"])
    q["start"]["firmament"]["character_id"] = "a different character"
    with pytest.raises(ValueError, match="character"):
        plan_progression(q)
