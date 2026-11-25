"""Match reviewed path spell identities and all source settings, including ordered slots."""
def canonical_signature(catalog,index,element,range_type,slots):
    row=next((item for item in catalog if item["index"]==index),None)
    if not row or (element,range_type)!=(row["element"],row["range_type"]): return False
    mapping=dict(magnitudeBaseLow="base_low",magnitudeBaseHigh="base_high",magnitudeLevelBase="plus_low",
                 magnitudeLevelHigh="plus_high",magnitudePerLevel="per_level",durationBase="duration_base",
                 durationMod="duration_increment",durationPerLevel="duration_per_level",chanceBase="chance_base",
                 chanceMod="chance_increment",chancePerLevel="chance_per_level")
    expected=[{"type":s["type"],"subtype":s["subType"],**{mapping[k]:v for k,v in s["settings"].items()}}
              for s in row["slots"]]
    return expected==[{k:v for k,v in slot.items() if k!="climb"} for slot in slots]
