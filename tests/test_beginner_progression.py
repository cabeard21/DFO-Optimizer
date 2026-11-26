"""Paired role states used for every independent beginner scenario."""

import pytest

from dfo_optimizer.beginner_progression import CheckpointCache
from dfo_optimizer.build_baselines import resolve_family_baseline
from dfo_optimizer.ruleset import load_ruleset


@pytest.fixture(scope="module")
def rules():
    return load_ruleset()


def birth(rules, seed=42):
    return {**resolve_family_baseline("m1-breton-caster", rules), "roll_seed": seed}


def test_single_path_funded_snapshots_and_gear_sensitivity(rules):
    cache = CheckpointCache(rules)
    result = cache.project(birth(rules), levels=(1, 15, 45), family="breton")
    assert result["status"] == "complete", result.get("first_gap")
    early, mid, cap = result["checkpoints"]
    assert [p["level"] for p in (early, mid, cap)] == [1, 15, 45]
    assert all(p["family"] == "breton" and p["roll_seed"] == 42 for p in (early, mid, cap))
    assert mid["effort"]["practice"] < cap["effort"]["practice"]
    assert set(mid["state"]["mastered"]) <= set(cap["state"]["mastered"])
    assert "Arcane Arrow" in str(early["spells"])
    assert not early["acquisitions"]
    assert sum(result["policy"]["birth_allocation"]) == result["policy"]["birth_attribute_pool"]
    assert mid["acquisitions"] == cap["acquisitions"]
    assert {a["kind"] for a in mid["acquisitions"]} >= {"gear", "combat_spell"}
    no_gear = mid["variants"]["owned_only"]
    no_spell = mid["variants"]["no_spell_purchase"]
    assert len(no_gear["inventory"]) < len(mid["inventory"])
    assert no_gear["state"]["gold"] == mid["state"]["gold"] + sum(
        a["gold"] for a in mid["acquisitions"] if a["kind"] == "gear"
    )
    assert len(no_spell["spells"]) < len(mid["spells"])
    assert no_spell["state"]["gold"] == mid["state"]["gold"] + sum(
        a["gold"] for a in mid["acquisitions"] if a["kind"] == "combat_spell"
    )
    assert all(p["actor"]["current_sp"] == p["state"]["sp"] for p in (early, mid, cap))
    assert all(0 < p["state"]["fatigue"] <= p["state"]["max_fatigue"] for p in (early, mid, cap))
    assert all(p["state"]["gold"] >= 0 for p in (early, mid, cap))
    assert result["counters"]["nodes"] > 1000
    # A caller editing one scenario cannot alter the cache or the next paired view.
    mid["state"]["skills"][22] = -999
    again = cache.project(birth(rules), family="breton")
    assert again["cache_hit"] and again["counters"]["nodes"] == 0
    assert again["checkpoints"][1]["state"]["skills"][22] > 0


def test_limited_trial_never_synthesizes_cap_and_can_retry(rules):
    cache = CheckpointCache(rules)
    limited = cache.project(birth(rules), max_nodes=1)
    assert limited["status"] != "complete" and limited["first_gap"]
    assert [p["level"] for p in limited["checkpoints"]] == [1]
    result = cache.project(birth(rules), levels=(1, 15), max_nodes=100_000)
    assert result["status"] == "complete" and not result["cache_hit"]
    assert [p["level"] for p in result["checkpoints"]] == [1, 15]


def test_distinct_rolls_and_creation_only_projection(rules):
    cache = CheckpointCache(rules)
    one, two = [cache.project(birth(rules, seed), levels=(1,)) for seed in (42, 43)]
    assert one["checkpoints"][0]["state"]["attributes"] != two["checkpoints"][0]["state"]["attributes"]
    assert not two["cache_hit"] and one["checkpoints"][0]["effort"]["practice"] == 0
    with pytest.raises(ValueError, match="levels"):
        cache.project(birth(rules), levels=(15, 1))


def test_legal_plate_and_single_proficient_weapon_in_paired_sensitivities(rules):
    import json

    from dfo_optimizer.beginner_equipment import bind_physical_player
    from dfo_optimizer.ruleset import DATA

    row = json.loads((DATA / "beginner-manual.json").read_text())[0]
    start = {"type": "new_character", "roll_seed": 42, "class": row["class"], "race_id": row["race_id"]}
    role = CheckpointCache(rules).project(start, levels=(1, 15))
    born, mid = role["checkpoints"]
    for p in (born, mid, mid["variants"]["owned_only"]):
        physical = bind_physical_player(p)
        assert physical["weapon"]["templateIndex"] != 113  # Long Blade major, common backup dagger.
    assert any(item.get("material") == 512 for item in bind_physical_player(mid)["armor"])
    assert mid["carry"]["headroom_kg"] >= 0
    assert not any(
        item.get("material") == 512 for item in bind_physical_player(mid["variants"]["owned_only"])["armor"]
    )
    assert mid["state"]["gold"] == born["state"]["gold"] + sum(t["delta_gold"] for t in mid["transactions"])
    mid["state"]["attributes"][4] = -10
    assert mid["variants"]["owned_only"]["state"]["attributes"][4] > 0


def test_limited_cap_keeps_only_independently_reached_levels_and_skill_points(rules):
    cache = CheckpointCache(rules)
    capped = cache.project(birth(rules), max_nodes=4000)
    assert capped["status"] != "complete"
    assert [p["level"] for p in capped["checkpoints"]] == [1, 15]
    assert capped["checkpoints"][1]["effort"]["practice"] > 0
    allocation = capped["policy"]["realized_birth_skill_allocation"]
    assert [sum(allocation[k]) for k in ("primary", "major", "minor")] == [6, 6, 6]
    first = capped["policy"]["first_earned_level"]
    assert first["level"] == 2 and sum(first["attribute_gains"]) > 0
    assert first["practice"] < capped["checkpoints"][1]["effort"]["practice"]
    assert capped["first_gap"]["reached_level"] >= 15


def test_slow_all_metals_caster_reaches_cap_on_same_declared_training_policy(rules):
    import json

    from dfo_optimizer.ruleset import DATA

    row = json.loads((DATA / "beginner-manual.json").read_text())[0]
    unrestricted = {**row["class"], "disadvantages": []}
    role = CheckpointCache(rules).project(
        {"type": "new_character", "roll_seed": 42, "class": unrestricted, "race_id": row["race_id"]}
    )
    assert role["status"] == "complete", role["first_gap"]
    cap = role["checkpoints"][-1]
    assert cap["level"] == 45 and cap["career"]["advancementMultiplier"] > 2.5
    assert cap["career"]["forbiddenMaterialsFlags"] == 0
    assert role["counters"]["native_batches"] >= 2


def test_cancel_or_timeout_during_independent_replay_preserves_only_verified_birth(rules, monkeypatch):
    from dfo_optimizer import _progression, progression

    token = _progression.CancelToken()
    assert not token.cancelled()
    transition = progression.transition

    def interrupt(*args):
        token.cancel()
        return transition(*args)

    monkeypatch.setattr(progression, "transition", interrupt)
    role = CheckpointCache(rules).project(birth(rules), levels=(1, 15), cancel=token)
    assert role["status"] == "cancelled" and role["termination"] == "cancelled"
    assert role["first_gap"]["phase"] == "independent_replay"
    assert [p["level"] for p in role["checkpoints"]] == [1]
    assert role["counters"]["nodes"] > 0
    expired = CheckpointCache(rules).project(birth(rules), wall_seconds=0.00000001)
    assert expired["termination"] == "time_limit" and expired["counters"]["nodes"] == 0
