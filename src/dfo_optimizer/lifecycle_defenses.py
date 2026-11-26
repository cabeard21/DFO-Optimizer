"""Prospective, ordinary player defenses for Damage Health and Disintegrate.

The pinned spellcast.js savingChance applies the player's race before career
tolerances, tests immunity, then adds live Willpower. These effects check one
element flag. Temporary wards, biography and noncaster equipment need evidence.
"""
from .spell_reference import _save

ELEMENT_FLAGS = (8, 16, 4, 32, 2)


def player_save_channels(race_flags, career, willpower):
    resist_mods = []
    for flag in ELEMENT_FLAGS:
        initial = 50
        if race_flags["resistanceFlags"] & flag:
            initial += 30
        if race_flags["immunityFlags"] & flag:
            initial = 100
        if race_flags["lowToleranceFlags"] & flag:
            initial -= 25
        if race_flags["criticalWeaknessFlags"] & flag:
            initial -= 50
        resist_mods.append(initial - 50)
    return {
        "willpower": min(100, willpower), "resist_mods": resist_mods,
        "elemental_resists": [0]*5, "pierce": 0,
        "resistant": career["resistanceFlags"], "immune": career["immunityFlags"],
        "low_tolerance": career["lowToleranceFlags"], "critical_weakness": career["criticalWeaknessFlags"],
    }


def player_save_chances(race_flags, career, willpower):
    channels = player_save_channels(race_flags, career, willpower)
    return [_save(channels, element)[0] for element in range(5)]


def career_absorption(career, environment):
    flag = career["spellAbsorptionFlags"]
    return flag == 4 or flag == 2 and environment == "darkness" or flag == 1 and environment == "daylight"
