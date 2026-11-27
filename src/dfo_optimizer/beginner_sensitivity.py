"""Describe assumption changes on the same fighters and isolate single permanent decisions."""
from collections import defaultdict

from .character import _hash


def _trait(row):
    return (row["primary"], row.get("secondary"))


def _single_change(a, b):
    left, right = a["class"], b["class"]
    equal = all(left.get(k) == right.get(k) for k in ("hitPointsPerLevel", "attributes", "skills", "reputations", "advantages"))
    if not equal:
        return None
    before = list(map(_trait, left["disadvantages"]))
    after = list(map(_trait, right["disadvantages"]))
    if a["race_id"] != b["race_id"]:
        return f"{a['race']} or {b['race']}" if before == after else None
    removed, added = set(before) - set(after), set(after) - set(before)
    if (len(removed) == len(added) == 1 and next(iter(removed))[0] == next(iter(added))[0] == "forbiddenMaterial"
            and [x for x in before if x not in removed] == [x for x in after if x not in added]):
        return f"Forbid {next(iter(removed))[1]} or {next(iter(added))[1]}"
    return None


def matched_decisions(rows):
    by_core = defaultdict(list)
    for row in rows:
        if row["status"] == "replayed":
            d = row["class"]
            by_core[_hash([d.get(k) for k in ("hitPointsPerLevel", "attributes", "skills", "reputations", "advantages")])].append(row)
    results = []
    for group in by_core.values():
        for i, left in enumerate(group):
            for right in group[i+1:]:
                label = _single_change(left, right)
                if label:
                    offsets = {}
                    for variant, first in left["variant_metrics"].items():
                        other = right["variant_metrics"][variant]
                        offsets[variant] = {key: first[key]["mean_clear_rate"] - other[key]["mean_clear_rate"]
                                            for key in ("base", "changed")}
                    results.append({"decision": label, "left": left["id"], "right": right["id"],
                                    "mean_clear_rate_difference": left["metrics"]["mean_clear_rate"] - right["metrics"]["mean_clear_rate"],
                                    "paired_differences": offsets})
    return results


def interpretation(winner, changes, matched, rows):
    if not winner:
        reasons = sorted({r["reason"] for r in rows if r.get("reason")})
        return ("The run has no fully checked class on the required panel.", reasons[:3])
    names = {r["id"]: r["race"] + " " + r["class"]["name"] for r in rows}
    affected = [c for c in changes if c["winner_changed"]]
    labels = {"owned_only": "using only owned gear", "no_spell_purchase": "skipping the optional combat spell",
              "higher_pressure": "more frequent enemy attacks", "protected_recovery": "a protected recovery opportunity"}
    notes = [f"With {labels.get(c['variant'], c['variant'])}, first place on the affected fights shifted from "
             f"{names[c['baseline_family']]} to {names[c['variant_family']]}." for c in affected]
    if changes and not affected:
        notes.append(f"The same class stayed ahead on each affected set of fights across {len(changes)} changes in access or combat conditions.")
    for pair in matched:
        differences = pair["paired_differences"]
        if differences:
            axis, delta = max(differences.items(), key=lambda kv: abs(kv[1]["changed"] - kv[1]["base"]))
            if delta["changed"] != delta["base"]:
                notes.append(f"{pair['decision']}, with the other class settings held fixed. The first option's clear-rate "
                             f"difference was {delta['base']:+.1%} originally and {delta['changed']:+.1%} with "
                             f"{labels.get(axis,axis)} on those same fights.")
    notes.append("The panel models scheduled attacks and conditional purchases. Enemy frequency, item availability and the value of paralysis immunity in other fights can change the choice.")
    name = winner["race"]
    return f"Choose {name} and import the class below. Enter the listed skills in order, then use the creation checklist for bonuses the class file cannot set.", notes
