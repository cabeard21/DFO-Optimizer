"""Freeze the pinned online PCAAO/RRI ordinary melee lane for one retained loadout."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
from types import MappingProxyType

from .ruleset import DATA
from .spell_request import _int, _object


def _freeze_table(value):
    if isinstance(value,dict):
        return MappingProxyType({k: _freeze_table(v) for k,v in value.items()})
    if isinstance(value,list):
        return tuple(_freeze_table(v) for v in value)
    return value


@lru_cache(maxsize=1)
def laws():
    data = (DATA / "physical-laws.json").read_bytes().rstrip(b"\r\n")
    if hashlib.sha256(data).hexdigest() != LAW_HASH:
        raise ValueError("Physical combat law hash mismatch")
    return _freeze_table(json.loads(data))


LAW_HASH = "0e023189be5ccefcdece23a847bbe16b772f110ab456e9e8bae701c9646610d2"
CORE = "ordinary_online_pcaao_v1"


class PhysicalGap(ValueError):
    """The loadout or effects require additional verified combat mechanics."""


def ordinary_foe(*, level=1, skill=35, weapon=None):
    """One authored awake, stationary human class opponent with supplied skill and a main hand."""
    if weapon is None:
        weapon = {"templateIndex":113, "group":"Weapons", "material":0,
                  "currentCondition":50, "maxCondition":50}
    return {"level":level, "skills":[skill]*35, "attributes":[50]*8, "race_id":1,
            "career_index":1, "min_metal":-1, "career":{}, "armor":[],
            "weapon":None if weapon is False else deepcopy(weapon),
            "evidence":"Hypothetical ordinary class enemy, stated equipment and skills, no secondary attack."}


def ordinary_combat(foes, *, fallback=True, frame_us=16667, evidence):
    return {"core":CORE,"enemies":deepcopy(foes),"fallback":fallback,"frame_us":frame_us,"evidence":evidence}


def _evidence(value):
    if not isinstance(value,str) or not value.strip() or len(value)>2048:
        raise ValueError("Physical combat requires attributed ordinary-state evidence")


def _vector(values, size, maximum, label):
    if not isinstance(values,list) or len(values)!=size:
        raise ValueError(f"{label} requires {size} entries")
    return [_int(v,label,0,maximum) for v in values]


def _mundane(item, kinds):
    if not isinstance(item,dict) or type(item.get("templateIndex")) is not int:
        raise ValueError("Physical item requires its numeric template index")
    if item["templateIndex"] not in kinds:
        raise PhysicalGap("Unsupported ordinary physical item template")
    if any(item.get(k) for k in ("magic","legendary","affixes","enchantments","artifact","sockets","sigil","setId")):
        raise PhysicalGap("Equipped physical item requires reviewed mundane effects")
    if item.get("quality") not in (None,1) or item.get("repairData") is not None:
        raise PhysicalGap("Modeled physical equipment must have ordinary quality and be available to wield")
    if item.get("poisonType",-1)!=-1:
        raise PhysicalGap("Poison on the equipped weapon requires a physical rider")
    if type(item.get("flags",0)) is not int or item.get("flags",0)&0x10:
        raise PhysicalGap("Nonstandard equipped physical damage flags require verification")
    if "currentCondition" not in item or "maxCondition" not in item:
        raise PhysicalGap("The worn copy needs its current and maximum condition")
    maximum=_int(item.get("maxCondition"),"observed maximum item condition",1,1_000_000)
    condition=_int(item.get("currentCondition"),"observed equipped item condition",1,maximum)
    return condition,maximum


def _swing(attributes, skills, index, race, expert, frame_us):
    info=laws()["weapons"][str(index)]
    strength,_,_,_,_,_,speed,_=attributes
    level=skills[info["skill"]]
    if level>100:
        raise PhysicalGap("Mastered physical attack skills require their verified weapon riders")
    state=laws()["modifiers"][str(info["skill"])]
    bonuses=[state[str(race)]]
    if expert & info["mask"]:
        bonuses.append(state["expert"])
    def bonus(field):
        return sum(row[field][0] + sum(v//d for v,d in zip(attributes,row[field][1:],strict=True) if d>0)
                   for row in bonuses)
    if index<0:
        effective=speed
        span=(level//10+1,level//5+1)
    else:
        base=min(98,speed)
        effective=int(base-base*(info["weight"]*(150-strength)/100*3.4)/90)
        span=info["span"]
    tempo=1+((50-min(100,max(0,effective)))/100)*(.8)
    tick=max(.09,min(.4,(195/980)*tempo*info["handling"]))
    step=max(1,math.ceil(tick/(frame_us/1e6)-1e-9))*frame_us
    return [level,*span,bonus("damageMod"),bonus("toHitMod"),int(info["both"]),int(info["skill"]==32),
            step*(3 if index<0 else 2),step*(8 if index<0 else 5)]


def _fighter(raw, player, frame_us):
    allowed={"attributes","skills","race_id","level","career","armor","weapon","evidence"}
    _object(raw,"ordinary physical combatant",allowed|{"fatigue"} if player else allowed|{"career_index","min_metal"})
    _evidence(raw.get("evidence"))
    attrs=_vector(raw.get("attributes"),8,100,"live physical attributes")
    skills=_vector(raw.get("skills"),35,255,"live physical skills")
    race=_int(raw.get("race_id"),"physical race",1,8)
    level=_int(raw.get("level"),"physical level",1,255)
    career=raw.get("career")
    if not isinstance(career,dict):
        raise ValueError("Missing physical career")
    flags=_int(career.get("abilityFlagsAndSpellPointsBitfield",0),"career abilities",0,2**32-1)
    expert=_int(career.get("weaponArmorShieldsBitfield",0),"career expertise",0,2**32-1)>>16
    group=2 if player else laws()["class_groups"][_int(raw.get("career_index"),"class enemy career index",0,18)]
    min_metal=-1 if player else _int(raw.get("min_metal"),"target minimum weapon metal",-1,9)
    # The ordinary class opponent lane identifies the actual career index.
    index=raw.get("career_index",-1)
    kind=-1
    metal=-1
    condition=maximum=repool=0
    weapon=raw.get("weapon")
    if weapon is not None:
        condition,maximum=_mundane(weapon,range(113,129))
        kind=weapon["templateIndex"]
        metal=_int(weapon.get("material"),"weapon metal",0,9)
        repool=laws()["weapons"][str(kind)]["repool"][metal].get(str(maximum),0)
    armor=raw.get("armor")
    if not isinstance(armor,list) or len(armor)>8:
        raise ValueError("Use at most seven physical body pieces and one shield")
    slots=[[0]*12 for _ in range(8)]
    rows=laws()["rows"]
    for it in armor:
        supported=[*range(102,113),147,148,149,186,187,188]
        cond,mx=_mundane(it,supported)
        template=it["templateIndex"]
        shield=109<=template<=112
        parts=laws()["armor_parts"].get(str(template),[6])
        pos=7 if shield else parts[0]
        if slots[pos][0]:
            raise ValueError("Overlapping physical body slots")
        if shield and kind>=0 and laws()["weapons"][str(kind)]["both"]:
            raise ValueError("Two-handed weapon overlaps a shield")
        material=it.get("material",0 if template>=147 else None)
        if type(material) is not int or str(material) not in laws()["materials"]:
            raise ValueError("Missing or unsupported equipped armor material")
        tier=str(laws()["materials"][str(material)][int(shield)])
        stem="SHIELD_" if shield else ""
        names=[stem+"UNARMED_ROWS",stem+"BLUNT_ROWS",stem+"EDGED_ROWS","AVERAGE_"+("SHIELD" if shield else "ARMOR")+"_ROWS"]
        factors=[round(100*v) for name in names for v in rows[name].get(tier,[1,1])]
        slots[pos]=[cond,mx,template,sum(1<<i for i in parts),*factors]
    if not player:
        expert=0
    return {"stats":attrs,"level":level,"group":group,"index":index,"min_metal":min_metal,
            "attack_flags":_int(career.get("attackModifierFlags",0),"physical group traits",0,255),
            "adrenaline":int(bool(flags&4)), "dodge":skills[20],"crit":skills[34],
            "weapon":[kind,metal,condition,maximum],"repool":repool,"armor":slots,
            "armed":_swing(attrs,skills,kind,race,expert,frame_us),"bare":_swing(attrs,skills,-1,race,expert,frame_us)}


def freeze_physical(actor_spec, physical_spec, n):
    _object(physical_spec,"physical scenario",{"core","evidence","enemies","fallback","frame_us"})
    _evidence(physical_spec.get("evidence"))
    if physical_spec.get("core")!=CORE or type(physical_spec.get("fallback")) is not bool:
        raise ValueError("Physical encounter requires the ordinary online PCAAO core and explicit fallback")
    foes=physical_spec.get("enemies")
    if not isinstance(foes,list) or len(foes)!=n:
        raise ValueError("Physical enemies must match the ordered target panel")
    frame=_int(physical_spec.get("frame_us"),"authored render frame interval",1000,250000)
    if not isinstance(actor_spec,dict):
        raise ValueError("Physical scenario requires an observed player combatant")
    fatigue=_int(actor_spec.get("fatigue"),"current physical fatigue",0,2**30)
    return {"fallback":physical_spec["fallback"], "enemy_reach_mm":laws()["enemy_reach_mm"],
            "fatigue":fatigue,
            "actors":[_fighter(actor_spec,True,frame),*[_fighter(foe,False,frame) for foe in foes]]}
