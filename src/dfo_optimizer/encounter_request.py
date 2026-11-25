"""Freeze one offline encounter. IDs and eligibility are resolved before native work."""
from copy import deepcopy
from bisect import bisect_left
from dataclasses import asdict
from functools import lru_cache
import re

from .spell_request import SpellCaster, _caster, _target, _int, _float, _object, MODS
from .encounter_advanced_reference import MARTIAL_IDS, PATH_IDS, martial_speed, path_cost
from .encounter_defenses import absorb_active, freeze_wards


def label(value, name, maximum=256):
    if type(value) is not str or not value.strip() or len(value)>maximum:
        raise ValueError(f"{name} requires a nonempty label up to {maximum} characters")
    return value


def array(value, name, minimum, maximum):
    if not isinstance(value,list) or not minimum<=len(value)<=maximum:
        raise ValueError(f"{name} requires {minimum} to {maximum} entries")
    return value


def unique(values, name):
    if len(set(values))!=len(values):
        raise ValueError(f"duplicate {name}")
    return values


# Source pricing uses the live skill of each effect's school, before the range multiplier.
SCHOOLS={"4,0":"destruction","5,255":"destruction","10,8":"restoration",
         "18,255":"restoration","35,255":"alteration","19,255":"mysticism"}
MAGNITUDE=("base_low","base_high","plus_low","plus_high","per_level")
CHANCE=("chance_base","chance_increment","chance_per_level")
DURATION=("duration_base","duration_increment","duration_per_level")


def _slot(effect, blockers):
    obj=_object(effect,"encounter effect",("effect_id",*MAGNITUDE,*CHANCE,*DURATION))
    pair=label(obj.get("effect_id"),"effect_id",12)
    if not re.fullmatch(r"(0|[1-9][0-9]{0,3}),(0|[1-9][0-9]{0,3})",pair):
        raise ValueError("effect_id requires two unsigned source IDs")
    t,sub=map(int,pair.split(","))
    canonical={"type":t,"subtype":sub}
    if pair not in SCHOOLS:
        blockers.append("unsupported spell effect "+pair)
        return canonical,0,pair
    if pair in ("5,255","19,255"):
        required=CHANCE+(DURATION if pair=="19,255" else ())
    else:
        required=MAGNITUDE+(DURATION if pair in ("18,255","35,255") else ())
    if set(obj)!={"effect_id",*required}:
        raise ValueError(f"{pair} requires exactly its source effect settings {required}")
    for k in required:
        canonical[k]=_int(obj[k],k,1 if k.endswith("per_level") else 0,100 if k in CHANCE[:2] else 255)
    if pair=="19,255":
        base=20*(canonical["chance_base"]+canonical["duration_base"])+100*(
                canonical["chance_increment"]//canonical["chance_per_level"]+
                canonical["duration_increment"]//canonical["duration_per_level"])
    elif pair=="5,255":
        base=80*canonical["chance_base"]+140*(canonical["chance_increment"]//canonical["chance_per_level"])
    else:
        lo,hi,pl,ph,per=(canonical[k] for k in MAGNITUDE)
        if lo>hi or pl>ph:
            raise ValueError("magnitude lower endpoint exceeds its upper endpoint")
        a,b={"4,0":(20,28),"10,8":(20,28),"18,255":(8,8),"35,255":(80,60)}[pair]
        base=a*((lo+hi)//2)+b*(((pl+ph)//2)//per)
        if pair in ("18,255","35,255"):
            a,b=(100,20) if pair=="18,255" else (28,8)
            base+=a*canonical["duration_base"]+b*(canonical["duration_increment"]//canonical["duration_per_level"])
    return canonical,base,pair


def _paths(raw,blockers,rules,speed):
    arcane=label(raw.get("path","none"),"path")
    martial=label(raw.get("martial_path","none"),"martial_path")
    mastered=unique([_int(i,"mastered",0,34) for i in array(raw.get("mastered",[]),"mastered",0,6)],"mastered skill")
    pairs={p["id"]:p for p in rules["progression_rules"]["paths"]}
    for family,name,roster in (("arcane",arcane,PATH_IDS),("martial",martial,MARTIAL_IDS)):
        if name=="none": continue
        source=pairs.get(name)
        if name not in roster or not source or source["family"]!=family or not set(source["skills"]).issubset(mastered):
            blockers.append(f"unresolved {family} path or missing earned mastery pair: {name}")
    if arcane=="trickster":
        blockers.append("unsupported Trickster panic and enemy AI")
    if martial not in ("none","brawler","vanguard","bladedancer","juggernaut","bloodletter","windrunner"):
        blockers.append("unsupported martial combat passive or technique: "+martial)
    if arcane!="none" or martial!="none" or "path_evidence" in raw:
        evidence=_object(raw.get("path_evidence",{}),"path_evidence",
                         ("source","observed_at_ms","context","initial_state","speed_basis"))
        if "source" in evidence: label(evidence["source"],"path evidence source",2048)
        if "observed_at_ms" in evidence: _int(evidence["observed_at_ms"],"path observation time",0,2**53-1)
        if not {"source","observed_at_ms"}<=evidence.keys() or evidence.get("context")!="ordinary_online_pve" or evidence.get("initial_state")!="fresh":
            blockers.append("paths require attributed, dated ordinary online PvE evidence with fresh cooldowns, stacks and fractional carries")
        if martial=="windrunner":
            basis=evidence.get("speed_basis")
            if basis not in ("before_martial_fold","observed_final"):
                blockers.append("Windrunner speed requires its observed input basis")
            elif basis=="before_martial_fold" and speed is not None:
                speed=min(100,speed+martial_speed(MARTIAL_IDS[martial]))
    return PATH_IDS.get(arcane,0),MARTIAL_IDS.get(martial,0),speed


def _actor(raw,blockers,rules):
    extras={"hp","max_hp","school_live","school_climb","school_trained","path","mastered","unsupported_effects",
            "defense","wellspring_items","wards","known_signature_indices","martial_path","path_evidence"}
    _object(raw,"actor",set(SpellCaster.__dataclass_fields__)|extras)
    caster=_caster({k:v for k,v in raw.items() if k not in extras})
    if caster.has_spellbook is not True:
        blockers.append("repeatable casting policies require an observed spellbook")
    for key in ("level","speed","current_sp","max_sp","destruction_live","climb",*MODS):
        if getattr(caster,key) is None:
            blockers.append("unknown actor."+key)
    hp=_int(raw.get("hp"),"actor.hp",1,2**30)
    maximum=_int(raw.get("max_hp"),"actor.max_hp",hp,2**30)
    live={"destruction":caster.destruction_live}
    climb={"destruction":caster.climb}
    for table,key,limit in ((live,"school_live",10000),(climb,"school_climb",140)):
        for school,val in _object(raw.get(key,{}),key,("restoration","alteration","illusion","mysticism","thaumaturgy")).items():
            table[school]=_int(val,school,0,limit)
    for issue in array(raw.get("unsupported_effects",[]),"unsupported_effects",0,128):
        blockers.append("unresolved actor effect "+label(issue,"unsupported effect"))
    ctx={k:getattr(caster,k) for k in ("level","speed",*MODS)}
    ctx.update(live_skill=caster.destruction_live,climb=caster.climb,available_sp=caster.current_sp,
               target_hp=hp,willpower=0)
    defense=raw.get("defense")
    if defense is not None:
        allowed=("willpower","resistant","immune","critical_weakness","low_tolerance","resist_mods","elemental_resists")
        _object(defense,"actor defense",allowed)
        target=asdict(_target({"id":"player","hp":hp,**defense}))
        ctx.update({k:target[k] for k in allowed})
    path,martial,ctx["speed"]=_paths(raw,blockers,rules,ctx["speed"])
    worn=[]
    total=0
    for item in array(raw.get("wellspring_items",[]),"wellspring_items",0,32):
        _object(item,"worn Wellspring jewelry",("instance_id","rarity","pct","evidence"))
        worn.append(label(item.get("instance_id"),"item instance"))
        label(item.get("evidence"),"equipped Wellspring evidence",2048)
        bound={"magic":(2,4),"rare":(4,7),"legendary":(7,10)}.get(item.get("rarity"))
        if not bound: raise ValueError("unsupported Wellspring item rarity")
        total+=_int(item.get("pct"),"Wellspring roll",*bound)
    unique(worn,"worn Wellspring instance")
    return dict(hp=hp,max_hp=maximum,max_sp=caster.max_sp,caster=ctx,path_id=path,martial_id=martial,
                wellspring_pct=min(10,total)),live,climb


def _spellbook(raw,actor,live,climb,trained,blockers,catalog,owned):
    ids,spells=[],[]
    for spell in array(raw,"spells",1,256):
        _object(spell,"spell",("id","effects","element","range_type","evidence","signature"))
        ids.append(label(spell.get("id"),"spell.id"))
        element=_int(spell.get("element"),"element",0,4)
        reach=_int(spell.get("range_type"),"range_type",0,4)
        if "evidence" in spell: label(spell["evidence"],"spell evidence",2048)
        signature=spell.get("signature")
        if signature is not None: _int(signature,"signature record ID",-2**31,-1)
        if signature is not None and (signature not in owned or not spell.get("evidence")):
            blockers.append("signature spell requires an owned index and attributed shelf evidence")
        matches={-46113:"necromancer",-46107:"spellbreaker",-46101:"battlemage"}
        awake=signature in matches and actor["path_id"]==PATH_IDS[matches[signature]]
        siphon=awake and signature==-46113
        if signature is not None and not awake:
            blockers.append("unverified signature rider for "+ids[-1])
        slots=[]
        schools=set()
        sp=0
        for raw_slot in array(spell.get("effects"),"effects",1,3):
            slot,base,pair=_slot(raw_slot,blockers)
            school=SCHOOLS.get(pair)
            if school and ((reach==0)!=(school in ("restoration","alteration"))):
                blockers.append("unsupported effect target "+pair)
            if siphon and school:
                if not {"restoration","mysticism"}<=trained.keys():
                    blockers.append("Siphon Life requires permanent Restoration and Mysticism")
                school="mysticism" if trained.get("mysticism",0)>trained.get("restoration",0) else "restoration"
            if school:
                schools.add(school)
                value=live.get(school)
                earned=climb.get(school)
                if value is None or earned is None:
                    blockers.append("unknown live or earned "+school)
                else:
                    sp+=base*1000//(400*value) if value>100 else base*(110-value)//400
                slot["climb"]=earned or 0
            slots.append(slot)
        if awake:
            from .encounter_signatures import canonical_signature
            if not canonical_signature(catalog,signature,element,reach,slots):
                blockers.append("spell does not match the source signature record")
        if any(slot["type"]==19 for slot in slots) and not (awake and signature==-46107):
            blockers.append("Silence outside the reviewed Unravel bundle")
        raw_cost=max(5,sp*(2,2,3,4,5)[reach]//2)
        focused=(raw_cost*(100-min(actor["caster"]["focus_pct"] or 0,30))+50)//100
        discounted=path_cost(actor["path_id"],bool(schools and schools<={"alteration","thaumaturgy"}),focused)
        paid=int(discounted+.5)
        spells.append({"element":element,"range_type":reach,"cost_sp":paid,"effects":slots,
                       "climb":slots[0].get("climb",0),"signature":awake})
    return unique(ids,"spell ID"),spells


def _enemies(raw,horizon,blockers):
    results=[]
    extras={"x_mm","z_mm","radius_mm","category","kill_eligible","trapped","distance_mm","wards",
            "sp","max_sp","absorb_skill","level","evidence"}
    for row in array(raw,"enemies",1,128):
        if not isinstance(row,dict): raise ValueError("enemy must be an object")
        target=asdict(_target({k:v for k,v in row.items() if k not in extras}))
        for dim in ("x_mm","z_mm"):
            target[dim]=_int(row.get(dim),dim,-1_000_000,1_000_000)
        target["radius_mm"]=_int(row.get("radius_mm",450),"radius_mm",0,10000)
        target["category"]=row.get("category","ordinary")
        if target["category"] not in ("ordinary","undead","daedra"):
            raise ValueError("unknown target category")
        target["undead_daedra"]=target.pop("category") in ("undead","daedra")
        if "distance_mm" in row: target["distance_mm"]=_int(row["distance_mm"],"travel distance",0,2_000_000)
        for k,d in (("kill_eligible",True),("trapped",False)):
            v=row.get(k,d)
            if type(v) is not bool: raise ValueError(f"enemy {k} must be boolean")
            target[k]=v
        target["wards"]=freeze_wards(row.get("wards"),horizon,blockers)
        if absorb_active(target["wards"]) and not {"sp","max_sp","absorb_skill","evidence"}<=row.keys():
            blockers.append("enemy absorption needs observed remaining pool, capacity, live Destruction and evidence")
        if "evidence" in row: label(row["evidence"],"enemy evidence",2048)
        target["sp"]=_int(row.get("sp",0),"enemy SP",0,2**30)
        target["max_sp"]=_int(row.get("max_sp",target["sp"]),"enemy max SP",target["sp"],2**30)
        target["absorb_skill"]=_int(row.get("absorb_skill",0),"enemy live Destruction",0,10000)
        target["level"]=_int(row.get("level",1),"enemy level",1,255)
        results.append(target)
    unique([r["id"] for r in results],"enemy ID")
    return results


def _rooms(raw,actor,enemies,horizon):
    if "rooms" not in raw: return []
    if raw.get("recovery"): raise ValueError("explicit rooms require recovery at room transitions")
    rooms,labels,assigned=[],[],[]
    for i,room in enumerate(array(raw["rooms"],"rooms",1,len(enemies))):
        _object(room,"room",("id","enemies","delay_us","rest_hp","rest_sp","evidence"))
        labels.append(label(room.get("id"),"room id"))
        members=[_int(j,"room enemy",0,len(enemies)-1) for j in array(room.get("enemies"),"room enemies",1,len(enemies))]
        delay=_int(room.get("delay_us",0),"room delay",0,horizon if i else 0)
        out={"enemies":members,"delay_us":delay}
        assigned.extend(members)
        if {"rest_hp","rest_sp"} & set(room):
            if not delay or not {"rest_hp","rest_sp"}<=set(room): raise ValueError("room rest requires two floors and positive duration")
            label(room.get("evidence"),"protected room rest evidence",2048)
            out["rest_hp"]=_int(room["rest_hp"],"room health floor",0,actor["max_hp"])
            out["rest_sp"]=_int(room["rest_sp"],"room magicka floor",0,2**30 if actor["max_sp"] is None else actor["max_sp"])
        rooms.append(out)
    unique(labels,"room ID")
    if sorted(assigned)!=list(range(len(enemies))): raise ValueError("every enemy must belong to exactly one room")
    return rooms


def _scenario(raw,actor,blockers,ids,spells):
    _object(raw,"scenario",("id","horizon_us","first_round_us","round_period_us","enemies","incoming",
                            "recovery","tape","evidence","unsupported_mechanics","rooms"))
    label(raw.get("id"),"scenario.id")
    label(raw.get("evidence"),"scenario.evidence",2048)
    horizon=_int(raw.get("horizon_us"),"horizon_us",1,3_600_000_000)
    enemies=_enemies(raw.get("enemies"),horizon,blockers)
    incoming=[]
    for row in array(raw.get("incoming",[]),"incoming",0,100_000):
        _object(row,"incoming",("time_us","source","damage","kind","spell","evidence"))
        if row.get("kind") not in ("blow","spell","bundle"): raise ValueError("unknown incoming kind")
        event=dict(time_us=_int(row.get("time_us"),"incoming time_us",0,horizon),
            source=_int(row.get("source"),"incoming source",0,len(enemies)-1),kind=row["kind"])
        if event["kind"]=="bundle":
            if "damage" in row or row.get("spell") not in ids: raise ValueError("incoming bundle requires a known spell ID")
            label(row.get("evidence"),"observed enemy spell landing",2048)
            event["spell"]=ids.index(row["spell"])
            bundle=spells[event["spell"]]
            if "level" not in raw["enemies"][event["source"]]:
                blockers.append("incoming bundle requires a verified caster level")
            if bundle["range_type"] not in (1,2) or any(e["type"] not in (4,5) for e in bundle["effects"]):
                blockers.append("unsupported hostile projectile bundle")
        else:
            if "spell" in row: raise ValueError("incoming spell ID requires a complete bundle")
            event["damage"]=_int(row.get("damage"),"damage",0,2**30)
        incoming.append(event)
    rec=[]
    for row in array(raw.get("recovery",[]),"recovery",0,10000):
        _object(row,"recovery",("time_us","hp","sp","kind","duration_us","evidence"))
        label(row.get("evidence"),"recovery evidence",2048)
        kind=row.get("kind")
        if kind not in ("potion","rest"): raise ValueError("unknown recovery kind")
        when=_int(row.get("time_us"),"recovery time_us",0,horizon)
        duration=_int(row.get("duration_us",0),"duration_us",int(kind=="rest"),when)
        if kind=="potion" and duration: raise ValueError("instantaneous potion cannot have duration")
        rec.append(dict(time_us=when,duration_us=duration,kind=kind,hp=_int(row.get("hp",0),"hp",0,2**30),
                        sp=_int(row.get("sp",0),"sp",0,2**30)))
    intervals=sorted((r["time_us"]-r["duration_us"],r["time_us"]) for r in rec if r["kind"]=="rest")
    if any(a[1]>b[0] for a,b in zip(intervals,intervals[1:])):
        raise ValueError("overlapping recovery intervals")
    if intervals:
        times=sorted(i["time_us"] for i in incoming)
        if any((j:=bisect_left(times,b))<len(times) and times[j]<end for b,end in intervals):
            blockers.append("incoming damage during declared safe rest")
    for tag in array(raw.get("unsupported_mechanics",[]),"unsupported_mechanics",0,128):
        blockers.append("unresolved scenario mechanic "+label(tag,"unsupported mechanic"))
    tape=[_float(v,"draw",0,1) for v in array(raw.get("tape",[]),"tape",0,100000)]
    if any(v==1 for v in tape): raise ValueError("random draw must be below one")
    rooms=_rooms(raw,actor,enemies,horizon)
    first=_int(raw.get("first_round_us",5_000_000),"first_round_us",0,60_000_000)
    period=_int(raw.get("round_period_us",5_000_000),"round_period_us",1,60_000_000)
    if period!=5_000_000 or first>period:
        blockers.append("ordinary world magic rounds require five seconds between ticks and a phase in [0,5s]")
    return dict(**actor,horizon_us=horizon,enemies=enemies,incoming=sorted(incoming,key=lambda x:x["time_us"]),
                **({"rooms":rooms} if rooms else {}),
                recovery=sorted(rec,key=lambda x:x["time_us"]),tape=tape,
                first_round_us=first,round_period_us=period)


def _policies(raw,spell_ids,n):
    ids,policies=[],[]
    for item in array(raw,"policies",1,65536):
        _object(item,"policy",("id","rules"))
        ids.append(label(item.get("id"),"policy.id"))
        rules=[]
        for r in array(item.get("rules"),"priority rules",1,128):
            _object(r,"policy rule",("spell","target","hp_below_pct","sp_below_pct","shield_below"))
            name=label(r.get("spell"),"spell reference")
            if name not in spell_ids: raise ValueError("unknown policy spell "+name)
            rule={"spell":spell_ids.index(name)}
            if "target" in r: rule["target"]=_int(r["target"],"target",-1,n-1)
            for key in ("hp_below_pct","sp_below_pct","shield_below"):
                if key in r: rule[key]=_int(r[key],key,0,2**30 if key=="shield_below" else 100)
            rules.append(rule)
        policies.append(rules)
    return unique(ids,"policy ID"),policies


@lru_cache(maxsize=1)
def _package_rules():
    from .ruleset import load_ruleset, validate_encounter_ruleset
    return validate_encounter_ruleset(load_ruleset())


def freeze_encounter(request,ruleset=None):
    from .ruleset import validate_encounter_ruleset
    rules=_package_rules() if ruleset is None else validate_encounter_ruleset(ruleset)
    raw=deepcopy(_object(request,"encounter request",("schema_version","ruleset_hash","actor","scenario",
                                                      "spells","policies","seeds","search","description")))
    _int(raw.get("schema_version",1),"schema_version",1,1)
    if raw.get("ruleset_hash",rules["content_hash"])!=rules["content_hash"]: raise ValueError("encounter ruleset mismatch")
    blockers=[]
    actor,live,climb=_actor(raw.get("actor"),blockers,rules)
    trained=_object(raw["actor"].get("school_trained",{}),"school_trained",("mysticism","restoration"))
    trained={k:_int(v,k,0,200) for k,v in trained.items()}
    owned=unique([_int(n,"owned signature",-(2**31),-1) for n in array(
        raw["actor"].get("known_signature_indices",[]),"owned signature indices",0,128)],"signature index")
    ids,spells=_spellbook(raw.get("spells"),actor,live,climb,trained,blockers,rules["encounter_paths"],owned)
    scenario=_scenario(raw.get("scenario"),actor,blockers,ids,spells)
    scenario["wards"]=freeze_wards(raw["actor"].get("wards"),scenario["horizon_us"],blockers)
    incoming=scenario["incoming"]
    if any(e["kind"]=="bundle" for e in incoming) and "defense" not in raw["actor"]:
        blockers.append("incoming spell bundles require observed player defense")
    if any(e["wards"].get("reflect_chance") for e in scenario["enemies"]) and "defense" not in raw["actor"]:
        blockers.append("reflected bundles require observed player defense")
    if any(e["kind"]=="spell" for e in incoming) and any(scenario["wards"].values()):
        blockers.append("defensive spell interaction requires the incoming bundle")
    if ("defense" not in raw["actor"] and any(s["range_type"]==4 for s in spells) and
            any(e["x_mm"]**2+e["z_mm"]**2<=4350**2 for e in scenario["enemies"])):
        blockers.append("self blast requires observed player defense")
    policy_ids,policies=_policies(raw.get("policies"),ids,len(scenario["enemies"]))
    seeds=unique([_int(v,"seed",0,2**32-1) for v in array(raw.get("seeds"),"seeds",1,65536)],"seed")
    opts=_object(raw.get("search",{}),"search",("max_policies","max_events","memory_bytes","wall_seconds","objective"))
    search={k:_int(opts.get(k,d),k,lo,hi) for k,d,lo,hi in (
            ("max_policies",0,0,100000),("max_events",0,0,2**53-1),("memory_bytes",64<<20,1,2**53-1))}
    search["wall_seconds"]=_float(opts.get("wall_seconds",0),"wall_seconds",0,86400)
    search["objective"]=opts.get("objective","pareto")
    if search["objective"] not in ("pareto","clear_probability","kills_per_minute","survival_probability","damage_per_sp"):
        raise ValueError("unsupported encounter objective")
    return dict(raw=raw,ruleset_hash=rules["content_hash"],source_sha=rules["source_sha"],scenario=scenario,
                spells=spells,policies=policies,seeds=seeds,spell_ids=ids,policy_ids=policy_ids,search=search,
                blockers=sorted(set(blockers)))
