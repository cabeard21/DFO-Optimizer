# cython: language_level=3
"""Coarse-grained native calls. All Python conversions happen outside traversal."""
import math
from time import perf_counter
from array import array

import cython
from cpython.array cimport array as c_array, clone
from libc.stdint cimport INT32_MIN, INT32_MAX, int32_t, int64_t, uint32_t, uint64_t
from libc.math cimport copysign
from libcpp cimport bool as cppbool
from libcpp.vector cimport vector

cdef extern from "native_build.hpp":
    const char* dfo_compiler() noexcept
    const char* dfo_flags() noexcept

cdef extern from "class_search.hpp" namespace "dfo":
    cdef cppclass CancelFlag:
        void cancel() noexcept
        cppbool is_cancelled() noexcept
        cppbool has_incumbent() noexcept
    cdef cppclass Trait:
        int id, side, cost, family
        cppbool required
        void block(int other) noexcept
    cdef cppclass Options:
        vector[Trait] traits
        vector[int] hp, races
        vector[vector[int]] attributes, skills
        int target, k
        uint64_t max_nodes, memory_bytes, magic_mask
        double wall_seconds
        cppbool max_intelligence, stop_after_top, require_magic
    cdef cppclass Candidate:
        int hp, race, count
        int attributes[8]
        int skills[12]
        int traits[14]
    cdef enum End:
        exhausted
        top_k
        node_limit
        time_limit
        memory_limit
        cancelled
        sample_limit
    cdef cppclass Output:
        End end
        uint64_t nodes, pruned, leaves, work_bytes
        double first_seconds
        vector[Candidate] best
    Output search(const Options&, CancelFlag&) except + nogil
    cdef cppclass DiscoveryConfig:
        cppbool exhaustive, stable_examples
        uint32_t seed
        uint64_t required_masteries, required_skills
        vector[uint32_t] rolls
        void trait(int,int,int,int,int)
        void add_stage() except +
        void item(int,int) except +
        void start_beginner() except +
        void beginner_part(int) except +
        void beginner_weapon(int,int,int) except +
        void beginner_probe(int) except +
        void beginner_probe_weapon(int,int,int) except +
        void beginner_plate(int) except +
        void beginner_attack_cost(int,int) except +
        void beginner_capacity(int) except +
    cdef cppclass ScreenFeatures:
        int hp, absorption, destruction_sum, sp_sum, speed_sum
        int eligible[32]
        cppbool pareto
        int headroom
        uint64_t backups
    cdef cppclass BeginnerPanel:
        void add(int,int,const vector[int]&,const vector[int]&,uint64_t,int,int,double) except +
        vector[int] select(int,const vector[int]&,const CancelFlag&,double) except + nogil
    cdef cppclass DiscoveryOutput:
        Output visited
        vector[ScreenFeatures] features
        uint64_t unique_screened, attempts, pareto_overflows, pareto_retained, pareto_capacity
        uint64_t beginner_admissible
        uint64_t beginner_rejections[16]
    DiscoveryOutput discover(const Options&,CancelFlag&,const DiscoveryConfig&) except + nogil
    int hp_points(int hp) noexcept nogil


def build_info():
    return {"compiler": dfo_compiler().decode("ascii"), "flags": dfo_flags().decode("ascii")}


def beginner_panel(rows, prior, cap, CancelToken cancel=None, wall_seconds=0.0):
    """Merge the retained outputs of disjoint class-cost searches with stable diversity."""
    cdef BeginnerPanel panel
    cdef vector[int] traits, skills, initial, selected
    cdef int k = _whole(cap,1,10000,"beginner panel size")
    cdef CancelToken token = CancelToken() if cancel is None else cancel
    cdef double seconds=wall_seconds
    if type(wall_seconds) not in (int,float) or not math.isfinite(seconds) or seconds<0:
        raise ValueError("invalid panel time limit")
    started=perf_counter()
    if not isinstance(rows,(list,tuple)) or len(rows)>530000:
        raise ValueError("invalid beginner panel")
    for i,(target,row) in enumerate(rows):
        if not (i & 255) and (token.cancelled() or (seconds and perf_counter()-started>=seconds)):
            return []
        target = _whole(target,-12,40,"difficulty")
        race = _whole(row["race"],1,8,"race")
        traits = _domain(row["traits"],0,127,"traits")
        skills = _domain(row["skills"],0,34,"skills")
        if traits.size()>14 or skills.size()!=12:
            raise ValueError("invalid panel traits or skills")
        screen = row["screen"]
        backup = _whole(screen["usable_backup_skill_mask"],0,(1<<35)-1,"backup mask")
        headroom = _whole(screen["minimum_headroom_units"],0,1000000,"headroom")
        gear = _whole(sum(screen["eligible_stage_items"]),0,100000,"gear count")
        sp = screen["mean_birth_sp"]
        if type(sp) not in (int,float) or not 0<=sp<=300:
            raise ValueError("invalid panel SP")
        panel.add(target,race,traits,skills,backup,headroom,gear,sp)
    if not isinstance(prior,(tuple,list)) or len(set(prior))!=len(prior) or len(prior)>k:
        raise ValueError("invalid previous beginner panel")
    for index in prior:
        initial.push_back(_whole(index,0,len(rows)-1,"previous panel index"))
    if seconds:
        seconds=max(1e-12,seconds-(perf_counter()-started))
    with nogil:
        selected=panel.select(k,initial,token.flag,seconds)
    return selected


cdef bint _same_json_tree(object value, object reference, int depth):
    """The reference is an authenticated, finite tree of plain JSON values."""
    cdef Py_ssize_t index
    cdef object key, item
    if value is reference:
        return True
    if depth > 64 or type(value) is not type(reference):
        return False
    if type(reference) is dict:
        if len(<dict>value) != len(<dict>reference):
            return False
        for key, item in (<dict>value).items():
            if type(key) is not str or key not in <dict>reference:
                return False
            if not _same_json_tree(item, (<dict>reference)[key], depth + 1):
                return False
        return True
    if type(reference) is list:
        if len(<list>value) != len(<list>reference):
            return False
        for index in range(len(<list>reference)):
            if not _same_json_tree((<list>value)[index], (<list>reference)[index], depth + 1):
                return False
        return True
    if type(reference) is float:
        return <double>value == <double>reference and copysign(1., <double>value) == copysign(1., <double>reference)
    return type(reference) in (int, bool, str) and value == reference


def same_json_tree(value, reference):
    """Compare an external JSON input with a trusted snapshot while holding the GIL."""
    return bool(_same_json_tree(value, reference, 0))


cdef class CancelToken:
    """Thread-safe one-shot token; call cancel() while another thread searches."""
    cdef CancelFlag flag

    def cancel(self):
        self.flag.cancel()

    def cancelled(self):
        """Read the same signal used by native traversal during finalist checks."""
        return bool(self.flag.is_cancelled())

    def has_incumbent(self):
        """Whether this token's search has retained its first feasible class."""
        return bool(self.flag.has_incumbent())


@cython.boundscheck(False)
@cython.wraparound(False)
cdef Py_ssize_t _batch(const int32_t[::1] hp, const int32_t[::1] positive,
                       const int32_t[::1] negative, int32_t[::1] points,
                       double[::1] multipliers) noexcept nogil:
    cdef Py_ssize_t i
    cdef int64_t value
    cdef int setting, adv, dis
    for i in range(hp.shape[0]):
        setting, adv, dis = hp[i], positive[i], negative[i]
        if setting < 4 or setting > 30 or adv < 0 or dis > 0:
            return i
        value = <int64_t>hp_points(setting) + adv + dis
        if value < INT32_MIN or value > INT32_MAX:
            return i
        points[i] = <int32_t>value
        multipliers[i] = 0.3 + 2.7 * (<double>value + 12.0) / 52.0
    return -1


def evaluate_batch(const int32_t[::1] hp not None, const int32_t[::1] advantages not None,
                   const int32_t[::1] disadvantages not None):
    cdef Py_ssize_t n = hp.shape[0]
    cdef Py_ssize_t invalid
    if n != advantages.shape[0] or n != disadvantages.shape[0]:
        raise ValueError("HP and adjustment arrays must have the same length")
    cdef c_array points = clone(array("i"), n, False)
    cdef c_array advancement = clone(array("d"), n, False)
    cdef int32_t[::1] point_view = points
    cdef double[::1] advancement_view = advancement
    with nogil:
        invalid = _batch(hp, advantages, disadvantages, point_view, advancement_view)
    if invalid >= 0:
        raise ValueError(f"invalid HP, signed adjustment or total at row {invalid}")
    return {"rows": n, "points": points, "advancement": advancement}


def _whole(value, low, high, field):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{field} must be an integer from {low} to {high}")
    return value


def _domain(values, low, high, field):
    if not isinstance(values, (list, tuple, range)) or len(values) > high - low + 1:
        raise ValueError(f"invalid {field} domain")
    checked = [_whole(v, low, high, field) for v in values]
    if len(set(checked)) != len(checked):
        raise ValueError(f"duplicate value in {field} domain")
    return checked


cdef vector[Trait] _trait_table(rows):
    cdef vector[Trait] packed
    cdef Trait row
    cdef int j, other
    if not isinstance(rows, (list, tuple)) or len(rows) > 128:
        raise ValueError("at most 128 trait rows are supported")
    ids = set()
    conflicts = {}
    for item in rows:
        trait_id, side, cost, blocked, required, family = item
        row.id = _whole(trait_id, 0, 127, "trait ID")
        if trait_id in ids:
            raise ValueError("duplicate trait ID")
        ids.add(trait_id)
        row.side = _whole(side, 0, 1, "trait side")
        row.cost = _whole(cost, -14 if side else 0, 0 if side else 14, "trait cost")
        row.family = _whole(family, 0, 3, "last-writer family")
        if type(required) is not bool:
            raise ValueError("required must be boolean")
        row.required = required
        for other in _domain(blocked, 0, 127, "conflicting IDs"):
            conflicts.setdefault(trait_id, set()).add(other)
            conflicts.setdefault(other, set()).add(trait_id)
        packed.push_back(row)
    for j in range(packed.size()):
        for other in conflicts.get(packed[j].id, ()):
            packed[j].block(other)
    return packed


cdef vector[vector[int]] _domains(rows, int size, int low, int high, field):
    cdef vector[vector[int]] packed
    if not isinstance(rows, (list, tuple)) or len(rows) != size:
        raise ValueError(f"expected {size} {field} domains")
    for domain in rows:
        packed.push_back(_domain(domain, low, high, field))
    return packed


cdef dict _decode(Output& out):
    cdef size_t i
    cdef int j
    cdef Candidate c
    results = []
    for i in range(out.best.size()):
        c = out.best[i]
        results.append({
            "race": c.race, "hp": c.hp,
            "attributes": tuple([c.attributes[j] for j in range(8)]),
            "skills": tuple([c.skills[j] for j in range(12)]),
            "traits": tuple([c.traits[j] for j in range(c.count)]),
        })
    reasons = ("exhausted", "top_k", "node_limit", "time_limit", "memory_limit", "cancelled", "sample_limit")
    return {
        "results": results, "termination": reasons[<int>out.end],
        "nodes": out.nodes, "pruned": out.pruned, "leaves": out.leaves,
        "first_feasible_seconds": out.first_seconds if out.leaves else None,
        "work_bytes": out.work_bytes,
    }


cdef uint64_t _skill_mask(values):
    cdef uint64_t bits = 0
    cdef int skill
    for skill in _domain(values, 0, 34, "required skills"):
        bits |= (<uint64_t>1) << skill
    return bits


cdef void _starter_tables(DiscoveryConfig& config, object tables) except *:
    if not isinstance(tables,dict) or set(tables)!={"parts","probes","plate_weights","capacity","attack_costs"}:
        raise ValueError("invalid beginner creation tables")
    for key,size in (("parts",144),("probes",864),("plate_weights",10),("capacity",101),("attack_costs",82)):
        if not isinstance(tables[key],(tuple,list)) or len(tables[key])!=size:
            raise ValueError("invalid beginner table length")
    config.start_beginner()
    for index, cost in enumerate(tables["attack_costs"]):
        config.beginner_attack_cost(index,_whole(cost,1,100000,"starter damage spell cost"))
    for units in tables["plate_weights"]:
        config.beginner_plate(_whole(units,0,1000000,"cuirass weight"))
    for units in tables["capacity"]:
        config.beginner_capacity(_whole(units,0,1000000,"capacity"))
    for key in ("parts","probes"):
        for weight,weapons in tables[key]:
            weight = _whole(weight,0,1000000,"kit weight")
            if key == "parts":
                config.beginner_part(weight)
            else:
                config.beginner_probe(weight)
            if not isinstance(weapons,(list,tuple)) or len(weapons)>64:
                raise ValueError("invalid birth weapon rows")
            for skill,material,gear in weapons:
                skill = _whole(skill,0,34,"weapon skill")
                material = _whole(material,0,1023,"material mask")
                gear = _whole(gear,0,63,"weapon mask")
                if key == "parts":
                    config.beginner_weapon(skill,material,gear)
                else:
                    config.beginner_probe_weapon(skill,material,gear)


cdef dict _discover(Options& options, CancelToken token, object raw):
    cdef DiscoveryConfig config
    cdef DiscoveryOutput output
    cdef ScreenFeatures features
    cdef size_t index
    allowed = {"exhaustive", "seed", "required_masteries", "required_skills", "roll_seeds",
               "trait_features", "stage_items", "stable_examples","beginner"}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise ValueError("invalid native discovery options")
    exhaustive = raw.get("exhaustive", False)
    if type(exhaustive) is not bool:
        raise ValueError("exhaustive must be boolean")
    config.exhaustive = exhaustive
    examples = raw.get("stable_examples", False)
    if type(examples) is not bool:
        raise ValueError("stable_examples must be boolean")
    config.stable_examples = examples
    if "beginner" in raw:
        if examples: raise ValueError("beginner gates require mechanics screening")
        _starter_tables(config,raw["beginner"])
    config.seed = _whole(raw.get("seed", 42), 0, 2**32-1, "screen seed")
    config.required_masteries = _skill_mask(raw.get("required_masteries", []))
    config.required_skills = _skill_mask(raw.get("required_skills", []))
    rolls = raw.get("roll_seeds", [42, 97])
    if not isinstance(rolls, (list,tuple)) or not 1 <= len(rolls) <= 128:
        raise ValueError("require 1..128 paired screen rolls")
    for seed in rolls:
        config.rolls.push_back(_whole(seed, 0, 2**32-1, "roll seed"))
    if len(set(rolls)) != len(rolls):
        raise ValueError("duplicate paired roll seed")
    table = raw.get("trait_features", [])
    if not isinstance(table, (list,tuple)) or len(table) > 128:
        raise ValueError("invalid trait feature rows")
    ids = set()
    for ident, magery, materials, gear, absorb in table:
        ident = _whole(ident, 0, 127, "trait feature ID")
        if ident in ids:
            raise ValueError("duplicate trait feature ID")
        ids.add(ident)
        config.trait(ident, _whole(magery, 0, 12, "magery quarters"),
                     _whole(materials, 0, INT32_MAX, "material bits"),
                     _whole(gear, 0, INT32_MAX, "equipment bits"),
                     _whole(absorb, 0, INT32_MAX, "absorption flag"))
    stages = raw.get("stage_items", [])
    if not isinstance(stages, (list,tuple)) or len(stages)>32:
        raise ValueError("at most 32 screening equipment pools")
    count = 0
    for stage in stages:
        if not isinstance(stage,(list,tuple)) or len(stage)+count>100000:
            raise ValueError("invalid screening equipment pool")
        count += len(stage)
        config.add_stage()
        for materials, gear in stage:
            config.item(_whole(materials, 0, INT32_MAX, "item material mask"),
                        _whole(gear, 0, INT32_MAX, "item gear mask"))
    with nogil:
        output = discover(options, token.flag, config)
    decoded = _decode(output.visited)
    n = float(len(rolls))
    for index in range(output.features.size()):
        features = output.features[index]
        decoded["results"][index]["screen"] = {
            "birth_hp": features.hp, "absorption_flag": features.absorption,
            "mean_birth_sp": features.sp_sum/n,
            "mean_cast_rate": 1 + (features.speed_sum/n - 50)/200,
            "mean_birth_destruction": features.destruction_sum/n,
            "eligible_stage_items": [features.eligible[i] for i in range(len(stages))],
            "pareto_representative": bool(features.pareto),
        }
        if "beginner" in raw:
            decoded["results"][index]["screen"]["minimum_headroom_units"]=features.headroom
            decoded["results"][index]["screen"]["usable_backup_skill_mask"]=features.backups
    if "beginner" in raw:
        decoded["beginner_admissible"]=output.beginner_admissible
        decoded["beginner_rejections"]=[output.beginner_rejections[i] for i in range(16)]
    decoded["unique_screened"] = output.unique_screened
    decoded["attempts"] = output.attempts
    decoded["pareto_overflows"] = output.pareto_overflows
    decoded["pareto_retained"] = output.pareto_retained
    decoded["pareto_capacity"] = output.pareto_capacity
    return decoded


def search_classes(*, traits, hp_values, races, attributes, skills, target, top_k, max_nodes,
                   wall_seconds=0.0, memory_bytes=67108864, objective="examples",
                   stop_after_top=False, CancelToken cancel=None, require_magic=False, magic_skills=(),
                   discovery=None):
    cdef Options options
    cdef Output result
    cdef int skill
    cdef CancelToken token = CancelToken() if cancel is None else cancel
    options.traits = _trait_table(traits)
    options.hp = _domain(hp_values, 4, 30, "HP")
    options.races = _domain(races, 1, 8, "race")
    options.attributes = _domains(attributes, 8, 10, 75, "attribute")
    options.skills = _domains(skills, 12, 0, 34, "skill")
    options.target = _whole(target, -12, 40, "target difficulty")
    options.k = _whole(top_k, 1, 10000, "top_k")
    options.max_nodes = _whole(max_nodes, 0, 2**63-1, "max_nodes")
    options.memory_bytes = _whole(memory_bytes, 0, 2**63-1, "memory_bytes")
    if type(wall_seconds) not in (int, float) or not math.isfinite(wall_seconds) or wall_seconds < 0:
        raise ValueError("wall_seconds must be finite and non-negative")
    if objective not in ("examples", "max_intelligence"):
        raise ValueError("unsupported class objective")
    if type(stop_after_top) is not bool or type(require_magic) is not bool:
        raise ValueError("search switches must be boolean")
    if stop_after_top and objective != "examples":
        raise ValueError("stop_after_top applies only to feasibility examples")
    options.wall_seconds = wall_seconds
    options.max_intelligence = objective == "max_intelligence"
    options.stop_after_top = stop_after_top
    options.require_magic = require_magic
    options.magic_mask = 0
    for skill in _domain(magic_skills, 0, 34, "magic skills"):
        options.magic_mask |= (<uint64_t>1) << skill
    if discovery is not None:
        return _discover(options, token, discovery)
    with nogil:
        result = search(options, token.flag)
    return _decode(result)
