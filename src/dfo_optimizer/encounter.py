"""Offline seeded encounter evaluation, finite policy search and witness replay."""
from hashlib import sha256
import json
from time import perf_counter

from .encounter_reference import simulate_trial
from .encounter_request import freeze_encounter
from .encounter_statistics import probability_intervals, single_cast_exact


def _digest(value):
    return sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(",",":")).encode()).hexdigest()


def _identity(doc):
    return _digest({k:v for k,v in doc.items() if k not in ("timings","counters","result_hash","frozen_request")})


def _ratio(n,d):
    return n/d if d else None


def _metrics(trials,horizon):
    n=len(trials)
    def total(k): return sum(x[k] for x in trials)
    cleared=total("cleared")
    finish=sum(t["end_us"] for t in trials if t["cleared"])
    elapsed=total("end_us")
    result={"trials":n,"cleared_trials":cleared,"unfinished_trials":n-cleared,"dead_trials":total("dead"),
            "clear_probability":cleared/n,"death_probability":total("dead")/n,
            "survival_probability":1-total("dead")/n,"mean_kill_time_us":_ratio(finish,cleared),
            "censored_mean_clear_us":(finish+(n-cleared)*horizon)/n,"kills_per_minute":_ratio(total("kills")*60_000_000,elapsed),
            "damage_per_sp":_ratio(total("damage"),total("spent_sp"))}
    for field,name in (("damage","damage"),("casts","casts"),("kills","kills"),("end_hp","ending_hp"),("end_sp","ending_sp"),
                       ("min_hp","minimum_hp"),("min_sp","minimum_sp"),("healing","healing"),("mitigated","mitigated"),
                       ("consumables","consumables"),("rest_us","rest_us"),("spent_sp","sp_spent"),("restored_sp","sp_restored")):
        result["mean_"+name]=total(field)/n
    if trials and "melee_damage" in trials[0]:
        for k in ("melee_damage","melee_swings","melee_hits","incoming_swings","incoming_hits","spent_fatigue","end_fatigue"):
            result["mean_"+k]=total(k)/n
        result["spell_damage_per_sp"]=_ratio(total("damage")-total("melee_damage"),total("spent_sp"))
    return result


class _Interrupted(Exception):
    pass


def _witness(ctx,index,native_trials=None,poll=None):
    if type(index) is not int or not 0<=index<len(ctx["policies"]):
        raise ValueError("invalid encounter policy index")
    trials=[]
    trace=[]
    for i,seed in enumerate(ctx["seeds"]):
        if poll: poll()
        row=simulate_trial(ctx["scenario"],ctx["spells"],ctx["policies"][index],seed,trace=i==0,poll=poll)
        if native_trials is not None:
            their=native_trials[i]
            if any(their.get(k)!=v for k,v in row.items() if k!="trace"):
                diffs=[k for k,v in row.items() if k!="trace" and their.get(k)!=v]
                raise RuntimeError(f"encounter native/replay mismatch for policy {index}, seed {seed}, fields {diffs}")
            if [list(event) for event in their["trace"]]!=row["trace"]:
                raise RuntimeError(f"encounter native/replay event ordering differs for policy {index}, seed {seed}")
        history=row.pop("trace")
        if not i: trace=history
        trials.append(row)
    exact=single_cast_exact(ctx["scenario"],ctx["spells"],ctx["policies"][index])
    if poll: poll()
    return {"policy_id":ctx["policy_ids"][index],"policy_index":index,
            "metrics":_metrics(trials,ctx["scenario"]["horizon_us"]),
            "probability_intervals":probability_intervals(trials,ctx["scenario"]["tape"]),
            "single_cast_exact":exact,
            "trials_hash":_digest(trials),"first_trial":trials[0],"trace":trace}


_PARETO=("clear probability (max)","survival probability (max)","kills per elapsed minute (max)",
         "clipped hostile damage (max)","SP spent (min)","horizon-censored clear time (min)")


def _solve(request,ruleset,cancel,fixed):
    started=perf_counter()
    ctx=freeze_encounter(request,ruleset)
    if fixed and len(ctx["policies"])!=1:
        raise ValueError("evaluate_encounter requires exactly one fixed policy")
    if not ctx["blockers"]:
        try:
            from . import _encounter
        except ImportError as exc:
            raise RuntimeError("Encounter evaluation requires the compiled dfo_optimizer._encounter extension. Install the platform wheel or build the native extensions.") from exc
    opts=ctx["search"]
    deadline=started+opts["wall_seconds"] if opts["wall_seconds"] else None
    def poll():
        if cancel is not None and cancel.cancelled(): raise _Interrupted("cancelled")
        if deadline is not None and perf_counter()>=deadline: raise _Interrupted("time_limit")
    limit=opts["max_policies"] or len(ctx["policies"])
    started_native=perf_counter()
    native={"rows":[],"termination":"unsupported"}
    remaining=deadline-started_native if deadline is not None else 0.
    if not ctx["blockers"] and deadline is not None and remaining<=0:
        native["termination"]="time_limit"
    elif not ctx["blockers"]:
        native=_encounter.evaluate(ctx["scenario"],ctx["spells"],ctx["policies"][:limit],ctx["seeds"],
                trace=True,frontier=not fixed,objective=opts["objective"],cancel=cancel,
                wall_seconds=remaining,memory_bytes=opts["memory_bytes"],max_events=opts["max_events"])
    finished_native=perf_counter()
    term=native["termination"]
    if term=="exhausted" and limit<len(ctx["policies"]): term="policy_limit"
    frontier=[]
    first=None
    for row in native["rows"]:
        try:
            verified=_witness(ctx,row["policy_index"],row["trials"],poll=poll)
        except _Interrupted as stopped:
            term=str(stopped)
            break
        frontier.append(verified)
        if first is None: first=perf_counter()-started
    exact=term=="exhausted"
    status=("unsupported" if ctx["blockers"] else "cancelled" if term=="cancelled" else
            ("evaluated" if fixed else "optimal_proven") if exact else
            "best_found_bounded" if frontier else "no_feasible_found")
    counters={k:native.get(k,0) for k in ("events","trials_completed","policies_completed","work_bytes")}
    result={"schema_version":1,"kind":"encounter_result","mode":"evaluate" if fixed else "optimize",
            "status":status,"termination":term,"exact":exact,"source_sha":ctx["source_sha"],"ruleset_hash":ctx["ruleset_hash"],
            "input_hash":_digest(ctx["raw"]),"frozen_request":ctx["raw"],"blockers":ctx["blockers"],
            "objective":opts["objective"],"objective_axes":list(_PARETO) if opts["objective"]=="pareto" else [opts["objective"]],
            "frontier":frontier,"winner":frontier[0] if frontier else None,"counters":counters,
            "seed_scope":{"seeds":ctx["seeds"],"sampling":"fixed common-seed trials","rng":"xorshift32-v1",
                          "tape":bool(ctx["scenario"]["tape"])},
            "proof_scope":"Declared repeatable spellbook policies, stationary geometry, supplied attacks, recovery opportunities, world round phase and finite seed panel.",
            "timings":{"preparation_seconds":started_native-started,"native_seconds":finished_native-started_native,
                "first_native_seconds":native.get("first_native_seconds"),"first_replayed_seconds":first,
                "elapsed_seconds":perf_counter()-started}}
    if ctx["scenario"].get("physical"):
        from .physical_encounter import CORE, LAW_HASH
        result["physical_mechanics"]={"profile":CORE,"law_sha256":LAW_HASH,
            "geometry":"Awake stationary human class enemies, mutually visible and facing. Incoming attacks are supplied opportunities.",
            "timeline":"Spells and ordinary swings share hands. No equipment swap. A fallback preserves positive fatigue.",
            "scope":"Single checkpoint. Strike wear and fatigue persist across rooms. Practice has no in-fight skill-raise check."}
        result["proof_scope"]="Declared spell and fallback policy, physical copies, render cadence, geometry, hostile opportunities and finite draw panel."
    result["result_hash"]=_identity(result)
    return result


def evaluate_encounter(request,ruleset=None,cancel=None):
    return _solve(request,ruleset,cancel,True)


def optimize_encounter(request,ruleset=None,cancel=None):
    return _solve(request,ruleset,cancel,False)


def replay_encounter(result,ruleset=None):
    if not isinstance(result,dict) or result.get("kind")!="encounter_result" or result.get("schema_version")!=1:
        raise ValueError("invalid encounter result")
    if _identity(result)!=result.get("result_hash"): raise ValueError("encounter result identity mismatch")
    ctx=freeze_encounter(result.get("frozen_request"),ruleset)
    if ctx["scenario"].get("physical"):
        from .physical_encounter import CORE, LAW_HASH
        receipt=result.get("physical_mechanics")
        if not isinstance(receipt,dict) or (receipt.get("profile"),receipt.get("law_sha256"))!=(CORE,LAW_HASH):
            raise ValueError("encounter physical law receipt mismatch")
    if ((result.get("input_hash"),result.get("source_sha"),result.get("ruleset_hash"))!=
            (_digest(ctx["raw"]),ctx["source_sha"],ctx["ruleset_hash"])):
        raise ValueError("encounter frozen input or source mismatch")
    rows=result.get("frontier")
    if not isinstance(rows,list) or result.get("blockers")!=ctx["blockers"] or (rows and ctx["blockers"]):
        raise ValueError("invalid encounter frontier")
    if result.get("winner")!=(rows[0] if rows else None) or result.get("exact")!=(result.get("termination")=="exhausted"):
        raise ValueError("invalid encounter winner or proof scope")
    if result.get("exact") and not rows: raise ValueError("missing exact encounter winner")
    for row in rows:
        if not isinstance(row,dict) or row!=_witness(ctx,row.get("policy_index")):
            raise ValueError("encounter trace or metric mismatch")
    return {"valid":True,"result_hash":result["result_hash"],"policies_checked":len(rows),
            "trials_checked":len(rows)*len(ctx["seeds"]),"ruleset_hash":ctx["ruleset_hash"]}
