"""Resolve observed, horizon-stable defensive channels before the native event loop."""
from .spell_request import _int, _object


def freeze_wards(raw,horizon,blockers):
    if raw is None: return {}
    _object(raw,"wards",("absorb_chance","reflect_chance","resist_chance","career_absorbs","enchant_absorbs",
                         "set_absorb_chances","active_through_us","evidence"))
    fields={}
    for k,cap in (("absorb_chance",50),("reflect_chance",100),("resist_chance",100)):
        fields[k]=_int(raw.get(k,0),k,0,cap)
    for k in ("career_absorbs","enchant_absorbs"):
        v=raw.get(k,False)
        if type(v) is not bool: raise ValueError(f"{k} requires a boolean")
        fields[k]=v
    sets=raw.get("set_absorb_chances",[])
    if not isinstance(sets,list) or len(sets)>32: raise ValueError("invalid set absorption chances")
    fields["set_absorb_chances"]=[_int(c,"set absorption",1,100) for c in sets]
    if any(fields.values()):
        evidence=raw.get("evidence")
        if not isinstance(evidence,str) or not evidence.strip() or len(evidence)>2048:
            blockers.append("missing active ward and environment evidence")
        if _int(raw.get("active_through_us",0),"active_through_us",0,86_400_000_000)<horizon:
            blockers.append("ward lifetime or environmental condition is unverified through the encounter")
    return fields


def absorb_active(wards):
    return any(wards.get(k) for k in ("absorb_chance","enchant_absorbs","career_absorbs","set_absorb_chances"))
