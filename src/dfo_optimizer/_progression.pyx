# cython: language_level=3
"""Convert a finite, frozen online progression schedule to one native search."""
from libc.stdint cimport uint64_t, int64_t
from libcpp cimport bool as cpp_bool
from libcpp.vector cimport vector
from math import isfinite

cdef extern from "progression_search.hpp" namespace "dfo_progression":
    cdef cppclass Cancel:
        void cancel() noexcept
        cpp_bool has_incumbent() noexcept
    cdef cppclass Career:
        int group[35]
        int multipliers[35]
        int reflexes, starting_sum
        double advancement
    cdef cppclass State:
        int skills[35]
        int attributes[8]
        int level, current_sum, pending_level, pending_pool
        int arcane_path, martial_path, challenge_level
        uint64_t known[4]
        uint64_t mastered
        int64_t uses[35]
        int64_t spam_at[35]
        int64_t minutes, last_check, last_training, last_rest
        int64_t real_ms, challenge_at, gold, bank_gold, sp, fatigue
        double fractions[35]
        double progress[35]
        double spam_recent[35]
        double move_mark[35]
        double move_credit[35]
        double odometer_h, odometer_v
    cdef cppclass Action:
        Action() except +
        int kind, skill, count, amount, challenge_level, spell, roll
        int family, path, first, second, member, bonus, focus, until_skill
        int64_t cadence_ms, minutes, real_elapsed_ms, sp_cost, gold_cost, fatigue_cost
        int64_t refill_sp, refill_fatigue
        double price_factor
        cpp_bool recipe_set, if_due, if_eligible, use_order, movement, short_rest
        double horizontal_m, vertical_m
        int allocation[8]
        int order[8]
        int recipe[7]
    cdef cppclass Goal:
        int level, arcane, martial
        int skills[35]
        int attributes[8]
        uint64_t mastered
        uint64_t known[4]
    cdef cppclass Limits:
        uint64_t max_nodes, memory_bytes
        double wall_seconds
        cpp_bool retain_states, final_stage_only
    cdef cppclass Effort:
        int64_t practice, rest_passes, minutes, spent
    cdef cppclass Path:
        State state
        Effort effort
        vector[int] choices
    cdef cppclass Report:
        vector[Path] results
        Path prefix
        uint64_t nodes, pruned, leaves, hits, work_bytes
        double first_seconds
        int end
    Report native_search "dfo_progression::search"(const Career&,const State&,const vector[vector[Action]]&,
                                                  const Goal&,const Limits&,Cancel&) except + nogil

cdef class CancelToken:
    cdef Cancel flag
    def cancel(self):
        self.flag.cancel()
    def has_incumbent(self):
        return bool(self.flag.has_incumbent())

KINDS = ("skip","practice","rest","check","train","master","level","choose","reset","buy")
MULTIPLIERS = (12,1,1,5,15,15,15,15,15,15,15,15,15,2,1,2,2,1,2,1,4,50,1,2,1,1,2,1,2,2,2,2,2,1,8)
MAX_INTEGER = (1<<53)-1

def _int(v, name, lo=0, hi=MAX_INTEGER):
    if type(v) is not int or not lo <= v <= hi:
        raise ValueError(f"invalid {name}")
    return v

def _float(v, name, lo=0., hi=MAX_INTEGER):
    if type(v) not in (float,int) or not isfinite(v) or not lo <= v <= hi:
        raise ValueError(f"invalid {name}")
    return v

def _flag(v,name):
    if type(v) is not bool:
        raise ValueError(f"invalid {name}")
    return v

def _list(v,name,size=None):
    if not isinstance(v,(tuple,list)) or (size is not None and len(v)!=size):
        raise ValueError(f"invalid {name}")
    return v

def _ids(v,name,top,size=None):
    values=[_int(i,name,0,top) for i in _list(v,name,size)]
    if len(set(values))!=len(values):
        raise ValueError(f"duplicate {name}")
    return values

cdef Career _career(dict row):
    cdef Career c
    groups=set()
    for group_id,(name,length) in enumerate((("primary",3),("major",3),("minor",6)),1):
        for i in _ids(row[name],name,34,length):
            if i in groups: raise ValueError("overlapping career groups")
            groups.add(i)
            c.group[i]=group_id
    for i,v in enumerate(_list(row.get("skill_multipliers",MULTIPLIERS),"skill_multipliers",35)):
        c.multipliers[i]=_int(v,"advancement multiplier",1,100)
    c.advancement=_float(row["advancement_multiplier"],"advancement_multiplier",.01,10.)
    c.reflexes=_int(row["reflexes"],"reflexes",0,4)
    c.starting_sum=_int(row["starting_sum"],"starting_sum",0,840)
    return c

cdef State _state(dict r):
    cdef State s
    cdef int i
    for k in ("skills","uses","fractions","progress"): _list(r[k],k,35)
    for k in ("spam_recent","spam_at","move_mark","move_credit"):
        if k in r: _list(r[k],k,35)
    s.real_ms=_int(r.get("real_ms",0),"real_ms")
    s.odometer_h=_float(r.get("odometer_h",0.),"odometer_h")
    s.odometer_v=_float(r.get("odometer_v",0.),"odometer_v")
    for i in range(35):
        s.skills[i]=_int(r["skills"][i],"skill",0,200)
        s.uses[i]=_int(r["uses"][i],"uses",0,1<<42)
        s.fractions[i]=_float(r["fractions"][i],"fraction",0.,1.)
        if s.fractions[i]>=1.: raise ValueError("fraction must be below one")
        s.progress[i]=_float(r["progress"][i],"progress",0.,1e12)
        if "spam_at" in r: s.spam_at[i]=_int(r["spam_at"][i],"spam_at",0,s.real_ms)
        if "spam_recent" in r: s.spam_recent[i]=_float(r["spam_recent"][i],"spam_recent")
        s.move_mark[i]=_float(r["move_mark"][i],"move_mark",-1.) if "move_mark" in r else -1.
        if "move_credit" in r: s.move_credit[i]=_float(r["move_credit"][i],"move_credit",0.,2.)
    for i,v in enumerate(_list(r["attributes"],"attributes",8)): s.attributes[i]=_int(v,"attribute",0,100)
    for i in _ids(r["mastered"],"mastered",34): s.mastered|=(<uint64_t>1)<<i
    for i in _ids(r["known"],"known",255): s.known[i//64]|=(<uint64_t>1)<<(i%64)
    s.level=_int(r["level"],"level",1,45)
    s.current_sum=_int(r["current_sum"],"current_sum",0,840)
    s.pending_level=_int(r["pending_level"],"pending_level",-1,45)
    s.pending_pool=_int(r["pending_pool"],"pending_pool",-1,30)
    s.minutes=_int(r["minutes"],"minutes")
    s.last_check=_int(r["last_check"],"last_check")
    s.last_training=_int(r["last_training"],"last_training")
    s.last_rest=_int(r.get("last_rest",-1),"last_rest",-1)
    s.gold=_int(r["gold"],"gold")
    s.bank_gold=_int(r.get("bank_gold",0),"bank_gold")
    s.sp=_int(r["sp"],"sp")
    s.fatigue=_int(r["fatigue"],"fatigue")
    s.arcane_path=_int(r["arcane_path"],"arcane_path",-1,255)
    s.martial_path=_int(r["martial_path"],"martial_path",-1,255)
    s.challenge_level=_int(r.get("challenge_level",0),"challenge_level",0,10000)
    s.challenge_at=_int(r.get("challenge_at",-1),"challenge_at",-1,s.real_ms)
    return s

cdef int _family(object a):
    return ("arcane","martial").index(a["family"])

cdef Action _action(dict a):
    cdef Action v
    kind=a["kind"]
    v.kind=KINDS.index(kind)
    v.real_elapsed_ms=_int(a.get("real_elapsed_ms",0),"real_elapsed_ms",0,10**10)
    if kind in ("practice","train","master"): v.skill=_int(a["skill"],"skill",0,34)
    if kind in ("choose","reset") or (kind=="buy" and a.get("path",-1)>=0):
        v.family=_family(a)
    if kind=="practice":
        v.fatigue_cost=_int(a.get("fatigue_cost",0),"practice fatigue_cost",0,1<<30)
        v.count=_int(a.get("count",1),"count",1,100000)
        v.amount=_int(a.get("amount",1),"amount",1,20000)
        v.cadence_ms=_int(a.get("cadence_ms",0),"cadence_ms",0,1000000)
        v.challenge_level=_int(a.get("challenge_level",0),"challenge_level",0,10000)
        v.spell=_int(a.get("spell",-1),"spell",-1,255)
        v.sp_cost=_int(a.get("sp_cost",0),"sp_cost",0,1<<27)
        v.until_skill=_int(a.get("until_skill",201),"until_skill",0,201)
        v.minutes=_int(a.get("minutes",0),"minutes",0,(1<<31)-1)
        if "horizontal_m" in a or "vertical_m" in a:
            if v.skill not in (3,17,18,21): raise ValueError("movement requires a movement skill")
            v.movement=True
            v.horizontal_m=_float(a.get("horizontal_m",0.),"horizontal_m",0.,10**6)
            v.vertical_m=_float(a.get("vertical_m",0.),"vertical_m",0.,10**6)
        if "recipe" in a:
            recipe=_list(a["recipe"],"recipe",7)
            # Stock spells use byte fields and can exceed the creator's spinner bounds.
            for i,(x,lo,hi) in enumerate(zip(recipe,(0,1,0,0,0,0,1),(4,4,255,255,255,255,255))):
                v.recipe[i]=_int(x,"spell recipe",lo,hi)
            if v.skill!=22 or v.spell<0 or recipe[2]>recipe[3] or recipe[4]>recipe[5]:
                raise ValueError("invalid training spell recipe")
            v.recipe_set=True
            v.bonus=_int(a.get("skill_bonus",0),"skill_bonus",-1000,10000)
            v.focus=_int(a.get("focus_pct",0),"focus_pct",0,1000)
    elif kind=="check":
        v.minutes=_int(a.get("minutes",0),"minutes",0,(1<<31)-1)
        v.short_rest=_flag(a.get("short_rest",False),"short_rest")
    elif kind=="rest":
        v.minutes=_int(a.get("minutes",480),"night minutes",480,480)
        v.refill_sp=_int(a.get("refill_sp",-1),"refill_sp",-1)
        v.refill_fatigue=_int(a.get("refill_fatigue",-1),"refill_fatigue",-1)
    elif kind=="train":
        v.roll=_int(a["roll"],"roll",10,20)
        v.fatigue_cost=_int(a.get("fatigue_cost",1980),"fatigue_cost",0,1<<30)
        if "member" in a:
            v.member=_flag(a["member"],"member")
            v.price_factor=_float(a.get("price_factor",1.),"price_factor",0.,10**6)
        else:
            v.gold_cost=_int(a["gold_cost"],"gold_cost")
    elif kind=="master":
        v.if_eligible=_flag(a.get("if_eligible",False),"if_eligible")
    elif kind=="level":
        v.if_due=_flag(a.get("if_due",False),"if_due")
        if "allocation_order" in a:
            v.use_order=True
            for i,x in enumerate(_ids(a["allocation_order"],"allocation_order",7,8)): v.order[i]=x
        else:
            for i,x in enumerate(_list(a["allocation"],"allocation",8)): v.allocation[i]=_int(x,"attribute delta",0,30)
    elif kind=="choose":
        v.path=_int(a["path"],"path",0,255)
        v.first,v.second=_ids(a["pair"],"pair",34,2)
    elif kind=="buy":
        v.path=_int(a.get("path",-1),"path",-1,255)
        v.spell=_int(a["spell"],"spell",0,255)
        v.gold_cost=_int(a["gold_cost"],"gold_cost")
    return v

cdef Goal _goal(dict r):
    cdef Goal g
    cdef int i
    g.level=_int(r.get("level",0),"goal level",0,45)
    g.arcane=_int(r.get("arcane_path",-1),"goal arcane path",-1,255)
    g.martial=_int(r.get("martial_path",-1),"goal martial path",-1,255)
    for k,v in r.get("skills",{}).items():
        i=_int(k,"goal skill id",0,34)
        g.skills[i]=_int(v,"target skill",0,200)
    for k,v in r.get("attributes",{}).items():
        i=_int(k,"goal attribute id",0,7)
        g.attributes[i]=_int(v,"target attribute",0,100)
    for i in _ids(r.get("mastered",[]),"goal mastered",34): g.mastered|=(<uint64_t>1)<<i
    for i in _ids(r.get("known",[]),"goal known",255): g.known[i//64]|=(<uint64_t>1)<<(i%64)
    if set(r)-{"level","arcane_path","martial_path","skills","attributes","mastered","known"}:
        raise ValueError("unknown progression goal")
    return g

cdef dict _path(const Path &p,dict start):
    cdef const State *s=&p.state
    cdef int i
    result=dict(start,skills=[s.skills[i] for i in range(35)],uses=[s.uses[i] for i in range(35)],
        fractions=[s.fractions[i] for i in range(35)],progress=[s.progress[i] for i in range(35)],
        spam_recent=[s.spam_recent[i] for i in range(35)],spam_at=[s.spam_at[i] for i in range(35)],
        move_mark=[s.move_mark[i] for i in range(35)],move_credit=[s.move_credit[i] for i in range(35)],
        odometer_h=s.odometer_h,odometer_v=s.odometer_v,
        attributes=[s.attributes[i] for i in range(8)],
        mastered=[i for i in range(35) if s.mastered&((<uint64_t>1)<<i)],
        known=[i for i in range(256) if s.known[i//64]&((<uint64_t>1)<<(i%64))],
        level=s.level,current_sum=s.current_sum,pending_level=s.pending_level,pending_pool=s.pending_pool,
        minutes=s.minutes,last_check=s.last_check,last_training=s.last_training,last_rest=s.last_rest,
        real_ms=s.real_ms,challenge_at=s.challenge_at,challenge_level=s.challenge_level,gold=s.gold,bank_gold=s.bank_gold,sp=s.sp,
        fatigue=s.fatigue,arcane_path=s.arcane_path,martial_path=s.martial_path)
    return {"choices":list(p.choices),"state":result,"effort":{"practice":p.effort.practice,
            "rest_passes":p.effort.rest_passes,"minutes":p.effort.minutes,"spent":p.effort.spent}}

def search(dict start, stages, dict goal, *, max_nodes=100000, memory_bytes=67108864,
           wall_seconds=0., CancelToken cancel=None, retain_states=False, final_stage_only=False):
    cdef Career career=_career(start)
    cdef State state=_state(start)
    cdef Goal target=_goal(goal)
    cdef Limits limits
    cdef Report report
    cdef vector[vector[Action]] domain
    cdef vector[Action] choices
    cdef CancelToken token=CancelToken() if cancel is None else cancel
    limits.max_nodes=_int(max_nodes,"max_nodes",0,1<<62)
    limits.memory_bytes=_int(memory_bytes,"memory_bytes",1,1<<62)
    limits.wall_seconds=_float(wall_seconds,"wall_seconds",0,10**8)
    limits.retain_states=_flag(retain_states,"retain_states")
    limits.final_stage_only=_flag(final_stage_only,"final_stage_only")
    if len(_list(stages,"stages"))>100000: raise ValueError("too many stages")
    total=0
    for row in stages:
        total+=len(_list(row,"stage alternatives"))
        if total>1000000: raise ValueError("too many actions")
    pack = total*sizeof(Action) + len(stages)*sizeof(vector[Action]) <= limits.memory_bytes
    if pack:
        domain.reserve(len(stages))
        for row in stages:
            domain.push_back(choices)
            domain.back().reserve(len(row))
            for action in row: domain.back().push_back(_action(action))
    else:
        for row in stages:
            for action in row: _action(action)
        # Return an initial witness with the normal budget termination without
        # allocating the input that already exceeds the native working budget.
        limits.memory_bytes=1
    with nogil:
        report=native_search(career,state,domain,target,limits,token.flag)
    return {"results":[_path(report.results[i],start) for i in range(report.results.size())],
            "prefix":_path(report.prefix,start),"nodes":report.nodes,"leaves":report.leaves,
            "pruned":report.pruned,"work_bytes":report.work_bytes,"cache_hits":report.hits,
            "first_feasible_seconds":report.first_seconds if report.first_seconds>=0 else None,
            "termination":("exhausted","node_limit","time_limit","memory_limit","cancelled")[report.end]}
