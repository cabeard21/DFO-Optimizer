"""Evaluate a single imported class independently of the native candidate search.

The creator checks the normalized draft. Profile certification also requires that
the importer kept every selected trait. Class construction covers neither
post-creation training nor damage delivery.
"""

from dataclasses import dataclass

from .class_document import ClassDraft, export_document, parse_document
from .ruleset import freeze_ruleset, load_ruleset


# src/systems/chargen.js, spellPointMultiplier. The career bitfield already
# encodes the last applicable writes from both trait windows.
MAGERY = {0: 3.0, 4: 2.0, 8: 1.75, 12: 1.5, 16: 1.0, 20: 0.5}


@dataclass(frozen=True)
class ClassPolicy:
    target: int
    hp: int | None
    magery: float | None
    allow_high_risk: bool
    require_day_and_night_casting: bool
    allow_unverified_advantageous_behavior: bool
    require_magic_school: bool

    def validate(self, limits):
        if type(self.target) is not int or not limits["difficulty_min"] <= self.target <= limits["difficulty_max"]:
            raise ValueError("difficulty_target must be a legal integer difficulty")
        if self.hp is not None and (type(self.hp) is not int or not limits["hp_min"] <= self.hp <= limits["hp_max"]):
            raise ValueError("hp_lock must be a legal HP setting or null")
        if self.magery is not None and (type(self.magery) not in (int, float)
                                        or self.magery not in MAGERY.values()):
            raise ValueError("magery_lock must be a catalog multiplier or null")
        if any(type(v) is not bool for v in (self.allow_high_risk, self.require_day_and_night_casting,
                                             self.allow_unverified_advantageous_behavior, self.require_magic_school)):
            raise ValueError("profile switches must be booleans")


def disallowed_trait(primary: str, secondary: str, *, allow_high_risk: bool = False,
                     require_day_and_night_casting: bool = True,
                     allow_unverified_advantageous_behavior: bool = False) -> str | None:
    """Return the profile exclusion code for a source trait, independently of its cost."""
    if require_day_and_night_casting and primary in ("darknessPoweredMagery", "lightPoweredMagery"):
        return "restricted_casting"
    if not allow_high_risk and (primary in ("damage", "criticalWeakness")
                                or (primary == "lowTolerance" and secondary == "toParalysis")):
        return "high_risk_disadvantage"
    if not allow_unverified_advantageous_behavior and primary == "inabilityToRegen":
        return "uncertain_regeneration_behavior"
    return None


def _career_flags(rows, defaults):
    # Compose the pinned parseCareerData writes in the actual window order.
    flags = dict(defaults)
    for row in rows:
        for name, write in row["writes"].items():
            flags[name] = (flags[name] & ~write["clear"]) | write["set"]
    return flags


def _create_errors(draft, stat_ledger, difficulty, limits):
    gates = ((not draft.name, "missing_name"),
             (None in draft.skills, "missing_skills"),
             (stat_ledger != 0, "unbalanced_attributes"),
             (not limits["difficulty_min"] <= difficulty <= limits["difficulty_max"], "difficulty_out_of_range"))
    return [code for failed, code in gates if failed]


def _resolve_race(race, catalog):
    if type(race) is int:
        return next((r for r in catalog if r["id"] == race), None)
    if isinstance(race, str):
        key = race.strip().lower()
        return next((r for r in catalog if key in (r["name"].lower(), r["key"].lower())), None)
    return None


def _profile_errors(draft, rows, policy, facts):
    checks = ((bool(facts["skipped"]), "skipped_traits"),
              (facts["race_invalid"], "unknown_race"),
              (policy.require_magic_school and facts["starting_spell_set_index"] is None, "missing_starting_spell_set"),
              (facts["difficulty_points"] != policy.target, "difficulty_lock"),
              (policy.hp is not None and draft.hp != policy.hp, "hp_lock"),
              (policy.magery is not None and policy.magery != facts["magicka_multiplier"], "magery_lock"))
    failures = [code for failed, code in checks if failed]
    for row in rows:
        exclusion = disallowed_trait(row["primary"], row["secondary"], allow_high_risk=policy.allow_high_risk,
                                     require_day_and_night_casting=policy.require_day_and_night_casting,
                                     allow_unverified_advantageous_behavior=policy.allow_unverified_advantageous_behavior)
        if exclusion:
            failures.append(f"{exclusion}.{row['primary']}.{row['secondary']}".rstrip("."))
    return failures


def _construction(draft: ClassDraft, rules):
    catalog = {t["id"]: t for t in rules["traits"]}
    rows = [catalog[i] for i in draft.advantages + draft.disadvantages]
    # These few scalar calculations deliberately do not call the search kernel.
    hp_cost = draft.hp - 8 if draft.hp >= 8 else 2 * (draft.hp - 8)
    points = hp_cost + sum(t["cost"] for t in rows)
    flags = _career_flags(rows, rules["career_defaults"])
    magic = {s["id"] for s in rules["skills"] if s["magic"]}
    return rows, {
        "hp_difficulty": hp_cost,
        "advantage_difficulty": sum(catalog[i]["cost"] for i in draft.advantages),
        "disadvantage_difficulty": sum(catalog[i]["cost"] for i in draft.disadvantages),
        "difficulty_points": points, "advancement_multiplier": 0.3 + (2.7 * (points + 12)) / 52,
        "effective_flags": flags, "magicka_multiplier": MAGERY.get((flags["abilityFlagsAndSpellPointsBitfield"] & 0x1c00) >> 8, 1.0),
        "stat_ledger": rules["limits"]["stat_total"] - sum(draft.attributes),
        "reputation_ledger": -sum(draft.reputations),
        "starting_spell_set_index": 1 if magic.intersection(draft.skills[:6]) else None,
    }


def _unsupported(rows):
    primaries = {row["primary"] for row in rows}
    missing = ["pve.spell_damage", "progression.training"]
    if "phobia" in primaries:
        missing.append("pve.phobia")
    if "inabilityToRegen" in primaries:
        missing.append("pve.sp_recovery")
    if any(primary.startswith("forbidden") for primary in primaries):
        missing.append("gear.eligibility")
    return missing


def validate_class_snapshot(document, *, ruleset, race=None, profile="dhargo_pve", hp_lock=30,
                   magery_lock=3.0, allow_high_risk=False, require_day_and_night_casting=True,
                   allow_unverified_advantageous_behavior=False, difficulty_target=-12,
                   require_magic_school=True) -> dict:
    """Evaluate against the private, already authenticated snapshot owned by a service."""
    if profile not in ("dhargo_pve", "custom"):
        raise ValueError("supported class profiles are dhargo_pve and custom")
    rules = ruleset
    policy = ClassPolicy(difficulty_target, hp_lock, magery_lock, allow_high_risk,
                         require_day_and_night_casting, allow_unverified_advantageous_behavior,
                         require_magic_school)
    policy.validate(rules["limits"])
    report = {"source_sha": rules["source_sha"], "ruleset_hash": rules["content_hash"], "profile": profile,
              "mode": rules["mode"], "unsupported_mechanics": [],
              "parsed": False, "create_legal": False, "profile_legal": False, "normalized": None,
              "errors": [], "create_errors": [], "profile_errors": [], "skipped": [], "warnings": [],
              "difficulty_points": None, "advancement_multiplier": None, "effective_flags": None,
              "early_damage_verified": None, "training_route_verified": None}
    try:
        draft, skipped = parse_document(document, rules)
    except ValueError as exc:
        return {**report, "errors": [str(exc)]}
    rows, facts = _construction(draft, rules)
    race_row = _resolve_race(race, rules["races"])
    gates = _create_errors(draft, facts["stat_ledger"], facts["difficulty_points"], rules["limits"])
    policy_failures = _profile_errors(draft, rows, policy, {**facts, "skipped": skipped,
                                      "race_invalid": race is not None and race_row is None})
    warnings = ["unbalanced_reputation_editor"] if facts["reputation_ledger"] else []
    if any(r["primary"] == "inabilityToRegen" for r in rows):
        warnings.append("regeneration_effect_unverified")
    return {**report, **facts, "parsed": True, "normalized": export_document(draft, rules),
            "race_id": race_row["id"] if race_row else None, "create_legal": not gates, "create_errors": gates,
            "profile_legal": not gates and not policy_failures, "profile_errors": policy_failures,
            "skipped": skipped, "warnings": warnings, "unsupported_mechanics": _unsupported(rows)}


def validate_class(document, *, ruleset=None, **options) -> dict:
    """Authenticate the ruleset, then return parser, post-import Create, and profile outcomes."""
    rules = load_ruleset() if ruleset is None else freeze_ruleset(ruleset)
    return validate_class_snapshot(document, ruleset=rules, **options)


def import_class(document, **options) -> dict:
    """Read a game-exported document, preserving all import diagnostics."""
    return validate_class(document, **options)


def export_class(document, *, ruleset=None) -> dict:
    """Write a normalized v1 class which survives both import and the Create gates."""
    report = validate_class(document, ruleset=ruleset)
    if not report["create_legal"] or report["skipped"]:
        errors = report["errors"] + report["create_errors"] + (["skipped_traits"] if report["skipped"] else [])
        raise ValueError("cannot export class: " + ", ".join(errors))
    return report["normalized"]
