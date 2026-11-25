"""The public gear request must preserve acquisition evidence and copy identity."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from dfo_optimizer.gear import GearService
from dfo_optimizer.gear_request import prepare_inventory

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def example(name):
    return json.loads((EXAMPLES / f"gear-{name}.json").read_text())


def item(key, *, owned=True, price=None, available=True):
    return {
        "instance_id": key,
        "item": {"group": "Jewellery", "templateIndex": 135},
        "acquisition": {"owned": owned, "obtainable": available, "price": price},
    }


def test_owned_and_budget_use_positive_evidence():
    raw = {"inventory": [item("own"), item("unknown", owned=False),
                         item("buy", owned=False, price={"gold": 3})],
           "budget": {"gold": 5}, "career": {}, "mode": "owned_plus_budget"}
    before = deepcopy(raw)
    prepared = prepare_inventory(raw)
    assert [row.identity for row in prepared.items] == ["buy", "own"]
    assert prepared.filtered["unknown"] == ("price_unknown",)
    assert raw == before
    owned = prepare_inventory({**raw, "mode": "owned_only"})
    assert [row.identity for row in owned.items] == ["own"]


def test_catalog_prices_stay_unknown_and_currencies_distinct():
    records = [item("a", owned=False, price={"gold": 2, "marks": 1}),
               item("b", owned=False, available=None)]
    prepared = prepare_inventory({"inventory": records, "mode": "owned_plus_budget",
                                  "budget": {"gold": 20}, "career": {}})
    assert prepared.filtered == {"a": ("budget",), "b": ("availability_unknown",)}


def test_copy_ids_unique_and_repair_unavailable():
    with pytest.raises(ValueError, match="duplicate"):
        prepare_inventory({"inventory": [item("a"), item("a")], "career": {}})
    prepared = prepare_inventory({"inventory": [{**item("r"), "container": "repair"}],
                                  "career": {}})
    assert prepared.filtered["r"] == ("container_unavailable",)


def test_locked_missing_never_relaxes():
    with pytest.raises(ValueError, match="lock"):
        prepare_inventory({"inventory": [item("a")], "locks": {"Ring0": "missing"},
                           "career": {}})


@pytest.mark.parametrize("mode", ["owned", "budget", "catalog", "bis"])
def test_worked_acquisition_modes(mode):
    req = example(mode)
    before = deepcopy(req)
    result = GearService().optimize(req)
    assert req==before and result["candidates"] and result["result_hash"]
    assert result["validation"]["finalists_checked"]==len(result["candidates"])
    for c in result["candidates"]:
        assert len(c["loadout"])==27
        assert c["metrics"]["affordable"] and c["validated"]
        if mode=="owned":
            assert all(i["owned"] for i in c["items"])
            assert c["purchases"]==[]
        elif mode=="budget":
            assert 0<=c["budget_remaining"]["gold"]<=120
            assert "unknown-quote" in result["filtered"]
    if mode in {"catalog","bis"}:
        assert result["generated_candidates"]>0
        assert any(not i["owned"] for c in result["candidates"] for i in c["items"])
    else:
        assert result["status"]=="optimal_proven" and result["exact"]
        assert result["marginals"]


def test_fixed_change_and_full_reoptimization():
    req = example("budget")
    req["spell"] = json.loads((EXAMPLES/"spell-fixed.json").read_text())["spell"]
    del req["domain"]
    service = GearService()
    initial = service.evaluate(req)
    assert initial["candidates"][0]["loadout"]["Ring0"]=="worn-focus"
    assert initial["candidates"][0]["changed_slots"]=={}
    opt = service.optimize(req)
    for key,marginal in opt["marginals"].items():
        if marginal["status"]=="locked":
            continue
        alt=service.optimize({**req,"marginals":False,"exclusions":[key]})
        assert marginal["best_dps_without"]==max(c["metrics"]["dps"] for c in alt["candidates"])
    locked=service.evaluate({**req,"locks":{"Ring0":"worn-focus"},"loadout":{"Ring0":"worn-focus"}})
    assert locked["candidates"][0]["loadout"]==initial["candidates"][0]["loadout"]
    with pytest.raises(ValueError,match="conflict"):
        service.evaluate({**req,"locks":{"Ring0":"training-ring"}})


def test_unknown_item_rules_and_missing_observations():
    req=example("owned")
    req["caster"]["current_sp"]=None
    r=GearService().optimize(req)
    assert r["status"]=="unsupported" and not r["candidates"]
    req["caster"]["current_sp"]=30
    del req["domain"]
    with pytest.raises(ValueError,match="exactly one"):
        GearService().optimize(req)
    req["spell"]=json.loads((EXAMPLES/"spell-fixed.json").read_text())["spell"]
    req["inventory"][0]["item"]["artifact"]=True
    assert GearService().evaluate(req)["status"]=="unsupported"


def test_cancellation_budget_and_repeatability():
    from dfo_optimizer._gear import CancelToken
    req=example("owned")
    req["marginals"]=False
    token=CancelToken()
    token.cancel()
    assert GearService().optimize(req,cancel=token)["status"]=="cancelled"
    req["search"]={"max_nodes":20,"wall_seconds":0}
    a,b=(GearService().optimize(req) for _ in range(2))
    assert a["result_hash"]==b["result_hash"]
    assert a["termination"]=="node_limit" and not a["exact"]


def test_multi_resource_and_unknown_budget_refusal():
    req=example("budget")
    req["budget"]["gold"]=501
    with pytest.raises(ValueError,match="available gold"):
        GearService().optimize(req)
    req["budget"]={"gold":2,"marks":1}
    req["offers"]=[{**item("new",owned=False,price={"gold":2,"marks":2})}]
    assert GearService().optimize(req)["filtered"]["new"]==("budget",)


def test_sp_cap_and_external_pool_after_removing_intelligence():
    request = example("owned")
    request.pop("domain")
    request["spell"] = {"effect_id":"4,0","element":0,"range_type":1,
        "base_low":3,"base_high":3,"plus_low":1,"plus_high":1,"per_level":8}
    request["caster"].update(current_sp=15,max_sp=None,destruction_live=50,level=1)
    request["inventory"] = [{"instance_id":"int","item":{"templateIndex":135,"group":"Jewellery",
        "equipSlot":4,"rarity":"magic","affixes":[{"id":"stat","param":"intelligence","value":5}]}}]
    request["capacity"]={"intelligence":10,"non_equipment_bonus":0}
    request["locks"]={"Ring0":None,"Ring1":None}
    # 3 base * 20 * 60 / 400 = 9; this fits the stripped ten-SP cap.
    answer=GearService().optimize(request)
    assert answer["candidates"][0]["effective"]["available_sp"]==10
    request["spell"].update(base_low=4,base_high=4)
    assert GearService().optimize(request)["status"]=="infeasible_proven"
    request.pop("capacity")
    assert GearService().optimize(request)["status"]=="no_feasible_found"
    request["capacity"]={"post_swap_sp":15}
    claimed=GearService().optimize(request)
    assert claimed["candidates"] and "hypothetical" in claimed["resource_policy"]


def test_offer_cannot_create_ownership():
    with pytest.raises(ValueError,match="owned"):
        prepare_inventory({"career":{},"offers":[item("invented",owned=True)]})


def test_keep_empty_left_hand_excludes_two_hander_but_worn_quest_accepts_it():
    req=example("owned")
    req["inventory"]=[{"instance_id":"bow","item":{"group":"Weapons","templateIndex":129,
                       "equipSlot":19,"material":0}}]
    held=GearService().evaluate(req)
    assert held["candidates"][0]["occupancy"]["LeftHand"]=="bow"
    assert held["candidates"][0]["loadout"]["LeftHand"] is None
    req["locks"]={"LeftHand":None,"RightHand":"bow"}
    blocked=GearService().optimize(req)
    assert blocked["status"]=="infeasible_proven" and not blocked["candidates"]
