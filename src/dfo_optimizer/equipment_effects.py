"""Decode caster-facing lines, with explicit unsupported item effects."""
from collections import Counter

MODIFIER_KEYS = ("speed", "intelligence", "destruction", "enhanced_destruction",
                 "cost_pct", "power_pct", "pierce", "cast_speed_pct")

# These enchantments trigger on a weapon strike, a separate item-use action,
# defense, or other channels outside the stationary outgoing direct-spell scenario.
_INACTIVE = {"None", "CastWhenUsed", "CastWhenStrikes", "PotentVs", "RegensHealth", "VampiricEffect",
             "IncreasedWeightAllowance", "RepairsObjects", "AbsorbsSpells", "FeatherWeight",
             "StrengthensArmor", "GoodRepWith", "SoulBound", "ExtraWeight", "WeakensArmor",
             "BadRepWith", "LowDamageVs"}
_WEAPON_POWERS = {"bane", "unaware", "sanctified", "chain", "flow", "venom", "quake", "moon"}
_REGULAR_MAGIC = {"CastWhenUsed", "CastWhenHeld", "CastWhenStrikes", "VampiricEffect",
                  "AbsorbsSpells", "EnhancesSkill"}


def _enchantments(item, data, mods, issues):
    rows = item.get("enchantments", [])
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("enchantments must be a list of effect records")
    names = {v: k for k, v in data["enchantment_types"].items()}
    if any("enchantCost" in r for r in rows):
        issues.add("maker_enchantments")
    if len(rows) > 11:
        issues.add("unverified_enchantments")
        return
    live = []
    for row in rows:
        kind, param = row.get("type"), row.get("param")
        if type(kind) is not int or type(param) is not int:
            raise ValueError("Enchantment type and param must be integers")
        name = names.get(kind)
        if not -128 <= param <= 127:
            issues.add("unknown_enchantment_parameter")
        if name != "None":
            live.append(name)
        if name == "EnhancesSkill":
            if not 0 <= param <= 34:
                issues.add("unknown_enchantment_parameter")
            if param == data["destruction_id"]:
                mods["enhanced_destruction"] += data["enhance_skill_value"]
        elif name == "ImprovesTalents" and param in (0, 1):
            continue
        elif name not in _INACTIVE:
            issues.add(f"enchantment:{name or kind}")
    if item.get("magic") and rows and (len(live) != 1 or live[0] not in _REGULAR_MAGIC):
        issues.add("unverified_enchantments")
    if rows and not item.get("magic") and not item.get("rarity") and not (len(rows) == 10 and len(live) < 10):
        issues.add("unverified_enchantments")


def _socket_lines(item, template, lines, data, issues):
    gems = [a for a in lines if a.get("gem") is not None]
    sockets = item.get("sockets", [] if item.get("socket") is None else [item["socket"]])
    if not isinstance(sockets, list) or any(not isinstance(g, str) for g in sockets):
        raise ValueError("Item sockets must be gem IDs")
    tier = item.get("rarity")
    limit = template["socket_max"] if tier in ("rare", "legendary") else int(tier == "magic" and template["group"] == "Weapons")
    if (item.get("socket") is not None and item.get("sockets") is not None) or len(sockets) > limit:
        issues.add("socket_layout")
    if sockets and (item.get("provenance") is not None or item.get("bound") is True):
        issues.add("socket_layout")
    mapping = data["gem_lines"]["Weapons" if template["group"] == "Weapons" else "other"]
    expected = [mapping.get(g) for g in sockets if g != "empty"]
    if expected != gems or (gems and lines[-len(gems):] != gems):
        issues.add("socket_affixes")
    return gems


def _line_value(line, template, data, tier, issues):
    key, value, param = line.get("id"), line.get("value"), line.get("param")
    if not isinstance(key, str) or type(value) is not int or type(param) not in (int, str, type(None)):
        raise ValueError("Invalid affix ID, value or parameter")
    row = data["affixes"].get(key)
    if not row:
        issues.add(f"affix:{key}")
        return None
    gem = line.get("gem") is not None
    params = row["garment_params"] if template["group"].endswith("Clothing") else row["params"]
    if not gem and template["group"] not in row["groups"]:
        issues.add("affix_group")
    if (param not in params if params is not None else "param" in line):
        issues.add("affix_parameter")
    low, high = (1, row["range"]["legendary"][1]) if gem else row["range"].get(tier, [1, 0])
    if not low <= value <= high:
        issues.add("affix_value")
    if row["technique"]:
        issues.add("weapon_technique")
    return row


def _roll_law(item, template, lines, data, issues):
    tier = item.get("rarity")
    if tier is None:
        if lines or item.get("legendary"):
            issues.add("unclassified_roll")
        return
    if tier not in ("magic", "rare", "legendary"):
        issues.add("unsupported_rarity")
        return
    if item.get("artifact") or item.get("magic") or item.get("questItem"):
        issues.add("invalid_rarity")
    identities = [(a["id"], a.get("param")) for a in lines]
    if len(set(identities)) != len(lines):
        issues.add("duplicate_affix")
    if tier == "legendary":
        record = data["legendary"].get(item.get("legendary"))
        if (not record or item["templateIndex"] not in record["templates"]
            or lines != record["affixes"] or item.get("enchantments", []) != ([record["enchantment"]] if record["enchantment"] else [])):
            issues.add("unverified_legendary_record")
        return
    if item.get("legendary"):
        issues.add("invalid_legendary_record")
    counts = Counter("proc" if data["affixes"].get(a["id"], {}).get("proc") else "number" for a in lines)
    low, high = data["affix_counts"][tier]
    if not low <= counts["number"] <= high or counts["proc"] > 1:
        issues.add("affix_count")
    flavours = item.get("enchantments") or []
    if tier == "rare":
        valid = data["rare_flavours"].get(template["group"], [])
        if len(flavours) != 1 or flavours[0] not in valid:
            issues.add("unverified_rare_flavour")
    elif flavours:
        issues.add("unverified_magic_enchantment")


def _line_mods(item, template, data, mods, issues):
    lines = item.get("affixes", [])
    if not isinstance(lines, list) or any(not isinstance(a, dict) for a in lines):
        raise ValueError("affixes must be a list of records")
    _socket_lines(item, template, lines, data, issues)
    used_gems = Counter()
    for a in lines:
        row = _line_value(a, template, data, item.get("rarity"), issues)
        if row is None:
            continue
        key, param, value = a["id"], a.get("param"), a["value"]
        if a.get("gem") is not None:
            value = min(value, max(0, row["range"]["rare"][1] - used_gems[(key, param)]))
            used_gems[(key, param)] += value
        if key == "skill" and param == data["destruction_id"]:
            mods["destruction"] += value
        elif key == "stat" and param in ("speed", "intelligence"):
            mods[param] += value
        elif key in ("castSpeed", "potency", "focus"):
            mods[{"castSpeed": "cast_speed_pct", "potency": "power_pct", "focus": "cost_pct"}[key]] += value
    _roll_law(item, template, [a for a in lines if a.get("gem") is None], data, issues)


def item_modifiers(item, template, data):
    mods = dict.fromkeys(MODIFIER_KEYS, 0)
    issues = {field for field in ("customEnchantments", "sigil", "cursed", "imprint", "aetheric",
                                  "gilded", "artifact", "exalted") if item.get(field)}
    if item.get("magic") and not item.get("enchantments") and not item.get("customEnchantments"):
        issues.add("unknown_magic_effects")
    for field in ("legendary", "rarity"):
        if item.get(field) is not None and not isinstance(item[field], str):
            raise ValueError(f"{field} must be a string")
    _enchantments(item, data, mods, issues)
    _line_mods(item, template, data, mods, issues)
    if item.get("rarity") == "legendary" and (record := data["legendary"].get(item.get("legendary"))):
        kind = record["power_kind"]
        if kind == "pierce":
            mods["pierce"] += record["pierce"]
        elif kind and kind not in _WEAPON_POWERS:
            issues.add(f"power:{kind}")
    return sorted(issues), mods
