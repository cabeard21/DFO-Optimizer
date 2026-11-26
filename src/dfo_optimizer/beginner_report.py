"""Compact, reproducible publication of beginner comparisons on a shared panel."""
import json
from statistics import fmean
from sys import getsizeof
from zlib import compress, decompress

from .beginner_ranking import cell_key, evaluate_metrics, pick_builds, ranking_key
from .character import _hash

ASSUMPTIONS = [
    "Birth and combat draws are shared examples. Their frequencies describe this panel.",
    "Ordinary solo enemies use declared stationary positions, melee attempts and hostile spell schedules.",
    "Training targets, lodging, funding and later equipment opportunities are hypothetical. The creation fight uses owned items.",
]
LIMITATIONS = [
    "The recommendation covers the pinned game snapshot and supported ordinary PvE. Different drops, opponents or combat settings can change the choice.",
    "Class generation and the set of progression and casting policies are bounded.",
]
METRICS = {
    "selection": "Across the paired panel, maximize weakest scenario survival with a clear, weakest survival, then mean survival with a clear. Next prefer more compatible plate and backup metals, faster advancement, less cap practice and lower censored clear time. Break ties by class identity.",
    "cap_damage_per_second": "Total applied damage at level 45 divided by total encounter time, charging the full horizon to unfinished fights.",
    "mean_damage_per_sp": "Applied spell damage divided by paid spell points in sustained encounters. Undefined if no points were spent.",
    "min_hp_fraction": "Lowest recorded HP divided by that character's HP capacity across the panel.",
    "durability": "Prefer the highest weakest-scenario survival, then mean survival, then mean lowest health fraction. Deaths contribute zero remaining health.",
}


def compact_stage(cp):
    s = cp["state"]
    pack = {r["instance_id"]: r["item"] for r in cp["inventory"]}
    details = [{"slot": slot, "instance_id": identity, "name": pack[identity]["name"],
                "material": pack[identity].get("material")} for slot, identity in cp["loadout"].items()]
    return {**{k: cp[k] for k in ("stage", "level", "effort", "loadout", "acquisitions", "transactions", "spells") if k in cp},
            "loadout_details": details, "unsupported_spells": cp.get("unsupported_spells", []),
            "state": {k: s[k] for k in ("hp", "max_hp", "sp", "max_sp", "fatigue", "max_fatigue", "attributes", "skills", "mastered",
                                       "known", "arcane_path", "gold", "gender", "reflexes") if k in s}}


def _matched_variants(row):
    outcomes = row["outcomes"]
    params = {k: row["metrics"][k] for k in ("plate_weapon_materials", "advancement_multiplier", "mean_practice")}
    changes = {}
    for variant in sorted({t["variant"] for t in outcomes} - {"baseline"}):
        alternate = [t for t in outcomes if t["variant"] == variant]
        affected = {(t["scenario"], t["stage"], t["roll_seed"], t["seed"]) for t in alternate}
        baseline = [t for t in outcomes if t["variant"] == "baseline"
                    and (t["scenario"], t["stage"], t["roll_seed"], t["seed"]) in affected]
        if len(baseline) == len(alternate):
            changes[variant] = {k: evaluate_metrics(v, **params) for k, v in (("base", baseline), ("changed", alternate))}
    return changes


def retained_size(value, seen):
    if id(value) in seen:
        return 0
    seen.add(id(value))
    children = (*value.keys(), *value.values()) if isinstance(value, dict) else value if isinstance(value, (tuple, list)) else ()
    return getsizeof(value) + sum(retained_size(v, seen) for v in children)


class PanelArchive:
    """Keep summarized families in memory and inflate individual fights only for the chosen builds."""
    def __init__(self):
        self.rows = []
        self.trials = {}
        self.bytes = 0

    def append(self, row, limit):
        cells = row.get("outcomes", [])
        summary = {k: v for k, v in row.items() if k != "outcomes"}
        if row["status"] == "replayed":
            summary.update(panel_hash=_hash(sorted(map(cell_key, cells))), variant_metrics=_matched_variants(row))
        payload = compress(json.dumps(cells, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode(), 1)
        size = retained_size(summary, set()) + getsizeof(payload)
        if self.bytes + size > limit:
            return False
        self.bytes += size
        self.rows.append(summary)
        self.trials[row["id"]] = payload
        return True

    def expand(self, row):
        return {**row, "outcomes": json.loads(decompress(self.trials[row["id"]]))}


def sensitivity(rows):
    changes = []
    for variant in sorted(set.intersection(*(set(row["variant_metrics"]) for row in rows))):
        def winner(key):
            return min(({"id": r["id"], "metrics": r["variant_metrics"][variant][key]} for r in rows), key=ranking_key)
        before, after = winner("base"), winner("changed")
        changes.append({"variant": variant, "same_families": len(rows), "baseline_family": before["id"],
                        "variant_family": after["id"], "winner_changed": before["id"] != after["id"],
                        "baseline_metrics": before["metrics"], "variant_metrics": after["metrics"]})
    return changes


def _advancement_note(winner, rows):
    fast = [r for r in rows if r["metrics"]["advancement_multiplier"] == .3]
    if winner["metrics"]["advancement_multiplier"] == .3:
        return "This class has the fastest legal advancement setting, 0.30×."
    if not fast:
        return "The evaluated panel lacked a fully checked 0.30× comparison."
    best = min(fast, key=ranking_key)
    own, other = winner["metrics"], best["metrics"]
    for key, label, pct in (("worst_clear_rate", "weakest survival with a clear", True),
                            ("worst_survival_rate", "weakest survival", True),
                            ("mean_clear_rate", "average survival with a clear", True),
                            ("plate_weapon_materials", "compatible plate and backup metals", False)):
        if own[key] != other[key]:
            values = (f"{own[key]:.0%} versus {other[key]:.0%}" if pct else f"{own[key]} versus {other[key]}")
            return (f"The slower {own['advancement_multiplier']:.2f}× setting gains {label} ({values}) versus "
                    f"the leading 0.30× class. Their routes averaged {own['mean_practice']:,.0f} and "
                    f"{other['mean_practice']:,.0f} practice actions respectively.")
    raise RuntimeError("A slower class won without the required measured benefit")


def publish(archive):
    from .beginner_guide import build_guide

    eligible = [r for r in archive.rows if r["status"] == "replayed"]
    if not eligible:
        return None, [], []
    if len({r["panel_hash"] for r in eligible}) != 1:
        raise ValueError("Cannot rank different scenario panels together")
    winner, alternatives = pick_builds(eligible)
    m = winner["metrics"]
    backup = winner["permanent"]["backup_weapons"][0]
    recommended = {**archive.expand(winner), "role": "Recommended spellcaster",
                   "tradeoff": (f"You can cast from the start, switch to your {backup['name']} when magicka runs low, "
                                f"and wear plate. This build survived and cleared {m['mean_clear_rate']:.0%} of the "
                                f"tested fights on average. It keeps {m['plate_weapon_materials']} materials open for "
                                f"both plate and a backup weapon. " + _advancement_note(winner, eligible))}
    details = {"cap_damage_per_second": ("level-45 damage per second", ".2f"),
               "min_hp_fraction": ("minimum health remaining", ".0%"),
               "mean_min_hp_fraction": ("average minimum health remaining", ".0%"),
               "mean_survival_rate": ("average survival", ".0%"),
               "worst_survival_rate": ("weakest scenario survival", ".0%"),
               "mean_damage_per_sp": ("dungeon spell damage per spell point", ".2f")}
    explained = []
    for alt in alternatives:
        key = alt["alternative_axis"]
        label, fmt = details[key]
        n = alt["metrics"]
        note = (f"{label.capitalize()} is {n[key]:{fmt}} versus {m[key]:{fmt}} for the recommendation. "
                f"It clears and survives {n['mean_clear_rate']:.0%} of tested fights on average "
                f"versus {m['mean_clear_rate']:.0%}, with {n['plate_weapon_materials']} compatible plate and "
                f"backup metals versus {m['plate_weapon_materials']}.")
        row = {**archive.expand(alt), "tradeoff": note}
        explained.append({**row, "guide": build_guide(row)})
    return {**recommended, "guide": build_guide(recommended)}, explained, sensitivity(eligible)


def checked_metrics(permanent, projections, outcomes):
    return evaluate_metrics(outcomes, plate_weapon_materials=permanent["plate_weapon_materials"],
                            advancement_multiplier=permanent["advancement_multiplier"],
                            mean_practice=fmean(r["stages"][-1]["effort"]["practice"] for r in projections))


def result_identity(result):
    return _hash({k: v for k, v in result.items() if k not in {"result_hash", "diagnostics", "timings"}})
