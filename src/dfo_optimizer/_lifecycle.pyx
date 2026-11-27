# cython: language_level=3
"""Finite cross-stage purchase and checkpoint search. The traversal runs without the GIL."""
from libc.stdint cimport int64_t, uint64_t
from libcpp.vector cimport vector
from ._encounter cimport PackedEncounter, freeze_scene_abi
from math import isfinite
include "_spell_common.pxi"
include "spellbook.pxi"

cdef extern from "lifecycle_search.hpp" namespace "dfo_lifecycle":
    cdef cppclass Cancel:
        void cancel() noexcept
        cpp_bool cancelled() noexcept
        cpp_bool has_incumbent() noexcept
    cdef cppclass Option:
        uint64_t requires_mask
        double score
        int64_t sp
    cdef cppclass Stage:
        vector[Option] options
        vector[int64_t] prices
        int64_t ceiling
    cdef cppclass Witness:
        vector[int] end_hp,end_sp
        vector[int] choices
        vector[uint64_t] bought
        vector[double] scores,metric_axes
        int64_t spent
    cdef cppclass Report:
        vector[Witness] routes
        uint64_t nodes, pruned, leaves, work_bytes
        double first_seconds
        int end
    Report search(const vector[Stage]&,uint64_t,uint64_t,uint64_t,double,Cancel&) except + nogil
    vector[int] frontier(const vector[vector[double]]&) except + nogil

def frontier_indices(rows):
    cdef vector[vector[double]] data
    cdef vector[int] keep
    for row in rows:
        if not row or len(row)!=len(rows[0]) or any(type(v) not in (float,int) or not isfinite(v) for v in row):
            raise ValueError("invalid objective row")
        data.push_back(row)
    with nogil:
        keep=frontier(data)
    return list(keep)

cdef class CancelToken:
    cdef Cancel token
    cdef readonly object progression_token
    cdef readonly object class_token
    def __cinit__(self):
        from ._progression import CancelToken as ProgressionToken
        from ._native import CancelToken as ClassToken
        self.progression_token = ProgressionToken()
        self.class_token = ClassToken()
    def cancel(self):
        self.token.cancel()
        self.progression_token.cancel()
        self.class_token.cancel()
    def cancelled(self):
        return bool(self.token.cancelled())
    def has_incumbent(self):
        return bool(self.token.has_incumbent())
    def mark_replayed(self):
        mark_replayed(self.token)

cdef extern from "lifecycle_search.hpp" namespace "dfo_lifecycle":
    void mark_replayed(Cancel&) noexcept

def _integer(value,label,low,high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"invalid {label}")
    return value

def traverse(stages, prices, ceilings, owned=0, *, max_nodes=0, memory_bytes=64<<20,
             wall_seconds=0, CancelToken cancel=None):
    cdef vector[Stage] packed
    cdef Stage stage
    cdef Option option
    cdef Witness w
    cdef Report report
    cdef CancelToken token=CancelToken() if cancel is None else cancel
    cdef uint64_t nodes=_integer(max_nodes,"node limit",0,2**63-1)
    cdef uint64_t memory=_integer(memory_bytes,"memory limit",1,2**63-1)
    if type(wall_seconds) not in (float,int) or not isfinite(wall_seconds) or wall_seconds<0:
        raise ValueError("invalid lifecycle time limit")
    cdef double wall=wall_seconds
    if not 1<=len(stages)<=256 or len(prices)!=len(stages) or len(ceilings)!=len(stages):
        raise ValueError("invalid checkpoint count")
    count=len(prices[0])
    if count>63 or len(stages)*(3+count)>1024:
        raise ValueError("lifecycle domain exceeds supported stack or physical asset capacity")
    mask_max=(1<<count)-1
    cdef uint64_t holdings=_integer(owned,"holdings",0,mask_max)
    for opts,amounts,ceiling in zip(stages,prices,ceilings,strict=True):
        if len(amounts)!=count:
            raise ValueError("inconsistent lifecycle asset count")
        stage.options.clear()
        stage.ceiling=_integer(ceiling,"lifecycle budget",0,2**53-1)
        stage.prices=[_integer(p,"price",-1,2**53-1) for p in amounts]
        for required,score in opts:
            option.requires_mask=_integer(required,"required assets",0,mask_max)
            option.sp=0
            if type(score) not in (float,int) or not isfinite(score) or score<0:
                raise ValueError("invalid checkpoint score")
            option.score=score
            stage.options.push_back(option)
        packed.push_back(stage)
    with nogil:
        report=search(packed,holdings,nodes,memory,wall,token.token)
    result=[]
    for w in report.routes:
        result.append({"spent":w.spent,"choices":list(w.choices),"bought":list(w.bought),"scores":list(w.scores)})
    return {"routes":result,"termination":("exhausted","node_limit","time_limit","memory_limit","cancelled")[report.end],
            "nodes":report.nodes,"pruned":report.pruned,"leaves":report.leaves,"work_bytes":report.work_bytes,
            "first_native_seconds":report.first_seconds if report.first_seconds>=0 else None}

cdef extern from "gear_search.hpp" namespace "dfo_gear":
    cdef cppclass GearOption "dfo_gear::Option":
        int mods[8]
        int legendary,worn
        cpp_bool owned
    cdef cppclass Place:
        int item
        unsigned int mask
    cdef cppclass Slot:
        int id,lock,current,preferred
        vector[Place] entries

cdef extern from "lifecycle_combat.hpp" namespace "dfo_lifecycle":
    cdef cppclass Physical:
        vector[GearOption] items
        vector[Slot] slots
        vector[vector[int]] declared
        vector[int] wellspring
        vector[Bundle] hostile_book
        cpp_bool automatic
    cdef cppclass CombatStage:
        Context ctx
        int64_t ceiling
        int intelligence, quarters, worn_int
        cpp_bool uncertain_worn
        int64_t sp_ceiling
        int64_t remaining_debt_cap
        vector[int64_t] prices
    void set_encounter(CombatStage&,const PackedEncounter&,unsigned int) except +
    cdef cppclass JointResult:
        Report search
        vector[vector[vector[int]]] slots
        vector[vector[int]] policies
        uint64_t evaluations,cache_hits,layout_count,uncertain,preparation_nodes
    JointResult joint(const Physical&,const vector[CombatStage]&,const vector[Bundle]&,
                      const vector[vector[int]]&,uint64_t,uint64_t,uint64_t,double,Cancel&,int) except + nogil

cdef Physical _physical(items,slots,declared):
    cdef Physical g
    cdef GearOption item
    cdef Slot slot
    cdef Place place
    if len(slots)!=27:
        raise ValueError("expected 27 physical slots")
    for mods, _, legend, worn, owned in items:
        if len(mods)!=8 or type(owned) is not bool:
            raise ValueError("invalid physical modifiers")
        for i in range(8): item.mods[i]=_integer(mods[i],"item modifier",0,1000)
        item.legendary=_integer(legend,"legendary group",-1,len(items))
        item.worn=_integer(worn,"worn slot",-1,26)
        item.owned=owned
        g.items.push_back(item)
    for i,(lock,current,preferred,entries) in enumerate(slots):
        slot.id=i
        slot.lock=_integer(lock,"slot lock",-2,len(items))
        slot.current=_integer(current,"current slot item",-1,len(items))
        slot.preferred=_integer(preferred,"paired slot",-1,26)
        slot.entries.clear()
        for item_id, mask in entries:
            place.item=_integer(item_id,"item id",0,len(items)-1)
            place.mask=_integer(mask,"slot occupancy",1,(1<<27)-1)
            if not mask & (1<<i): raise ValueError("placement omits anchor")
            slot.entries.push_back(place)
        g.slots.push_back(slot)
    g.automatic=declared is None
    if declared is not None:
        for row in declared:
            if len(row)!=27: raise ValueError("expected complete loadout")
            g.declared.push_back([_integer(v,"loadout item",-1,len(items)-1) for v in row])
    return g

def optimize_route(stages,items,slots,declared,bundles,policies,owned,*,encounters=None,wellspring=None,max_nodes=0,
                   memory_bytes=64<<20,wall_seconds=0,CancelToken cancel=None,objective="legacy"):
    from .lifecycle_objectives import validate_objective
    validate_objective({"objective":objective, **({"encounter":True} if encounters is not None else {})})
    cdef int metric={"legacy":0, "overall_pve":0, "endgame_damage":0, "progression_effort":0,
                     "encounter_damage":1, "clear_performance":2, "damage_per_sp":3,
                     "resource_sustain":4, "survivability":5, "pareto":6}[objective]
    cdef Physical g=_physical(items,slots,declared)
    cdef vector[CombatStage] frozen
    cdef vector[Bundle] book
    cdef vector[vector[int]] scripts
    cdef CombatStage s
    cdef PackedEncounter scene
    cdef JointResult result
    cdef Witness w
    cdef CancelToken token=CancelToken() if cancel is None else cancel
    count=len(bundles)+len(items)
    if wellspring is not None:
        if len(wellspring)!=len(items): raise ValueError("missing gear recovery roll")
        g.wellspring=[_integer(v,"Wellspring recovery percentage",0,10) for v in wellspring]
    if count>63 or not stages or len(stages)*(3+count)>1024:
        raise ValueError("lifecycle domain exceeds supported checkpoint/asset dimensions")
    if encounters:
        from .spellbook import pack_spell
        for recipe in encounters[0][0].get("hostile_recipes", []):
            g.hostile_book.push_back(prepare_bundle(pack_spell(recipe)))
    for row in bundles: book.push_back(prepare_bundle(row))
    for policy in policies:
        allow_initial_wait=not policy and encounters is None and len(stages)>1
        if not allow_initial_wait and not 1<=len(policy)<=128:
            raise ValueError("expected 1..128 supported casts per policy or a creation checkpoint wait")
        scripts.push_back([_integer(i,"spell id",0,len(bundles)-1) for i in policy])
    for ctx,ceil,prices,intel,quarters,worn,uncertain,sp_ceiling,debt_cap in stages:
        s.ctx=prepare_context(ctx)
        if len(prices)!=count or type(uncertain) is not bool: raise ValueError("invalid stage resources")
        s.ceiling=_integer(ceil,"funds",0,2**53-1)
        s.prices=[_integer(p,"price",-1,2**53-1) for p in prices]
        s.intelligence=_integer(intel,"Intelligence",0,100)
        s.quarters=_integer(quarters,"magery quarters",0,12)
        s.worn_int=_integer(worn,"worn Intelligence",0,27000)
        s.uncertain_worn=uncertain
        s.sp_ceiling=_integer(sp_ceiling,"SP reserve",0,2**53-1)
        s.remaining_debt_cap=_integer(debt_cap,"rest recovery deficit ceiling",0,2**53-1)
        if encounters is not None:
            if len(encounters)!=len(stages): raise ValueError("missing checkpoint encounter")
            raw,seed=encounters[frozen.size()]
            if raw.get("player_defense"):
                s.ctx=prepare_context(raw["caster"])
            scene=freeze_scene_abi(raw)
            set_encounter(s,scene,_integer(seed,"encounter seed",0,2**32-1))
        frozen.push_back(s)
    cdef uint64_t base=_integer(owned,"ownership",0,(1<<count)-1)
    cdef uint64_t nodes=_integer(max_nodes,"node limit",0,2**63-1)
    cdef uint64_t mem=_integer(memory_bytes,"memory limit",1,2**63-1)
    if type(wall_seconds) not in (int,float) or not isfinite(wall_seconds) or wall_seconds<0:
        raise ValueError("invalid lifecycle time limit")
    cdef double wall=wall_seconds
    with nogil:
        result=joint(g,frozen,book,scripts,base,nodes,mem,wall,token.token,metric)
    routes=[]
    for i in range(result.search.routes.size()):
        w=result.search.routes[i]
        routes.append({"spent":w.spent,"bought":list(w.bought),"scores":list(w.scores),
                       "slots":list(result.slots[i]),"policies":list(result.policies[i])})
        if objective != "legacy":
            routes[-1]["metric_axes"]=list(w.metric_axes)
        if encounters is not None:
            routes[-1]["end_hp"]=list(w.end_hp)
            routes[-1]["end_sp"]=list(w.end_sp)
    return {"routes":routes,"termination":("exhausted","node_limit","time_limit","memory_limit","cancelled")[result.search.end],
            "nodes":result.search.nodes,"pruned":result.search.pruned,"leaves":result.search.leaves,
            "work_bytes":result.search.work_bytes,"evaluations":result.evaluations,"cache_hits":result.cache_hits,
            "layouts":result.layout_count,"uncertain":result.uncertain,"preparation_nodes":result.preparation_nodes}
