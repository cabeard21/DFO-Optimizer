"""Compare fixed classes on a common panel of independently replayed fights."""
from collections import defaultdict
from statistics import fmean

from .character import _hash


def cell_key(row):
    return (row["scenario"], row["stage"], row["variant"], row["roll_seed"], row["seed"])


def evaluate_metrics(rows, *, plate_weapon_materials, advancement_multiplier, mean_practice):
    if not rows or any(row["status"] != "replayed" for row in rows):
        raise ValueError("Every required encounter must have a replayed outcome")
    groups = defaultdict(dict)
    for row in rows:
        case, stage, variant, birth, combat = cell_key(row)
        group = groups[case, stage, variant]
        if (birth, combat) in group:
            raise ValueError("duplicate encounter cell")
        group[birth, combat] = row
    keys = next(iter(groups.values())).keys()
    if any(group.keys() != keys for group in groups.values()):
        raise ValueError("Cannot compare a partially paired encounter panel")
    clear = [fmean(r["survived"] and r["cleared"] for r in g.values()) for g in groups.values()]
    survival = [fmean(r["survived"] for r in g.values()) for g in groups.values()]
    cap = [r for r in rows if r["stage"] == "cap"]
    elapsed = sum(r["censored_clear_us"] for r in cap)
    dungeon = [r for r in rows if r["scenario"] == "sustained"]
    paid = sum(r["spent_sp"] for r in dungeon)
    spell_damage = sum(r["damage"] - r.get("physical_damage", 0) for r in dungeon)
    return {
        "worst_clear_rate": min(clear), "worst_survival_rate": min(survival),
        "mean_survival_rate": fmean(survival),
        "mean_clear_rate": fmean(clear), "plate_weapon_materials": plate_weapon_materials,
        "advancement_multiplier": advancement_multiplier, "mean_practice": mean_practice,
        "mean_censored_clear_fraction": fmean(r["censored_clear_us"] / r["horizon_us"] for r in rows),
        "cap_damage_per_second": 1_000_000 * sum(r["damage"] for r in cap) / elapsed if elapsed else None,
        "mean_damage_per_sp": spell_damage / paid if paid else None,
        "min_hp_fraction": min(r["minimum_hp"] / r["max_hp"] for r in rows),
        "mean_min_hp_fraction": fmean(r["minimum_hp"] / r["max_hp"] for r in rows),
    }


def ranking_key(row):
    m = row["metrics"]
    return (-m["worst_clear_rate"], -m["worst_survival_rate"], -m["mean_clear_rate"],
            -m["plate_weapon_materials"], m["advancement_multiplier"], m["mean_practice"],
            m["mean_censored_clear_fraction"], row["id"])


def construction(row):
    doc = row["class"]
    return _hash([row["race_id"], doc["skills"], doc["advantages"], doc["disadvantages"]])


def pick_builds(rows, preferred=None):
    if not rows:
        return None, []
    winner = min(rows, key=ranking_key) if preferred is None else preferred
    used = {construction(winner)}
    alternatives = []
    for role, axes in (("Damage mage", ("cap_damage_per_second",)),
                       ("Durable battlemage", ("worst_survival_rate", "mean_survival_rate", "mean_min_hp_fraction")),
                       ("Resource-efficient dungeon mage", ("mean_damage_per_sp",))):
        def values(row):
            return tuple(row["metrics"][axis] for axis in axes)
        baseline = values(winner)
        eligible = [r for r in rows if construction(r) not in used and None not in values(r)
                    and None not in baseline and values(r) > baseline]
        if eligible:
            best = min(eligible, key=lambda r: (tuple(-v for v in values(r)), ranking_key(r)))
            axis = next(a for a in axes if winner["metrics"][a] != best["metrics"][a])
            alternatives.append({**best, "role": role, "alternative_axis": axis})
            used.add(construction(best))
    return winner, alternatives
