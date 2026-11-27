"""Independently check purchases, physical slots, spell records and checkpoint performance."""

from math import isclose

from .lifecycle_objectives import stage_performance
from .gear_replay import _selected, fold_worn_modifiers
from .gear_request import MODIFIERS
from .progression_replay import require
from .spellbook import replay_spell


def replay_choices(d, slots, policies, bought, native_scores=None):
    require(len(d.stages) == len(slots) == len(policies) == len(bought), "incomplete lifecycle route")
    held = d.owned
    spent = 0
    available_sp = d.states[d.indices[0]]["sp"]
    available_hp = d.states[d.indices[0]].get("hp")
    steps = []
    for n, (s, anchors, policy, acquired) in enumerate(zip(d.stages, slots, policies, bought, strict=True)):
        ctx, ceiling, prices, intel, q, worn, uncertain, sp_floor, debt_cap = s
        require(
            type(acquired) is int and 0 <= acquired < 1 << len(prices) and not held & acquired,
            "duplicate or invalid lifecycle purchase",
        )
        purchases = []
        for j, price in enumerate(prices):
            if acquired >> j & 1:
                require(price >= 0, "lifecycle purchase has no accessible quote")
                spent += price
                purchases.append({"id": d.names_all[j], "gold": price})
        require(spent <= ceiling, "lifecycle purchases consume funds committed to progression")
        held |= acquired
        require(
            len(anchors) == 27 and all(type(i) is int and -1 <= i < len(d.copies) for i in anchors),
            "invalid lifecycle physical layout",
        )
        if d.encounters:
            require(all(i < 0 or any(j == i for j,_ in d.slots[k][3]) for k,i in enumerate(anchors)),
                    "loadout lacks supported encounter defenses")
        layout = _selected({"slots": anchors}, d.domain)
        for it in layout.values():
            require(held >> d.names_all.index(it.identity) & 1, "equipped physical copy is unavailable")
        if d.declared is not None:
            require(anchors in d.declared, "loadout outside lifecycle domain")
        combat, mods = fold_worn_modifiers(
            ((it.legendary, dict(zip(MODIFIERS, it.modifiers, strict=True))) for it in layout.values()), ctx
        )
        retained = sum(it.modifiers[7] for slot, it in layout.items() if it.worn == slot and not it.legendary)
        changed = {slot: it.identity for slot, it in layout.items()} != dict(d.domain.current)
        require(
            not changed
            or not uncertain
            and (worn <= retained or q > 0 and combat["available_sp"] <= min(100, intel + retained) * q // 4),
            "unresolved swap clipping",
        )
        require(type(policy) is int and 0 <= policy < len(d.scripts), "invalid casting policy")
        names = d.scripts[policy]
        scores = []
        for name in names:
            idx = d.names.index(name)
            require(held >> (len(d.copies) + idx) & 1, "future spell used before acquisition")
            if not d.encounters:
                scores.append(replay_spell(combat, d.book[idx][1]))
        before = available_sp
        encounter = {}
        performance = {}
        if d.encounters:
            from .lifecycle_encounter import replay_point
            recipes = {k:r for k,(_,r) in zip(d.names,d.book,strict=True)}
            seen = set()
            wellspring = 0
            for it in layout.values():
                if it.legendary and it.legendary in seen:
                    continue
                seen.add(it.legendary)
                wellspring += sum(a["value"] for a in it.item.get("affixes", []) if a["id"] == "wellspring")
            require(not wellspring or (len(d.stages) == 1 and mods["intelligence"] == worn),
                    "Wellspring requires verified pool capacity and fractional recovery carry")
            dps,trial = replay_point(d.encounters[n],combat,recipes,names,available_hp,before,min(10,wellspring))
            encounter = {"encounter": {"initial_hp": available_hp, **trial}}
            if d.objective != "legacy":
                performance = stage_performance(trial["damage"], trial["spent_sp"], trial, d.encounters[n][0]["horizon_us"])
            available_sp, available_hp = trial["end_sp"], trial["end_hp"]
            require(available_hp > 0 or n+1 == len(d.indices),"dead character entered a later encounter")
            sp = before - available_sp
        else:
            sp = sum(v["cost_sp"] for v in scores)
            require(sp <= before, "policy exceeds spendable SP after previous casts")
            if d.objective != "legacy":
                performance = stage_performance(sum(v["expected_health_loss"] for v in scores), sp)
            available_sp -= sp
            dps = sum(v["dps"] for v in scores) / len(scores) if scores else 0.
            allow_wait = not names and n == 0 and len(d.stages) > 1 and d.source.get("boundary") == "creation"
            require(dps > 0 or allow_wait, "policy fails positive damage floor")
        if native_scores is not None:
            require(
                isclose(native_scores[n], dps, rel_tol=1e-10, abs_tol=1e-11),
                "native checkpoint score differs from independent replay",
            )
        stage = d.indices[n]
        steps.append(
            {
                "stage": stage,
                "level": d.states[stage]["level"],
                "dps": dps,
                "sp_available": before,
                "policy_sp": sp,
                "sp_after_policy": before - sp,
                "spent_gold": spent,
                "gold_after_purchases": d.states[stage]["gold"] - spent,
                "new_purchases": purchases,
                "loadout": {label: layout[i].identity for label, i in d.domain.slots.items() if i in layout},
                "casting_policy": names,
                **encounter,
                **({"performance": performance} if performance else {}),
                **({"firmament_modifiers": d.firmament[n]} if d.firmament and d.firmament[n] else {}),
                "spellbook": [name for j, name in enumerate(d.names, len(d.copies)) if held >> j & 1],
            }
        )
        next_stage = d.indices[n + 1] if n + 1 < len(d.indices) else stage
        for j in range(stage + 1, next_stage + 1):
            action = d.actions[j - 1]
            if action["kind"] == "rest" and action.get("recovery") == "full_bed":
                available_sp = d.states[j]["sp"]
                available_hp = d.states[j].get("hp")
            elif action["kind"] == "rest":
                available_sp = max(available_sp, action.get("refill_sp", 0))
            else:
                available_sp += d.states[j]["sp"] - d.states[j - 1]["sp"]
            require(available_sp >= 0, "previous checkpoint casts consumed SP required for training")
            require(d.states[j]["gold"] >= spent, "prior purchases consumed funds reserved for training")
    return steps
