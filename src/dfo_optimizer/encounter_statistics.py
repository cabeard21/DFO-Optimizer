"""Uncertainty for sampled panels and an exact restricted single-cast calculation."""
from math import ceil, hypot, sqrt


def probability_intervals(trials,tape):
    if tape:
        return {"method":"fixed draw tape; no sampling interval","clear":None,"death":None}
    n=len(trials)
    z=1.959963984540054
    def wilson(count):
        p=count/n
        den=1+z*z/n
        middle=(p+z*z/(2*n))/den
        width=z*sqrt((p*(1-p)+z*z/(4*n))/n)/den
        return [0. if count==0 else middle-width,1. if count==n else middle+width]
    return {"method":"95% Wilson score under an independent-seed sampling assumption",
            "clear":wilson(sum(t["cleared"] for t in trials)),"death":wilson(sum(t["dead"] for t in trials))}


def single_cast_exact(scene,spells,policy):
    """Enumerate independent magnitude/save/ward draws only where one cast covers the whole fight."""
    if (scene.get("physical") or len(policy)!=1 or len(scene["enemies"])!=1 or scene["incoming"] or scene["recovery"]
            or scene["tape"] or scene.get("path_id") or scene.get("martial_id") or scene.get("wellspring_pct")):
        return None
    rule=policy[0]
    if set(rule)-{"target","spell"}: return None
    spell=spells[rule["spell"]]
    e=spell["effects"][0]
    c=scene["caster"]
    if (len(spell["effects"])!=1 or e["type"]!=4 or spell["range_type"] not in (1,2)
            or not spell["cost_sp"]<=c["available_sp"]<2*spell["cost_sp"]):
        return None
    foe=scene["enemies"][0]
    if any(foe.get("wards",{}).values()): return None
    dist=foe.get("distance_mm",hypot(foe["x_mm"],foe["z_mm"]))
    rate=min(2,max(.5,1+(c["speed"]-50)/200+c["cast_speed_pct"]/100))
    hit_time=ceil(200000/rate)+(ceil(dist*40) if spell["range_type"]==2 else 0)
    if (dist>200000 and spell["range_type"]==2 or dist>3250+foe["radius_mm"] and spell["range_type"]==1 or
            hit_time>scene["horizon_us"]):
        return {"outcomes":1,"lethal_outcomes":0,"clear_probability":0.,"expected_hostile_hp_loss":0.,
                "censored_mean_clear_us":scene["horizon_us"],"basis":"stationary single-cast geometry and horizon"}
    from .spell_reference import evaluate_reference
    recipe=(spell["element"],spell["range_type"],*(e[k] for k in ("base_low","base_high","plus_low","plus_high","per_level")))
    # Exact replay is restricted to small magnitude domains at a finalist.
    if (1+recipe[3]-recipe[2])*(1+recipe[5]-recipe[4])>1024: return None
    ctx={**c,**foe,"level":c["level"],"target_hp":foe["hp"],"price_factor":1.,"climb":spell["climb"]}
    metrics=evaluate_reference(ctx,recipe)
    probability=metrics["kill_probability"]
    return {"outcomes":metrics["outcomes"],"lethal_outcomes":metrics["kill_sum"],
            "clear_probability":probability,"expected_hostile_hp_loss":metrics["expected_health_loss"],
            "censored_mean_clear_us":hit_time*probability+(1-probability)*scene["horizon_us"],
            "basis":"full integer Damage Health magnitude, ward and save distribution"}
