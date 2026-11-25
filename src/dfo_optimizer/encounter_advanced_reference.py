"""Independent finalist replay for ordinary online PvE path and item listeners."""
from dataclasses import dataclass
from math import floor

from .spell_reference import _save, _round_js

PATH_IDS = {name: index for index, name in enumerate((
    "none", "battlemage", "trickster", "riftwalker", "warden", "wardwright", "shadowcaster",
    "spellbreaker", "bloodmage", "elementalist", "seer", "lightbringer", "enchanter", "necromancer",
    "soulbinder", "hierophant",
))}
MARTIAL_IDS = {name: index for index, name in enumerate((
    "none","blademaster","warblade","vanguard","ranger","bladedancer","bloodletter","cutthroat","assassin",
    "shadowdancer","juggernaut","woodsman","berserker","crusader","brawler","windrunner",
))}


@dataclass
class PathState:
    id: int = 0
    stacks: int = 0
    stacks_until_ms: float = 0
    hurt_ready_ms: float = 0
    heal_owed: float = 0
    mana_owed: float = 0
    last_cast: int = -1
    martial_id: int = 0
    martial_ready_ms: float = 0
    guard_owed: float = 0


def path_damage(state, now_ms, hp, max_hp, shield, undead_daedra, concealed):
    if state.id == PATH_IDS["bloodmage"] and max_hp:
        return max(0, min(25, 100*(max_hp-hp)//(2*max_hp)))
    if state.id == PATH_IDS["elementalist"] and now_ms < state.stacks_until_ms:
        return state.stacks * 3
    return {1: 15 if shield > 0 else 0, 6: 25 if concealed else 0,
            11: 20 if undead_daedra else 0}.get(state.id, 0)


def path_pierce(id, marked=False):
    return 10 if id == 7 else 20 if id == 10 and marked else 0


def path_speed(id):
    return 20 if id == 3 else 0


def path_cost(id, all_wards, sp):
    return sp * 80 / 100 if id == 5 and all_wards else sp


def path_evades(id, draws):
    return id == 10 and draws.next() < 0.125


def martial_speed(id):
    return 10 if id == 15 else 0


def martial_evades(state, draws):
    return state.martial_id == 5 and draws.next() < .1


def martial_guard(state, amount):
    if state.martial_id != 3 or amount <= 0:
        return amount
    held = amount / 10 + state.guard_owed
    cut = floor(held+1e-9)
    state.guard_owed = held-cut
    return amount-cut


def path_landed(state, now_ms, cast_id, took):
    if state.id == 9 and took > 0 and state.last_cast != cast_id:
        state.stacks = min(5, state.stacks + 1) if now_ms < state.stacks_until_ms else 1
        state.stacks_until_ms = now_ms + 10_000
        state.last_cast = cast_id


def _give(state, kind, amount, current, maximum):
    if amount <= 0 or (kind == "heal_owed" and current <= 0):
        return current
    exact = amount + getattr(state, kind)
    points = floor(exact + 1e-9)
    setattr(state, kind, exact-points)
    return min(maximum, current+points)


def path_hurt(state, now_ms, before, hp, max_hp):
    if not 0 < hp < max_hp*.3 <= before:
        return hp
    if state.id == 15 and state.hurt_ready_ms <= now_ms:
        state.hurt_ready_ms = now_ms + 180_000
        hp = _give(state, "heal_owed", max_hp*.25, hp, max_hp)
    if state.martial_id == 10 and state.martial_ready_ms <= now_ms:
        state.martial_ready_ms = now_ms + 180_000
        hp = _give(state, "heal_owed", max_hp*.2, hp, max_hp)
    return hp


def path_round(state, shield, hp, max_hp):
    if state.id == 4 and shield > 0 and hp < max_hp:
        hp = _give(state, "heal_owed", max_hp/100, hp, max_hp)
    if state.martial_id == 14 and hp < max_hp:
        hp = _give(state,"heal_owed", max_hp/100, hp, max_hp)
    return hp


def path_kill(state, eligible, trapped, hp, max_hp, sp, max_sp):
    if eligible and state.id == 13:
        hp = _give(state, "heal_owed", max_hp*.05, hp, max_hp)
        sp = _give(state, "mana_owed", max_sp*.05, sp, max_sp)
    if eligible and state.id == 14:
        sp = _give(state, "mana_owed", max_sp*(.2 if trapped else .1), sp, max_sp)
    if eligible and state.martial_id == 6:
        hp = _give(state,"heal_owed",max_hp*.05,hp,max_hp)
    return hp, sp


def path_signature(state, took, paid, hp, max_hp, sp, max_sp):
    if took > 0:
        if state.id == 13:
            hp = _give(state, "heal_owed", took*.5, hp, max_hp)
        elif state.id in (7, 14):
            amount = paid*(1/3) if state.id == 7 else took*.25
            sp = _give(state, "mana_owed", amount, sp, max_sp)
    return hp, sp


def gear_kill(state, wellspring_pct, eligible, sp, max_sp):
    if eligible:
        return _give(state, "mana_owed", max_sp*min(max(wellspring_pct,0),10)/100, sp, max_sp)
    return sp


@dataclass
class Defenses:
    absorb_chance: int = 0
    reflect_chance: int = 0
    resist_chance: int = 0
    career_absorbs: bool = False
    enchant_absorbs: bool = False
    set_absorb_chances: tuple = ()


def try_absorb(defense, effect, range_type, receiver_live, available_sp, paid_self, draws):
    if effect["type"] not in (4, 5):
        return 0
    if effect["type"] == 4:
        base = (effect["base_low"]+effect["base_high"])//2
        increment = (effect["plus_low"]+effect["plus_high"])//2
        component = 20*base + 28*(increment//effect["per_level"])
    else:
        component = 80*effect["chance_base"] + 140*(effect["chance_increment"]//effect["chance_per_level"])
    sp = (component*1000//(400*receiver_live) if receiver_live > 100
          else component*(110-receiver_live)//400)
    cost = max(5, sp*(2,2,3,4,5)[range_type]//2)
    drink = min(paid_self,cost) if paid_self>0 else cost
    if drink > available_sp:
        return 0
    for chance in (min(50,defense.absorb_chance), *defense.set_absorb_chances):
        if chance > 0 and floor(draws.next()*100) < chance:
            return drink
    if defense.career_absorbs or (defense.enchant_absorbs and floor(draws.next()*100)<50):
        return drink
    return 0


def reflects(defense, draws):
    return defense.reflect_chance > 0 and floor(100*draws.next()) < defense.reflect_chance


def resists(defense, draws):
    return defense.resist_chance > 0 and floor(100*draws.next()) < defense.resist_chance


def absorb_refund(total_absorbed, paid_self=0):
    return (min(total_absorbed,paid_self) if paid_self > 0 else total_absorbed)//2


def silence_rounds(effect, ctx, element, incumbent_rounds, draws):
    fresh = effect["duration_base"] + effect["duration_increment"] * max(1,ctx["level"]//effect["duration_per_level"])
    if fresh <= 0:
        return incumbent_rounds
    chance = effect["chance_base"] + effect["chance_increment"] * (ctx["level"]//effect["chance_per_level"])
    passed = floor(draws.next()*100) < _round_js(chance*(1 + max(0,ctx["climb"]-100)*.01))
    if incumbent_rounds >= 0:
        return max(incumbent_rounds,fresh-1)
    if not passed:
        return -1
    resistance = ctx["elemental_resists"][element]
    if resistance and floor(100*draws.next()) < resistance:
        return -1
    saving, immune = _save({**ctx,"pierce":0},element)
    if immune or 1+floor(100*draws.next()) <= saving-20:
        return -1
    return fresh-1


def aegis_bolt(took, max_hp, draws):
    if took <= 0:
        return 0
    draws.next()
    draws.next()
    return max(1,min(2*took,_round_js(max_hp*.2)))
