# cython: language_level=3
"""Validated batch bridge to the deterministic ordinary-PvE encounter kernel."""
from libcpp.vector cimport vector
from libc.stdint cimport uint32_t, uint64_t
from math import isfinite
from time import perf_counter
include "_spell_common.pxi"

cdef extern from "spell_kernel.hpp" namespace "dfo_spell":
    cdef cppclass Token:
        void cancel() noexcept
        cpp_bool has_incumbent() noexcept

cdef extern from "encounter_kernel.hpp" namespace "dfo_enc":
    cdef cppclass MeleeMove:
        int skill,low,high,damage_mod,hit_mod,both,blunt,impact_us,ready_us
    cdef cppclass ArmorPiece:
        int condition,maximum,type,covers
        int rows[8]
    cdef cppclass Fighter:
        int stats[8]
        int level,group,index,min_metal,flags,adrenaline,dodge,crit
        int weapon,metal,condition,maximum,repool
        ArmorPiece armor[8]
        MeleeMove armed,bare
    cdef cppclass Defenses:
        int absorb_chance,reflect_chance,resist_chance
        cpp_bool career_absorbs,enchant_absorbs
        vector[int] set_absorb_chances
    cdef cppclass Effect:
        int type,subtype,base_low,base_high,plus_low,plus_high,per_level,climb
        int chance_base,chance_increment,chance_per_level
        int duration_base,duration_increment,duration_per_level
    cdef cppclass Foe:
        Context defense
        Defenses wards
        int hp,x_mm,z_mm,radius_mm,distance_mm,level,absorb_skill,sp,max_sp
        cpp_bool undead_daedra,kill_eligible,trapped
    cdef cppclass Incoming:
        int64_t time_us
        int source,damage,spell
        cpp_bool blow
    cdef cppclass Room:
        int64_t delay_us
        int rest_hp,rest_sp,heal_spell
        vector[int] enemies
        vector[Incoming] incoming
    cdef cppclass Recovery:
        int64_t time_us,duration_us
        int hp,sp
        cpp_bool rest
    cdef cppclass Encounter:
        vector[Fighter] fighters
        cpp_bool backup
        int enemy_reach_mm,fatigue
        Context caster
        Defenses wards
        int hp,max_hp,max_sp,path_id,martial_id,wellspring_pct
        int64_t horizon_us,first_round_us,round_period_us
        vector[Foe] enemies
        vector[Incoming] incoming
        vector[Room] rooms
        vector[Recovery] recovery
        vector[double] tape
    cdef cppclass Spell:
        int element,range_type,cost_sp,climb
        cpp_bool signature
        vector[Effect] effects
    cdef cppclass Rule:
        int spell,target,hp_below_pct,sp_below_pct,shield_below
    cdef cppclass Limits:
        uint64_t max_events,memory_bytes
        double wall_seconds
        cpp_bool trace,frontier
        int objective
    cdef cppclass Event:
        int64_t time_us
        int kind,target,spell,value,hp,sp,shield,target_hp
    cdef cppclass Trial:
        cpp_bool physical
        int melee_swings,melee_hits,incoming_swings,incoming_hits,spent_fatigue,end_fatigue
        int64_t melee_damage
        int64_t initial_sp,spent_sp,restored_sp,damage,kills,casts,impacts
        int64_t healing,mitigated,consumables,rest_us
        int end_hp,end_sp,min_hp,min_sp
        int64_t end_us
        cpp_bool dead,cleared
        uint64_t draws
        vector[Event] trace
    cdef cppclass PolicyResult:
        int policy_index
        vector[Trial] trials
    cdef cppclass Report:
        int end
        uint64_t events,trials_completed,work_bytes,policies_completed
        double first_native_seconds
        vector[PolicyResult] rows
    Report run_batch "dfo_enc::evaluate"(const Encounter&,const vector[Spell]&,const vector[vector[Rule]]&,
                                         const vector[uint32_t]&,const Limits&, Token&) except + nogil

cdef class CancelToken:
    cdef Token flag
    cdef bint requested
    def cancel(self):
        self.requested=True
        self.flag.cancel()
    def cancelled(self):
        return bool(self.requested)
    def has_incumbent(self):
        return bool(self.flag.has_incumbent())

def _whole(v,key,lo,hi):
    if type(v) is not int or not lo<=v<=hi:
        raise ValueError(f"invalid {key}")
    return v

def _boolean(v,key):
    if type(v) is not bool:
        raise ValueError(f"invalid {key}")
    return v

def _sequence(v,key,lo,hi):
    if not isinstance(v,(list,tuple)) or not lo<=len(v)<=hi:
        raise ValueError(f"invalid {key}")
    return v

def _mapping(v,key):
    if not isinstance(v,dict):
        raise ValueError(f"invalid {key}")
    return v

cdef Defenses pack_wards(object value):
    cdef Defenses result
    _mapping(value,"wards")
    result.absorb_chance=_whole(value.get("absorb_chance",0),"active absorption",0,50)
    result.reflect_chance=_whole(value.get("reflect_chance",0),"active reflection",0,100)
    result.resist_chance=_whole(value.get("resist_chance",0),"active resistance",0,100)
    result.career_absorbs=_boolean(value.get("career_absorbs",False),"career absorption")
    result.enchant_absorbs=_boolean(value.get("enchant_absorbs",False),"enchantment absorption")
    for chance in _sequence(value.get("set_absorb_chances",[]),"registered absorption",0,32):
        result.set_absorb_chances.push_back(_whole(chance,"registered absorption chance",0,100))
    return result

cdef MeleeMove pack_move(object row):
    cdef MeleeMove m
    _sequence(row,"physical move",9,9)
    m.skill=_whole(row[0],"weapon skill",0,100)
    m.low=_whole(row[1],"minimum damage",0,1000)
    m.high=_whole(row[2],"maximum damage",m.low,1000)
    m.damage_mod=_whole(row[3],"proficiency damage",0,100)
    m.hit_mod=_whole(row[4],"proficiency hit",0,100)
    m.both=_whole(row[5],"two hands",0,1)
    m.blunt=_whole(row[6],"blunt",0,1)
    m.impact_us=_whole(row[7],"swing impact",1,10_000_000)
    m.ready_us=_whole(row[8],"swing ready",m.impact_us,20_000_000)
    return m

cdef Fighter pack_fighter(object raw):
    cdef Fighter f
    cdef ArmorPiece p
    cdef int i,j
    _mapping(raw,"physical combatant")
    for i,v in enumerate(_sequence(raw.get("stats"),"physical stats",8,8)):
        f.stats[i]=_whole(v,"physical stat",0,100)
    f.level=_whole(raw.get("level"),"physical level",1,255)
    f.group=_whole(raw.get("group"),"physical group",-1,3)
    f.index=_whole(raw.get("index"),"physical enemy career",-1,18)
    f.min_metal=_whole(raw.get("min_metal"),"minimum metal",-1,9)
    f.flags=_whole(raw.get("attack_flags"),"attack flags",0,255)
    f.adrenaline=_whole(raw.get("adrenaline"),"adrenaline",0,1)
    f.dodge=_whole(raw.get("dodge"),"Dodging",0,255)
    f.crit=_whole(raw.get("crit"),"Critical Strike",0,255)
    weapon=_sequence(raw.get("weapon"),"physical weapon",4,4)
    f.weapon=_whole(weapon[0],"weapon template",-1,128)
    if f.weapon!=-1 and f.weapon<113: raise ValueError("unsupported weapon")
    f.metal=_whole(weapon[1],"weapon material",-1 if f.weapon==-1 else 0,9)
    f.maximum=_whole(weapon[3],"maximum condition",0,1_000_000)
    f.condition=_whole(weapon[2],"condition",0,0 if f.weapon==-1 else f.maximum)
    f.repool=_whole(raw.get("repool",0),"legacy condition migration",0,1_000_000)
    f.armed=pack_move(raw.get("armed"))
    f.bare=pack_move(raw.get("bare"))
    for i,row in enumerate(_sequence(raw.get("armor"),"armor positions",8,8)):
        _sequence(row,"physical armor",12,12)
        p.maximum=_whole(row[1],"armor maximum condition",0,1_000_000)
        p.condition=_whole(row[0],"armor condition",0,p.maximum)
        p.type=_whole(row[2],"armor type",109 if i==7 and p.condition else 0,112 if i==7 else 188)
        p.covers=_whole(row[3],"protected locations",0,127)
        for j in range(8): p.rows[j]=_whole(row[4+j],"reduction ratio percent",0,100)
        f.armor[i]=p
    return f

cdef Encounter pack_scenario(dict raw):
    cdef Encounter e
    cdef Foe f
    cdef Incoming inc
    cdef Room room
    cdef Recovery rv
    cdef int64_t previous
    e.caster=prepare_context(raw["caster"])
    if "physical" in raw:
        phys=_mapping(raw["physical"],"physical scene")
        e.backup=_boolean(phys.get("fallback"),"backup melee")
        e.fatigue=_whole(phys.get("fatigue"),"current physical fatigue",0,2**30)
        e.enemy_reach_mm=_whole(phys.get("enemy_reach_mm"),"enemy reach",1,10000)
        size=len(_sequence(raw.get("enemies"),"physical targets",1,256))+1
        for fighter in _sequence(phys.get("actors"),"physical actors",size,size):
            e.fighters.push_back(pack_fighter(fighter))
    e.wards=pack_wards(raw.get("wards",{}))
    e.max_hp=_whole(raw.get("max_hp"),"max_hp",1,2000000000)
    e.hp=_whole(raw.get("hp"),"hp",1,e.max_hp)
    e.max_sp=_whole(raw.get("max_sp"),"max_sp",e.caster.available_sp,2147483647)
    e.horizon_us=_whole(raw.get("horizon_us"),"horizon_us",0,86_400_000_000)
    e.first_round_us=_whole(raw.get("first_round_us",5_000_000),"first_round_us",0,86_400_000_000)
    e.round_period_us=_whole(raw.get("round_period_us",5_000_000),"round_period_us",1,86_400_000_000)
    e.path_id=_whole(raw.get("path_id",0),"path_id",0,15)
    e.martial_id=_whole(raw.get("martial_id",0),"martial_id",0,15)
    e.wellspring_pct=_whole(raw.get("wellspring_pct",0),"wellspring_pct",0,10)
    for row in _sequence(raw.get("enemies"),"enemies",1,256):
        _mapping(row,"enemy")
        f.hp=_whole(row.get("hp"),"foe HP",1,2_000_000_000)
        # Targets have distinct ancestry/wards and never inherit player defences.
        f.defense=prepare_context({**dict.fromkeys(("level","climb","live_skill","speed","available_sp"),1),
                                   "willpower":50,**row,"target_hp":f.hp})
        f.x_mm=_whole(row.get("x_mm",0),"foe X",-1_000_000,1_000_000)
        f.z_mm=_whole(row.get("z_mm",0),"foe Z",-1_000_000,1_000_000)
        f.radius_mm=_whole(row.get("radius_mm",450),"body radius",0,10000)
        f.distance_mm=_whole(row.get("distance_mm",-1),"impact distance",-1,2_000_000)
        f.undead_daedra=_boolean(row.get("undead_daedra",False),"undead_daedra")
        f.kill_eligible=_boolean(row.get("kill_eligible",True),"kill eligibility")
        f.trapped=_boolean(row.get("trapped",False),"trapped")
        f.wards=pack_wards(row.get("wards",{}))
        f.level=_whole(row.get("level",1),"enemy level",1,1000)
        f.absorb_skill=_whole(row.get("absorb_skill",0),"enemy live Destruction",0,10000)
        f.max_sp=_whole(row.get("max_sp",0),"enemy SP capacity",0,2147483647)
        f.sp=_whole(row.get("sp",0),"enemy SP",0,f.max_sp)
        e.enemies.push_back(f)
    owner=[-1]*e.enemies.size()
    for i,wave in enumerate(_sequence(raw.get("rooms",[]),"rooms",0,e.enemies.size())):
        _mapping(wave,"room")
        room.enemies.clear()
        room.delay_us=_whole(wave.get("delay_us",0),"room transition delay",0,0 if i==0 else 86_400_000_000)
        if ("rest_hp" in wave)!=("rest_sp" in wave) or ("rest_hp" in wave and not room.delay_us):
            raise ValueError("room rest needs paired resource floors and a positive delay")
        room.rest_hp=_whole(wave["rest_hp"],"room rest HP",0,e.max_hp) if "rest_hp" in wave else -1
        room.rest_sp=_whole(wave["rest_sp"],"room rest SP",0,e.max_sp) if "rest_sp" in wave else -1
        room.heal_spell=_whole(wave.get("heal_spell",-1),"protected heal spell",-1,8191)
        if room.heal_spell>=0 and (not room.delay_us or room.rest_sp>=0):
            raise ValueError("Room heal requires an interval without a simultaneous refill")
        for idx in _sequence(wave.get("enemies"),"room partition",1,e.enemies.size()):
            _whole(idx,"room partition index",0,e.enemies.size()-1)
            if owner[idx]!=-1: raise ValueError("duplicate enemy in room partition")
            owner[idx]=i
            room.enemies.push_back(idx)
        e.rooms.push_back(room)
    if e.rooms.size() and (-1 in owner or raw.get("recovery")):
        raise ValueError("invalid room partition or absolute recovery schedule")
    room_previous=[0]*e.rooms.size()
    previous=-1
    incoming_times=[]
    for row in _sequence(raw.get("incoming",[]),"incoming events",0,100000):
        _mapping(row,"incoming event")
        inc.source=_whole(row.get("source"),"incoming source",0,e.enemies.size()-1)
        room_id=owner[inc.source]
        lower=room_previous[room_id] if e.rooms.size() else max(0,previous)
        inc.time_us=_whole(row.get("time_us"),"incoming timestamp",lower,e.horizon_us)
        previous=inc.time_us
        if row.get("kind") not in ("blow","spell","bundle","melee"):
            raise ValueError("invalid incoming hit kind")
        if row["kind"]=="bundle":
            inc.damage=0
            inc.spell=_whole(row.get("spell"),"incoming spell index",0,8191)
        elif row["kind"]=="melee":
            if not e.fighters.size(): raise ValueError("incoming melee needs a verified physical actor panel")
            inc.damage=0
            inc.spell=-2
        else:
            inc.spell=-1
            inc.damage=_whole(row.get("damage"),"incoming damage",0,2_000_000_000)
        inc.blow=row["kind"]=="blow"
        if e.rooms.size():
            e.rooms[room_id].incoming.push_back(inc)
            room_previous[room_id]=inc.time_us
        else:
            e.incoming.push_back(inc)
        incoming_times.append(inc.time_us)
    previous=-1
    from bisect import bisect_left
    for row in _sequence(raw.get("recovery",[]),"recovery events",0,10000):
        _mapping(row,"recovery event")
        rv.time_us=_whole(row.get("time_us"),"recovery timestamp",max(0,previous),e.horizon_us)
        if row.get("kind") not in ("potion","rest"):
            raise ValueError("invalid recovery kind")
        rv.rest=row["kind"]=="rest"
        rv.duration_us=_whole(row.get("duration_us",0),"recovery duration",1 if rv.rest else 0,rv.time_us if rv.rest else 0)
        rv.hp=_whole(row.get("hp",0),"recovery HP",0,e.max_hp if rv.rest else 2_000_000_000)
        rv.sp=_whole(row.get("sp",0),"recovery SP",0,e.max_sp if rv.rest else 2_000_000_000)
        if rv.rest:
            start=rv.time_us-rv.duration_us
            pos=bisect_left(incoming_times,start)
            if start<previous or (pos<len(incoming_times) and incoming_times[pos]<rv.time_us):
                raise ValueError("safe rest overlaps another encounter event")
        previous=rv.time_us
        e.recovery.push_back(rv)
    for roll in _sequence(raw.get("tape",[]),"draw tape",0,1_000_000):
        if type(roll) not in (int,float) or not 0<=roll<1:
            raise ValueError("invalid draw tape value")
        e.tape.push_back(roll)
    return e

cdef PackedEncounter freeze_scene_abi(dict raw) except *:
    cdef Encounter scene=pack_scenario(raw)
    return (<PackedEncounter*>&scene)[0]

cdef Spell pack_action(object row):
    cdef Spell s
    cdef Effect e
    _mapping(row,"spell")
    s.cost_sp=_whole(row.get("cost_sp"),"cost_sp",0,2_000_000_000)
    s.element=_whole(row.get("element"),"element",0,4)
    s.range_type=_whole(row.get("range_type"),"range_type",0,4)
    s.climb=_whole(row.get("climb",-1),"school climb",-1,140)
    s.signature=_boolean(row.get("signature",False),"signature")
    for value in _sequence(row.get("effects"),"spell effects",1,3):
        _mapping(value,"effect")
        e.type=_whole(value.get("type"),"effect type",0,255)
        e.subtype=_whole(value.get("subtype"),"effect subtype",-1,255)
        if e.subtype==-1: e.subtype=255
        key=(e.type,e.subtype)
        if key not in ((4,0),(5,255),(10,8),(35,255),(18,255),(19,255)):
            raise ValueError("unsupported encounter effect")
        if (s.range_type==0)!=(key in ((10,8),(35,255),(18,255))):
            raise ValueError("unsupported effect targeting mode")
        e.base_low=_whole(value.get("base_low",0),"base_low",0,1000)
        e.base_high=_whole(value.get("base_high",e.base_low),"base_high",e.base_low,1000)
        e.plus_low=_whole(value.get("plus_low",0),"plus_low",0,1000)
        e.plus_high=_whole(value.get("plus_high",e.plus_low),"plus_high",e.plus_low,1000)
        e.per_level=_whole(value.get("per_level",1),"per_level",1,255)
        e.chance_base=_whole(value.get("chance_base",0),"chance_base",0,100)
        e.chance_increment=_whole(value.get("chance_increment",0),"chance_increment",0,100)
        e.chance_per_level=_whole(value.get("chance_per_level",1),"chance_per_level",1,255)
        e.duration_base=_whole(value.get("duration_base",0),"duration_base",0,1000)
        e.duration_increment=_whole(value.get("duration_increment",0),"duration_increment",0,1000)
        e.duration_per_level=_whole(value.get("duration_per_level",1),"duration_per_level",1,255)
        e.climb=_whole(value.get("climb",-1),"effect school climb",-1,140)
        s.effects.push_back(e)
    return s

_EVENTS=("click","release","impact","round","incoming","kill","death","miss","wait","restore",
         "absorbed","reflected","resisted","room","melee_start","melee_impact","melee_miss","enemy_melee_impact","enemy_melee_miss")
_STOPS=("exhausted","event_limit","time_limit","memory_limit","cancelled")

cdef dict trial_dict(const Trial& t):
    cdef Event e
    cdef size_t i
    events=[]
    for i in range(t.trace.size()):
        e=t.trace[i]
        events.append((e.time_us,_EVENTS[e.kind],e.target,e.spell,e.value,e.hp,e.sp,e.shield,e.target_hp))
    physical = ({"melee_damage":t.melee_damage,"melee_swings":t.melee_swings,"melee_hits":t.melee_hits,
                 "incoming_swings":t.incoming_swings,"incoming_hits":t.incoming_hits,
                 "spent_fatigue":t.spent_fatigue,"end_fatigue":t.end_fatigue} if t.physical else {})
    return {**physical,"initial_sp":t.initial_sp,"spent_sp":t.spent_sp,"restored_sp":t.restored_sp,
            "healing":t.healing,"mitigated":t.mitigated,"consumables":t.consumables,"rest_us":t.rest_us,
            "damage":t.damage,"kills":t.kills,"casts":t.casts,"impacts":t.impacts,
            "end_hp":t.end_hp,"end_sp":t.end_sp,"min_hp":t.min_hp,"min_sp":t.min_sp,
            "end_us":t.end_us,"dead":bool(t.dead),"cleared":bool(t.cleared),"draws":t.draws,
            "trace":events}

cdef dict no_work(str reason):
    return {"termination":reason,"events":0,"trials_completed":0,"policies_completed":0,
            "work_bytes":0,"first_native_seconds":None,"rows":[]}

def evaluate(dict scenario,spells,policies,seeds,*,trace=False,max_events=0,memory_bytes=64<<20,
             wall_seconds=0,CancelToken cancel=None,frontier=False,objective="pareto"):
    cdef Encounter enc
    cdef vector[Spell] actions
    cdef vector[vector[Rule]] compiled
    cdef vector[Rule] rules
    cdef Rule r
    cdef vector[uint32_t] draws
    cdef Limits limits
    cdef Report report
    cdef size_t i,j
    cdef uint64_t minimum
    cdef double deadline=0
    cdef CancelToken token=CancelToken() if cancel is None else cancel
    limits.memory_bytes=_whole(memory_bytes,"memory budget",1,2**62)
    limits.trace=_boolean(trace,"trace")
    limits.frontier=_boolean(frontier,"frontier")
    objectives=("pareto","clear_probability","kills_per_minute","survival_probability","damage_per_sp")
    if objective not in objectives: raise ValueError("unsupported encounter objective")
    limits.objective=objectives.index(objective)
    limits.max_events=_whole(max_events,"event budget",0,2**62)
    if type(wall_seconds) not in (float,int) or not isfinite(wall_seconds) or not 0<=wall_seconds<=86400:
        raise ValueError("invalid time budget")
    if wall_seconds: deadline=perf_counter()+wall_seconds
    if token.requested: return no_work("cancelled")
    minimum_rules=0 if scenario.get("allow_wait") is True or scenario.get("physical",{}).get("fallback") is True else 1
    _sequence(spells,"spells",minimum_rules,8192)
    _sequence(policies,"policies",1,65536)
    _sequence(seeds,"seeds",1,65536)
    minimum=(sizeof(Encounter)+sizeof(Spell)*len(spells)+sizeof(uint32_t)*len(seeds)+
             sizeof(vector[Rule])*len(policies)+sizeof(double)*len(scenario.get("tape",()))+
             sizeof(Foe)*len(scenario.get("enemies",()))+sizeof(Incoming)*len(scenario.get("incoming",()))+
             sizeof(Recovery)*len(scenario.get("recovery",()))+sizeof(Room)*len(scenario.get("rooms",())))
    # Reject an oversized packed candidate domain before duplicating its input
    # into native storage. The evaluator then measures actual vector capacities.
    for p in policies:
        minimum+=sizeof(Rule)*len(_sequence(p,"rules",minimum_rules,128))
    minimum+=2*sizeof(Fighter)*len(scenario.get("physical",{}).get("actors",()))
    for spell in spells:
        minimum+=sizeof(Effect)*len(_sequence(_mapping(spell,"spell").get("effects"),"effects",1,3))
    if minimum>limits.memory_bytes: return no_work("memory_limit")
    enc=pack_scenario(scenario)
    actions.reserve(len(spells))
    compiled.reserve(len(policies))
    draws.reserve(len(seeds))
    for spell in spells:
        actions.push_back(pack_action(spell))
    for p in policies:
        if token.requested: return no_work("cancelled")
        if deadline and perf_counter()>=deadline: return no_work("time_limit")
        rules.clear()
        for value in _sequence(p,"rules",minimum_rules,128):
            _mapping(value,"rule")
            r.spell=_whole(value.get("spell"),"spell index",0,actions.size()-1)
            r.target=_whole(value.get("target",-1),"target index",-1,enc.enemies.size()-1)
            r.hp_below_pct=_whole(value.get("hp_below_pct",-1),"HP threshold",-1,100)
            r.sp_below_pct=_whole(value.get("sp_below_pct",-1),"SP threshold",-1,100)
            r.shield_below=_whole(value.get("shield_below",-1),"shield threshold",-1,2_000_000_000)
            rules.push_back(r)
        compiled.push_back(rules)
    for seed in seeds:
        draws.push_back(_whole(seed,"seed",0,2**32-1))
    if deadline:
        limits.wall_seconds=deadline-perf_counter()
        if limits.wall_seconds<=0: return no_work("time_limit")
    with nogil:
        report=run_batch(enc,actions,compiled,draws,limits,token.flag)
    return {"termination":_STOPS[report.end],"events":report.events,"trials_completed":report.trials_completed,
            "policies_completed":report.policies_completed,"work_bytes":report.work_bytes,
            "first_native_seconds":report.first_native_seconds if report.first_native_seconds>=0 else None,
            "rows":[{"policy_index":report.rows[i].policy_index,
                     "trials":[trial_dict(report.rows[i].trials[j]) for j in range(report.rows[i].trials.size())]}
                    for i in range(report.rows.size())]}
