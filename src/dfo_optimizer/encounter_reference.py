"""Single-witness encounter replay with an independent chronological event queue."""
from heapq import heapify, heappop, heappush
from copy import deepcopy
from math import ceil, hypot

from . import encounter_advanced_reference as powers
from .spell_reference import _round_js, _save


class Draws:
    def __init__(self,seed,tape):
        self.state=seed or 0x6d2b79f5
        self.tape=tape
        self.cursor=0

    def next(self):
        self.cursor+=1
        if self.tape:
            if self.cursor>len(self.tape):
                raise ValueError("Encounter random tape exhausted")
            return self.tape[self.cursor-1]
        x=self.state
        x^=(x<<13)&0xffffffff
        x^=x>>17
        x^=(x<<5)&0xffffffff
        self.state=x
        return x/2**32

    def between(self,a,b):
        return a+int(self.next()*(1+b-a))


def _amount(e,level,rng):
    return (rng.between(e["base_low"],e["base_high"])+
            rng.between(e["plus_low"],e["plus_high"])*(level//e["per_level"]))


def _save_pct(c,element,rng):
    ward=min(100,c["elemental_resists"][element])
    if ward and rng.between(0,99)<ward:
        return 0
    chance,immune=_save(c,element)
    if immune: return 0
    return max(0,100-5*max(0,chance-rng.between(1,100)))


def _damage(e,c,el,hp,rng):
    if e["type"]==5:
        chance=e["chance_base"]+e["chance_increment"]*(c["level"]//e["chance_per_level"])
        return hp if rng.between(1,100)<=chance and _save_pct({**c,"pierce":0},el,rng)>0 else 0
    amount=_amount(e,c["level"],rng)*_save_pct(c,el,rng)//100
    mult=(1+max(0,c["climb"]-100)/100)*max(.5,1+c["power_pct"]/100)
    return max(1,_round_js(amount*mult)) if amount else 0


_DEFENSE={"willpower":0,"resistant":0,"immune":0,"low_tolerance":0,"critical_weakness":0,
          "resist_mods":(0,)*5,"elemental_resists":(0,)*5}


class _Replay:
    def __init__(self,scene,spells,policy,seed,trace,max_trace_events=None):
        self.s,self.spells,self.policy=scene,spells,policy
        self.c=scene["caster"]
        self.rng=Draws(seed,scene.get("tape",()))
        self.path=powers.PathState(scene.get("path_id",0),martial_id=scene.get("martial_id",0))
        self.hp,self.sp=scene["hp"],self.c["available_sp"]
        self.enemies=scene["enemies"]
        self.hps=[e["hp"] for e in self.enemies]
        self.foe_sp=[e.get("sp",0) for e in self.enemies]
        self.wards=[powers.Defenses(**scene.get("wards",{}))]+[powers.Defenses(**e.get("wards",{})) for e in self.enemies]
        self.silence=[-1]*(1+len(self.hps))
        self.last_cost=0
        self.power_shield=False
        self.shield=self.shield_max=0
        self.shield_life=-1
        self.regens={}
        self.queue=[]
        self.now=0
        self.decision_at=None
        self.ready_at=0
        self.rooms=scene.get("rooms") or [{"enemies":list(range(len(self.hps))),"delay_us":0}]
        self.room=0
        self.between_rooms=False
        self.active=set(self.rooms[0]["enemies"])
        self.trace=trace
        self.max_trace_events=max_trace_events
        self.out=dict(initial_sp=self.sp,spent_sp=0,restored_sp=0,damage=0,kills=0,
            casts=0,impacts=0,min_hp=self.hp,min_sp=self.sp,healing=0,mitigated=0,consumables=0,rest_us=0,trace=[])
        self.fighters=deepcopy(scene.get("physical",{}).get("actors",[]))
        if self.fighters:
            self.out.update(melee_damage=0,melee_swings=0,melee_hits=0,incoming_swings=0,incoming_hits=0,
                            spent_fatigue=0,end_fatigue=scene["physical"]["fatigue"])
        self.room_attacks()
        for i,item in enumerate(scene.get("recovery",())):
            self.schedule(item["time_us"],1,i,"restore",item)
        self.schedule(scene["first_round_us"],2,0,"round",None)
        self.wake()

    def schedule(self,when,priority,serial,kind,data):
        heappush(self.queue,(when,priority,serial,kind,data))

    def room_attacks(self):
        for i,hit in enumerate(self.s["incoming"]):
            if hit["source"] in self.active:
                self.schedule(self.now+hit["time_us"],0,i,"incoming",hit)

    def clear_room(self):
        if self.between_rooms or self.room+1==len(self.rooms) or any(self.hps[t] for t in self.active):
            return
        self.between_rooms=True
        self.active=set()
        self.queue=[e for e in self.queue if e[3] not in ("decision","release","arrive","incoming","melee")]
        heapify(self.queue)
        self.decision_at=None
        self.room+=1
        opens=self.now+self.rooms[self.room]["delay_us"]
        self.schedule(opens,-1,0,"room",None)
        heal=self.rooms[self.room].get("heal_spell")
        if heal is not None and max(self.now,self.ready_at)<opens:
            self.schedule(max(self.now,self.ready_at),4,0,"protected_heal",(heal,opens))

    def open_room(self):
        room=self.rooms[self.room]
        self.active=set(room["enemies"])
        self.between_rooms=False
        if "rest_hp" in room:
            before=self.hp,self.sp
            self.hp=max(self.hp,room["rest_hp"])
            self.sp=max(self.sp,room["rest_sp"])
            self.gains(*before)
            self.out["rest_us"]+=room["delay_us"]
        self.note("room",value=self.room)
        self.room_attacks()

    def wake(self):
        if self.decision_at is None and not self.between_rooms:
            self.decision_at=max(self.now,self.ready_at)
            self.schedule(self.decision_at,4,0,"decision",None)

    def protected_heal(self,index,opens):
        cost=self.spells[index]["cost_sp"]
        if self.hp>=self.s["max_hp"] or cost>self.sp or (cost and self.silence[0]>=0):
            return
        rate=min(2,max(.5,1+(self.c["speed"]-50)/200+(self.c["cast_speed_pct"]+powers.path_speed(self.path.id))/100))
        release=self.now+ceil(200000/rate)
        if release>=opens:
            return
        self.ready_at=self.now+ceil(700000/rate)
        self.sp-=cost
        self.out["spent_sp"]+=cost
        self.out["casts"]+=1
        self.schedule(release,3,self.out["casts"],"release",(index,-1,self.out["casts"],cost))
        self.note("click",-1,index,cost)

    def note(self,kind,t=-1,i=-1,value=0):
        self.out["min_hp"]=min(self.out["min_hp"],self.hp)
        self.out["min_sp"]=min(self.out["min_sp"],self.sp)
        if self.trace:
            if self.max_trace_events is not None and len(self.out["trace"]) >= self.max_trace_events:
                raise MemoryError("Encounter replay exceeds its trace allowance")
            self.out["trace"].append([self.now,kind,t,i,value,self.hp,self.sp,self.shield,
                                      self.hp if t<0 else self.hps[t]])

    def gains(self,old_hp,old_sp):
        self.out["healing"]+=max(0,self.hp-old_hp)
        self.out["restored_sp"]+=max(0,self.sp-old_sp)

    def distance(self,t,origin=None):
        a=self.enemies[t]
        x,z=(0,0) if origin is None else (self.enemies[origin]["x_mm"],self.enemies[origin]["z_mm"])
        return hypot(a["x_mm"]-x,a["z_mm"]-z)

    def flight_distance(self,t):
        return self.enemies[t].get("distance_mm",self.distance(t))

    def ctx(self,t,spell,origin=-1):
        enemy={} if t<0 else self.enemies[t]
        c={**_DEFENSE,**self.c,**enemy}
        c["level"]=self.c["level"] if origin<0 else self.enemies[origin]["level"]
        c["climb"]=spell.get("climb",self.c["climb"])
        if origin>=0 or t<0 and spell["range_type"]!=0:
            c.update(climb=0,pierce=0,power_pct=0)
        if t>=0 and origin<0:
            c["power_pct"]+=powers.path_damage(self.path,self.now/1000,self.hp,self.s["max_hp"],
                                              self.shield,enemy.get("undead_daedra",False),False)
            c["pierce"]+=powers.path_pierce(self.path.id,False)
        return c

    def hurt(self,damage,blow):
        if damage<=0: return
        if blow:
            if powers.path_evades(self.path.id,self.rng) or powers.martial_evades(self.path,self.rng):
                self.out["mitigated"]+=damage
                return
            guarded=powers.martial_guard(self.path,damage)
            self.out["mitigated"]+=damage-guarded
            damage=guarded
        before=self.hp
        absorbed=min(damage,self.shield)
        self.shield-=absorbed
        if absorbed and not self.shield:
            self.shield_max,self.shield_life=0,-1
        applied=damage-absorbed
        if blow and self.hp==self.s["max_hp"] and applied>=self.hp:
            self.out["mitigated"]+=applied-self.hp+1
            applied=self.hp-1
        self.out["mitigated"]+=absorbed
        self.hp=max(0,self.hp-applied)
        self.out["min_hp"]=min(self.out["min_hp"],self.hp)
        if 0<self.hp<before:
            wounded=self.hp
            self.hp=powers.path_hurt(self.path,self.now/1000,before,wounded,self.s["max_hp"])
            self.gains(wounded,self.sp)

    def decide(self):
        self.decision_at=None
        if any(r["kind"]=="rest" and r["time_us"]-r["duration_us"]<=self.now<r["time_us"]
               for r in self.s.get("recovery",())):
            self.note("wait")
            return
        first=next(i for i,v in enumerate(self.hps) if v and i in self.active)
        for rule in self.policy:
            i=rule["spell"]
            s=self.spells[i]
            t=rule.get("target",-1)
            t=first if t==-1 else t
            if (("hp_below_pct" in rule and 100*self.hp>=self.s["max_hp"]*rule["hp_below_pct"])
                    or ("sp_below_pct" in rule and 100*self.sp>=self.s["max_sp"]*rule["sp_below_pct"])
                    or self.shield>=rule.get("shield_below",2**62)): continue
            r=s["range_type"]
            if r and (not self.hps[t] or t not in self.active) or r==1 and self.flight_distance(t)>3250+self.enemies[t]["radius_mm"]:
                continue
            cost=s["cost_sp"]
            if cost>self.sp or cost and self.silence[0]>=0: continue
            t=t if r else -1
            rate=min(2,max(.5,1+(self.c["speed"]-50)/200+(self.c["cast_speed_pct"]+powers.path_speed(self.path.id))/100))
            release=self.now+ceil(200000/rate)
            ready=self.now+ceil(700000/rate)
            finish=max(ready,release+min(8000000,ceil(self.flight_distance(t)*40)) if r in (2,4) else ready)
            if any(rec["kind"]=="rest" and rec["time_us"]>self.now and rec["time_us"]-rec["duration_us"]<=finish
                   for rec in self.s.get("recovery",())):
                continue
            self.sp-=cost
            self.out["spent_sp"]+=cost
            self.out["casts"]+=1
            cast=self.out["casts"]
            self.schedule(release,3,cast,"release",(i,t,cast,cost))
            self.decision_at=ready
            self.ready_at=ready
            self.schedule(self.decision_at,4,0,"decision",None)
            self.note("click",t,i,cost)
            return
        if self.fighters and self.s["physical"]["fallback"] and self.out["end_fatigue"]>8:
            t=next((j for j in sorted(self.active) if self.hps[j] and self.flight_distance(j)<=2500),None)
            actor=self.fighters[0]
            move=actor["armed"] if actor["weapon"][2] else actor["bare"]
            impact,ready=(self.now+delta for delta in move[-2:])
            overlap=any(r["kind"]=="rest" and self.now<r["time_us"] and r["time_us"]-r["duration_us"]<=ready
                        for r in self.s.get("recovery",()))
            if t is not None and not overlap:
                self.out["melee_swings"]+=1
                self.schedule(impact,3,2**31,"melee",t)
                self.ready_at=self.decision_at=ready
                self.schedule(ready,4,0,"decision",None)
                self.note("melee_start",t,value=move[-1])
                return
        self.note("wait")

    def melee(self,t,outgoing):
        from .physical_reference import melee_blow
        if outgoing:
            self.out["spent_fatigue"]+=8
            self.out["end_fatigue"]-=8
        if not self.hps[t]: return
        if not outgoing: self.out["incoming_swings"]+=1
        prefix="melee" if outgoing else "enemy_melee"
        if self.flight_distance(t)>(2500 if outgoing else self.s["physical"]["enemy_reach_mm"]):
            self.note(prefix+"_miss",t)
            return
        player,enemy=self.fighters[0],self.fighters[t+1]
        sides=((player,self.hp,self.s["max_hp"]),(enemy,self.hps[t],self.enemies[t]["hp"]))
        (a,ah,am),(d,dh,dm)=sides if outgoing else reversed(sides)
        amount,hit,part=melee_blow(a,d,outgoing,ah,am,dh,dm,self.rng)
        self.out["melee_hits" if outgoing else "incoming_hits"]+=int(hit)
        if outgoing:
            loss=min(amount,self.hps[t])
            self.hps[t]-=loss
            self.out["damage"]+=loss
            self.out["melee_damage"]+=loss
        else:
            before=self.hp
            if amount>0: self.hurt(amount,True)
            loss=before-self.hp
        self.note(prefix+("_impact" if hit else "_miss"),t,part,loss)
        if outgoing and not self.hps[t]:
            self.finish_kill(t,-1,self.enemies[t].get("kill_eligible",True))

    def finish_kill(self,t,spell,credited):
        self.out["kills"]+=1
        pre=self.hp,self.sp
        self.hp,self.sp=powers.path_kill(self.path,credited,self.enemies[t].get("trapped",False),
                                         self.hp,self.s["max_hp"],self.sp,self.s["max_sp"])
        self.sp=powers.gear_kill(self.path,self.s.get("wellspring_pct",0),credited,self.sp,self.s["max_sp"])
        self.gains(*pre)
        self.note("kill",t,spell)

    def heal(self,e,spell):
        raw=_amount(e,self.c["level"],self.rng)
        climb=e.get("climb",spell.get("climb",self.c["climb"]))
        return max(1,_round_js(raw*(1+max(0,climb-100)*.01))) if raw else 0

    def raise_shield(self,amount,rounds,from_power=False):
        if not amount or rounds<=0: return
        if not self.shield:
            self.shield=self.shield_max=amount
            self.shield_life=rounds-1
            self.power_shield=from_power
        else:
            if self.power_shield or from_power: self.shield_max=max(self.shield_max,amount)
            self.shield=min(self.shield_max,self.shield+amount)
            self.shield_life=max(self.shield_life,rounds-1)

    def self_slot(self,i,j):
        spell=self.spells[i]
        e=spell["effects"][j]
        kind=e["type"]
        rounds=(e.get("duration_base",0)+e.get("duration_increment",0)*
                max(1,self.c["level"]//e.get("duration_per_level",1)))
        key=tuple(e.get(k) for k in ("base_low","base_high","plus_low","plus_high","per_level",
                                      "duration_base","duration_increment","duration_per_level"))
        incumbent=self.regens.get(key)
        if kind==35:
            self.raise_shield(self.heal(e,spell),rounds)
        else:
            if kind==10 or rounds>0 and (not incumbent or incumbent[2]<=0):
                old=self.hp
                self.hp=min(self.s["max_hp"],self.hp+self.heal(e,spell))
                self.gains(old,self.sp)
            if kind==18 and rounds>0:
                self.regens[key]=(i,j,rounds-1) if not incumbent else (*incumbent[:2],max(incumbent[2],rounds-1))

    def round(self):
        self.silence=[max(-1,n-1) for n in self.silence]
        if self.shield_life==0: self.shield=self.shield_max=0
        self.shield_life=max(-1,self.shield_life-1)
        for key,(i,j,n) in tuple(self.regens.items()):
            if n==0: del self.regens[key]
            else:
                self.regens[key]=(i,j,n-1)
                old=self.hp
                self.hp=min(self.s["max_hp"],self.hp+self.heal(self.spells[i]["effects"][j],self.spells[i]))
                self.gains(old,self.sp)
        old=self.hp
        self.hp=powers.path_round(self.path,self.shield,self.hp,self.s["max_hp"])
        self.gains(old,self.sp)
        self.note("round")
        self.schedule(self.now+self.s["round_period_us"],2,0,"round",None)

    def landed(self,t,f,origin=-1,returned=False):
        i,_,cast,paid=f
        s=self.spells[i]
        before=self.hp if t<0 else self.hps[t]
        base=self.ctx(t,s,origin)
        defense=self.wards[t+1]
        available=self.s["max_sp"]-self.sp if t<0 else self.enemies[t].get("max_sp",0)-self.foe_sp[t]
        learner=self.c["live_skill"] if t<0 else self.enemies[t].get("absorb_skill",0)
        absorbed=0
        bounce=False
        for j,e in enumerate(s["effects"]):
            drank=powers.try_absorb(defense,e,s["range_type"],learner,available,paid if t==origin else 0,self.rng)
            if drank:
                absorbed+=drank
                self.note("absorbed",t,i,drank)
                continue
            if t!=origin and not returned and not bounce and powers.reflects(defense,self.rng):
                bounce=True
                self.note("reflected",t,i,j)
                continue
            if s["range_type"] and powers.resists(defense,self.rng):
                self.note("resisted",t,i,j)
                continue
            c=dict(base)
            if origin<0 and t>=0: c["climb"]=e.get("climb",base["climb"])
            if e["type"]==19:
                self.silence[t+1]=powers.silence_rounds(e,c,s["element"],self.silence[t+1],self.rng)
            elif t<0 and not s["range_type"]: self.self_slot(i,j)
            else:
                damage=_damage(e,c,s["element"],self.hp if t<0 else self.hps[t],self.rng)
                if t<0: self.hurt(damage,False)
                else: self.hps[t]=max(0,self.hps[t]-damage)
        if absorbed:
            refund=powers.absorb_refund(absorbed,self.last_cost if t==origin==-1 else 0)
            if t<0:
                old=self.sp
                self.sp=min(self.s["max_sp"],self.sp+refund)
                self.gains(self.hp,old)
            else: self.foe_sp[t]=min(self.enemies[t]["max_sp"],self.foe_sp[t]+refund)
        took=before-(self.hp if t<0 else self.hps[t])
        self.out["impacts"]+=1
        if t>=0: self.out["damage"]+=took
        self.note("impact",t,i,took)
        if t>=0 and before and not self.hps[t]:
            enemy=self.enemies[t]
            credited=enemy.get("kill_eligible",True) and (origin<0 or returned)
            self.finish_kill(t,i,credited)
        if origin<0 and t>=0 and took>0:
            powers.path_landed(self.path,self.now/1000,cast,took)
            if s.get("signature"):
                pre=self.hp,self.sp
                self.hp,self.sp=powers.path_signature(self.path,took,paid,self.hp,self.s["max_hp"],self.sp,self.s["max_sp"])
                if self.path.id==powers.PATH_IDS["battlemage"]:
                    self.raise_shield(powers.aegis_bolt(took,self.s["max_hp"],self.rng),9,True)
                self.gains(*pre)
        if bounce: self.landed(origin,f,origin,True)

    def flight(self,kind,f):
        i,t,cast,_=f
        r=self.spells[i]["range_type"]
        if kind=="release":
            self.note("release",t,i)
            if r: self.last_cost=f[3]
            if r in (2,4):
                self.schedule(self.now+min(8000000,ceil(self.flight_distance(t)*40)),3,cast,"arrive",f)
                return
        elif self.flight_distance(t)>200000:
            self.note("miss",t,i)
            return
        if r==0:
            self.landed(-1,f)
            self.last_cost=f[3]
        elif r in (3,4):
            for j,row in enumerate(self.enemies):
                if j in self.active and self.hps[j] and self.distance(j,t if r==4 else None)<=4000+row["radius_mm"]:
                    self.landed(j,f)
            if r==4 and self.distance(t)<=4350: self.landed(-1,f)
        elif self.hps[t]: self.landed(t,f)
        else: self.note("miss",t,i)

    def recover(self,item):
        hp,sp=self.hp,self.sp
        if item["kind"]=="rest":
            self.hp=min(self.s["max_hp"],max(hp,item["hp"]))
            self.sp=min(self.s["max_sp"],max(sp,item["sp"]))
            self.out["rest_us"]+=item["duration_us"]
        else:
            self.hp=min(self.s["max_hp"],hp+item["hp"])
            self.sp=min(self.s["max_sp"],sp+item["sp"])
            self.out["consumables"]+=1
        self.gains(hp,sp)
        self.note("restore",value=self.sp-sp)

    def run(self,poll=None):
        processed=0
        while self.hp and any(self.hps):
            if poll is not None and processed%128==0: poll()
            processed+=1
            when,_,_,kind,data=heappop(self.queue)
            if when>self.s["horizon_us"]:
                self.now=self.s["horizon_us"]
                break
            self.now=when
            if kind=="decision":
                self.decide()
                continue
            if kind=="incoming":
                t=data["source"]
                if self.hps[t]:
                    before=self.hp
                    if data["kind"]=="melee": self.melee(t,False)
                    elif data["kind"]=="bundle": self.landed(-1,(data["spell"],-1,0,0),t)
                    else: self.hurt(data["damage"],data["kind"]=="blow")
                    if data["kind"]!="melee": self.note("incoming",t,data.get("spell",-1),before-self.hp)
            elif kind=="melee": self.melee(data,True)
            elif kind=="room": self.open_room()
            elif kind=="round": self.round()
            elif kind=="restore": self.recover(data)
            elif kind=="protected_heal": self.protected_heal(*data)
            else: self.flight(kind,data)
            self.clear_room()
            self.wake()
        if not self.hp: self.note("death")
        return {**self.out,"end_hp":self.hp,"end_sp":self.sp,"dead":not self.hp,"cleared":not any(self.hps),
                "end_us":self.now,"draws":self.rng.cursor}


def simulate_trial(scenario,spells,policy,seed,trace=False,poll=None,max_trace_events=None):
    return _Replay(scenario,spells,policy,seed,trace,max_trace_events).run(poll)
