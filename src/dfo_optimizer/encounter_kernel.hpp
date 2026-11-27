#pragma once
#include "encounter_effects.hpp"
#include "encounter_powers.hpp"
#include "physical_combat.hpp"
#include "spellbook.hpp"
#include <array>
#include <chrono>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace dfo_enc {
using Time = std::int64_t;
constexpr Time never = std::numeric_limits<Time>::max();

struct Foe {
    dfo_spell::Context defense;
    int hp=1, x_mm=0, z_mm=0, radius_mm=450, distance_mm=-1;
    int level=1,absorb_skill=0,sp=0,max_sp=0;
    Defenses wards;
    bool undead_daedra=false, kill_eligible=true, trapped=false;
};
struct Incoming { Time time_us=0; int source=0, damage=0, spell=-1; bool blow=true; };
struct Room {
    Time delay_us=0;
    int rest_hp=-1,rest_sp=-1,heal_spell=-1;
    std::vector<int> enemies;
    std::vector<Incoming> incoming;
};
// Explicitly observed opportunities. Safe rest occupies the interval ending
// at time_us. Its measured resource floors are absolute; potion gains are deltas.
struct Recovery { Time time_us=0,duration_us=0; int hp=0,sp=0; bool rest=false; };
struct Encounter {
    dfo_spell::Context caster;
    Defenses wards;
    int hp=1,max_hp=1,max_sp=0,path_id=0,martial_id=0,wellspring_pct=0;
    Time horizon_us=0,first_round_us=5000000,round_period_us=5000000;
    std::vector<Foe> enemies;
    std::vector<Incoming> incoming;
    std::vector<Room> rooms;
    std::vector<Recovery> recovery;
    std::vector<double> tape;
    std::vector<Fighter> fighters;
    bool backup=false;
    int enemy_reach_mm=0,fatigue=0;
};
struct Spell {
    int element=4,range_type=1,cost_sp=0,climb=-1;
    bool signature=false;
    std::vector<Effect> effects;
};
struct Rule { int spell=0,target=-1,hp_below_pct=-1,sp_below_pct=-1,shield_below=-1; };
struct Limits { std::uint64_t max_events=0,memory_bytes=64u<<20; double wall_seconds=0; bool trace=false,frontier=false,mark_incumbent=true; int objective=0; };
enum EventKind { click,release,impact,round_tick,incoming_hit,kill,death,miss,wait,restore,absorbed,reflected,resisted,room_open,
                 swing_start,swing_impact,swing_miss,enemy_impact,enemy_miss };
struct Event { Time time_us=0; int kind=0,target=-1,spell=-1,value=0,hp=0,sp=0,shield=0,target_hp=0; };
struct Trial {
    int initial_sp=0,casts=0,impacts=0,kills=0,end_hp=0,end_sp=0,min_hp=0,min_sp=0,consumables=0;
    std::int64_t spent_sp=0,restored_sp=0,damage=0,healing=0,mitigated=0,rest_us=0,end_us=0;
    bool dead=false,cleared=false;
    bool physical=false;
    int melee_swings=0,melee_hits=0,incoming_swings=0,incoming_hits=0,spent_fatigue=0,end_fatigue=0;
    int64_t melee_damage=0;
    std::uint64_t draws=0;
    std::vector<Event> trace;
};
struct EncounterScore {
    std::int64_t cleared=0,alive=0,kills=0,damage=0,spent=0,elapsed=0,censored=0;
};
struct PolicyResult {
    int policy_index=0;
    std::vector<Trial> trials;
    EncounterScore score;
    std::uint64_t payload_bytes=0;
};
struct Report {
    int end=0;
    std::uint64_t events=0,trials_completed=0,work_bytes=0,policies_completed=0;
    double first_native_seconds=-1;
    std::vector<PolicyResult> rows;
};
#include "encounter_frontier.hpp"

inline Spell from_bundle(const dfo_spell::Context& caster,const dfo_book::Bundle& bundle) {
    Spell result;
    result.element=bundle.element; result.range_type=bundle.range_type;
    dfo_book::SpellScore priced;
    dfo_book::price_bundle(caster,bundle,priced);
    result.cost_sp=priced.cost_sp;
    for (const auto& settings:bundle.effects) {
        Effect e{};
        e.type=settings.effect_kind==0 ? 4 : 5;
        e.subtype=settings.effect_kind==0 ? 0 : 255;
        e.base_low=settings.base_low; e.base_high=settings.base_high;
        e.plus_low=settings.plus_low; e.plus_high=settings.plus_high; e.per_level=settings.per_level;
        e.chance_base=settings.chance_base; e.chance_increment=settings.chance_increment;
        e.chance_per_level=settings.per_level;
        result.effects.push_back(e);
    }
    return result;
}

class Budget {
    const Limits& l;
    dfo_spell::Token& token;
    const dfo_spell::Clock::time_point begin=dfo_spell::Clock::now();
    std::uint64_t reserved=0;
public:
    Report data;
    Budget(const Limits& limits,dfo_spell::Token& flag):l(limits),token(flag){}
    bool check() {
        if (token.stopped.load(std::memory_order_relaxed)) data.end=4;
        else if (l.wall_seconds>0 && std::chrono::duration<double>(dfo_spell::Clock::now()-begin).count()>=l.wall_seconds) data.end=2;
        return data.end==0;
    }
    bool take() {
        if (!check()) return false;
        if (l.max_events && data.events>=l.max_events) { data.end=1; return false; }
        ++data.events;
        return true;
    }
    bool reserve(std::uint64_t bytes) {
        if (bytes>l.memory_bytes-reserved) { data.end=3; return false; }
        reserved+=bytes;
        data.work_bytes=std::max(data.work_bytes,reserved);
        return true;
    }
    void release_bytes(std::uint64_t bytes) { reserved-=bytes; }
    template<class T> bool grow(std::vector<T>& values,std::size_t capacity) {
        const auto old_bytes=values.capacity()*sizeof(T);
        // Reallocation briefly owns the old AND new buffers.
        if (!reserve(capacity*sizeof(T))) return false;
        values.reserve(capacity);
        release_bytes(old_bytes);
        return true;
    }
    double elapsed() const {return std::chrono::duration<double>(dfo_spell::Clock::now()-begin).count();}
};
struct Flight { Time when=never; int spell=-1,target=-1,cast=0,paid=0; bool launched=false; };
struct Regen { int spell=-1,slot=-1,rounds=-1; };

class Run {
    const Encounter& scene;
    const std::vector<Spell>& spells;
    const std::vector<Rule>& policy;
    Budget& budget;
    const bool traced;
    Draws rng;
    PathState path{};
    Trial out;
    std::vector<int> foes;
    std::vector<int> foe_sp,silence;
    std::vector<Flight> flights;
    std::vector<Regen> regens;
    std::vector<Fighter> fighters;
    Time swing_at=never;
    int swing_target=-1;
    int hp,sp,shield=0,shield_max=0,shield_rounds=-1;
    int survivors,room_alive=0,last_cast_cost=0;
    bool power_shield=false;
    Time now=0,decision=0,next_round,cast_ready=0,open_at=never,entered_at=0;
    size_t room_index=0;
    size_t incoming_i=0,recovery_i=0,next_rest=0;

    void note(int kind,int target=-1,int spell=-1,int value=0) {
        out.min_hp=std::min(out.min_hp,hp);
        out.min_sp=std::min(out.min_sp,sp);
        if (!traced || budget.data.end) return;
        if (out.trace.size()==out.trace.capacity()) {
            auto next=std::max<size_t>(8,2*out.trace.capacity());
            if (!budget.grow(out.trace,next)) return;
        }
        out.trace.push_back({now,kind,target,spell,value,hp,sp,shield,target<0 ? hp : foes[target]});
    }
    int first_alive() const {
        auto p=std::find_if(foes.begin(),foes.end(),[](int v){return v>0;});
        return p==foes.end() ? -1 : int(p-foes.begin());
    }
    double distance(int t,int origin=-1) const {
        const auto& a=scene.enemies[t];
        return std::hypot(double(a.x_mm)-(origin<0 ? 0 : scene.enemies[origin].x_mm),
                          double(a.z_mm)-(origin<0 ? 0 : scene.enemies[origin].z_mm));
    }
    double target_distance(int t) const {
        return scene.enemies[t].distance_mm>=0 ? scene.enemies[t].distance_mm : distance(t);
    }
    dfo_spell::Context context(int target,int spell,int origin=-1) const {
        auto c=target<0 ? scene.caster : scene.enemies[target].defense;
        c.level=origin<0 ? scene.caster.level : scene.enemies[origin].level;
        c.climb=spells[spell].climb<0 ? scene.caster.climb : spells[spell].climb;
        c.power_pct=scene.caster.power_pct;
        c.pierce=scene.caster.pierce;
        if (origin<0 && target>=0) {
            c.power_pct+=path_damage(path,now/1000.,hp,scene.max_hp,shield,scene.enemies[target].undead_daedra,false);
            c.pierce+=path_pierce(path.id,false);
        } else if (origin>=0 || spells[spell].range_type!=0) {
            // spellPowerMult and spellPierce only empower my hit at an NPC.
            c.climb=0;
            c.power_pct=0;
            c.pierce=0;
        }
        return c;
    }
    void gains(int old_hp,int old_sp) {
        out.healing+=std::max(0,hp-old_hp);
        out.restored_sp+=std::max(0,sp-old_sp);
    }
    void hurt(int amount,bool blow) {
        if (amount<=0) return;
        int before=hp;
        if (blow) {
            if (path_evades(path.id,rng) || martial_evades(path,rng)) {out.mitigated+=amount;return;}
            const int after=martial_guard(path,amount);
            out.mitigated+=amount-after;
            amount=after;
        }
        const int soak=std::min(amount,shield);
        shield-=soak; amount-=soak;
        if (soak && !shield) {shield_rounds=-1;shield_max=0;}
        out.mitigated+=soak;
        if (blow && hp==scene.max_hp && amount>=hp) {
            out.mitigated+=amount-(hp-1); hp=1;
        } else hp=std::max(0,hp-amount);
        out.min_hp=std::min(out.min_hp,hp);
        if (hp>0 && hp<before) {
            int wounded=hp;
            path_hurt(path,now/1000.,before,hp,scene.max_hp);
            gains(wounded,sp);
        }
    }
    bool same_regen(const Effect& a,const Effect& b) const {
        return std::tie(a.base_low,a.base_high,a.plus_low,a.plus_high,a.per_level,
                        a.duration_base,a.duration_increment,a.duration_per_level)
            ==std::tie(b.base_low,b.base_high,b.plus_low,b.plus_high,b.per_level,
                       b.duration_base,b.duration_increment,b.duration_per_level);
    }
    void raise_shield(int amount,int rounds,bool from_power=false) {
        if (amount<=0 || rounds<=0) return;
        if (!shield) {
            shield=shield_max=amount;
            shield_rounds=rounds-1;
            power_shield=from_power;
            return;
        }
        if (from_power || power_shield) shield_max=std::max(shield_max,amount);
        shield+=std::min(shield_max-shield,amount);
        shield_rounds=std::max(shield_rounds,rounds-1);
    }
    void self_effect(int spell,int slot) {
        const auto& s=spells[spell]; const auto& e=s.effects[slot];
        auto existing=regens.end();
        if (e.type==18) existing=std::find_if(regens.begin(),regens.end(),[&](const Regen& r){
            return same_regen(e,spells[r.spell].effects[r.slot]);
        });
        const bool act=existing==regens.end() || existing->rounds<=0;
        auto ctx=context(-1,spell);
        if (e.climb>=0) ctx.climb=e.climb;
        auto effect=apply_effect(e,ctx,s.element,hp,scene.max_hp,rng,true,act);
        const int before=hp;
        hp+=std::min(scene.max_hp-hp,effect.healing);
        gains(before,sp);
        raise_shield(effect.shield,effect.rounds);
        if (e.type==18 && effect.rounds>0) {
            if (existing==regens.end()) regens.push_back({spell,slot,effect.rounds-1});
            else existing->rounds=std::max(existing->rounds,effect.rounds-1);
        }
    }
    // The target's three defenses run before each slot. Reflection skips one
    // slot and queues one whole-bundle return after the original landing.
    void landed(int t,const Flight& f,int origin=-1,bool return_trip=false) {
        const auto& s=spells[f.spell];
        int before=t<0 ? hp : foes[t];
        const auto& wards=t<0 ? scene.wards : scene.enemies[t].wards;
        const int receiver_skill=t<0 ? scene.caster.live_skill : scene.enemies[t].absorb_skill;
        const int room=t<0 ? scene.max_sp-sp : scene.enemies[t].max_sp-foe_sp[t];
        const bool same=t==origin;
        bool bounce=false;
        int drinks=0;
        const auto base=context(t,f.spell,origin);
        for (size_t j=0;j<s.effects.size();++j) {
            const auto& effect=s.effects[j];
            const int drink=try_absorb(wards,effect,s.range_type,receiver_skill,room,same?f.paid:0,rng);
            if (drink) {drinks+=drink;note(absorbed,t,f.spell,drink);continue;}
            if (!same && !return_trip && !bounce && reflects(wards,rng)) {
                bounce=true;note(reflected,t,f.spell,static_cast<int>(j));continue;
            }
            if (s.range_type && resists(wards,rng)) {
                note(resisted,t,f.spell,static_cast<int>(j));continue;
            }
            auto ctx=base;
            if (effect.climb>=0 && origin<0 && t>=0) ctx.climb=effect.climb;
            if (effect.type==19) {
                silence[t+1]=silence_rounds(effect,ctx,s.element,silence[t+1],rng);
            } else if (s.range_type==0) {
                self_effect(f.spell,static_cast<int>(j));
            } else {
                const auto v=apply_effect(effect,ctx,s.element,t<0?hp:foes[t],t<0?scene.max_hp:scene.enemies[t].hp,rng);
                if (t<0) hurt(v.damage,false);
                else foes[t]-=std::min(foes[t],v.damage);
            }
        }
        if (drinks) {
            const int refund=absorb_refund(drinks,t<0 && same ? last_cast_cost : 0);
            if (t<0) {const int old=sp;sp+=std::min(scene.max_sp-sp,refund);gains(hp,old);}
            else foe_sp[t]+=std::min(scene.enemies[t].max_sp-foe_sp[t],refund);
        }
        const int took=before-(t<0 ? hp : foes[t]);
        ++out.impacts;
        if (t>=0) out.damage+=took;
        note(impact,t,f.spell,took);
        if (t>=0 && before>0 && !foes[t]) {
            // Dungeon reflected missiles use the original foeSinks wrapper.
            // Its default fromPlayer=true credits the kill; this is not a
            // player-cast landing and cannot trigger a signature rider below.
            const bool credited=scene.enemies[t].kill_eligible && (origin<0 || return_trip);
            finish_kill(t,f.spell,credited);
        }
        if (origin<0 && t>=0 && took>0) {
            path_landed(path,now/1000.,f.cast,took);
            if (s.signature) {
                int old_hp=hp,old_sp=sp;
                path_signature(path,took,f.paid,hp,scene.max_hp,sp,scene.max_sp);
                if (path.id==battlemage) raise_shield(aegis_bolt(took,scene.max_hp,rng),9,true);
                gains(old_hp,old_sp);
            }
        }
        if (bounce) landed(origin,f,origin,true);
    }
    void apply_flight(Flight f) {
        const int range=spells[f.spell].range_type;
        if (!f.launched) {
            note(release,f.target,f.spell);
            if (range!=0) last_cast_cost=f.paid;
            if (range==2 || range==4) {
                f.launched=true;
                const Time transit=static_cast<Time>(std::ceil(target_distance(f.target)*40.));
                f.when=now+std::min<Time>(transit,8000000);
                flights.push_back(f);
                return;
            }
        } else if (target_distance(f.target)>200000.) {note(miss,f.target,f.spell);return;}
        if (range==0) {landed(-1,f);last_cast_cost=f.paid;}
        else if (range==3 || range==4) {
            const int origin=range==3 ? -1 : f.target;
            for (int t=0;t<int(foes.size());++t) {
                if (foes[t]>0 && distance(t,origin)<=4000+scene.enemies[t].radius_mm) landed(t,f);
            }
            if (range==4 && distance(origin)<=4350) landed(-1,f);
        } else if (foes[f.target]>0) landed(f.target,f);
        else note(miss,f.target,f.spell);
    }
    void magic_round() {
        for (auto& remaining:silence) if (remaining>=0) --remaining;
        if (shield_rounds==0) {shield=shield_max=0;shield_rounds=-1;}
        else if (shield_rounds>0) --shield_rounds;
        regens.erase(std::remove_if(regens.begin(),regens.end(),[](const Regen& r){return !r.rounds;}),regens.end());
        for (auto& r:regens) {
            const auto& s=spells[r.spell];
            auto ctx=context(-1,r.spell);
            if (s.effects[r.slot].climb>=0) ctx.climb=s.effects[r.slot].climb;
            auto v=apply_effect(s.effects[r.slot],ctx,s.element,hp,scene.max_hp,rng,true);
            const int healed=std::min(scene.max_hp-hp,v.healing);
            hp+=healed;out.healing+=healed;--r.rounds;
        }
        const int old=hp;
        path_round(path,shield,hp,scene.max_hp);
        gains(old,sp);note(round_tick);
        next_round+=scene.round_period_us;
    }
    void recover(const Recovery& r) {
        int old_hp=hp,old_sp=sp;
        if (r.rest) {
            hp=std::min(scene.max_hp,std::max(hp,r.hp));sp=std::min(scene.max_sp,std::max(sp,r.sp));
            out.rest_us+=r.duration_us;
        } else {
            hp+=std::min(scene.max_hp-hp,r.hp); sp+=std::min(scene.max_sp-sp,r.sp);
            ++out.consumables;
        }
        gains(old_hp,old_sp); note(restore,-1,-1,sp-old_sp);
    }
    void find_next_rest() {
        while (next_rest<scene.recovery.size() && !scene.recovery[next_rest].rest) ++next_rest;
    }
    bool overlaps_rest(Time finish) const {
        if (next_rest==scene.recovery.size()) return false;
        const auto& rest=scene.recovery[next_rest];
        return now<rest.time_us && rest.time_us-rest.duration_us<=finish;
    }
    void finish_kill(int t,int spell,bool credited) {
        --survivors;--room_alive;++out.kills;
        const int old_hp=hp,old_sp=sp;
        path_kill(path,credited,scene.enemies[t].trapped,hp,scene.max_hp,sp,scene.max_sp);
        gear_kill(path,scene.wellspring_pct,credited,sp,scene.max_sp);
        gains(old_hp,old_sp);note(kill,t,spell);
    }
    void strike(int t,bool outgoing) {
        if (outgoing) {out.end_fatigue-=8;out.spent_fatigue+=8;}
        if (!foes[t]) return;
        if (!outgoing) ++out.incoming_swings;
        if (target_distance(t)>(outgoing?2500:scene.enemy_reach_mm)) {
            note(outgoing?swing_miss:enemy_miss,t);
            return;
        }
        auto& foe=fighters[t+1];auto& actor=fighters[0];
        const auto blow=outgoing?physical_blow(actor,foe,true,hp,scene.max_hp,foes[t],scene.enemies[t].hp,rng)
                         :physical_blow(foe,actor,false,foes[t],scene.enemies[t].hp,hp,scene.max_hp,rng);
        if (outgoing) {
            out.melee_hits+=blow.hit;
            const int loss=std::min(foes[t],blow.damage);
            foes[t]-=loss;out.damage+=loss;out.melee_damage+=loss;
            note(blow.hit?swing_impact:swing_miss,t,blow.part,loss);
            if (!foes[t]) finish_kill(t,-1,scene.enemies[t].kill_eligible);
        } else {
            out.incoming_hits+=blow.hit;
            const int before=hp;
            if (blow.damage>0) hurt(blow.damage,true);
            note(blow.hit?enemy_impact:enemy_miss,t,blow.part,before-hp);
        }
    }
    void start_cast(int index,int target,Time release_at,Time ready_at) {
        const int cost=spells[index].cost_sp;
        sp-=cost; out.spent_sp+=cost; ++out.casts;
        flights.push_back({release_at,index,target,out.casts,cost,false});
        note(click,target,index,cost);
        cast_ready=ready_at;
    }
    void decide() {
        decision=never;
        if (open_at!=never) {
            const int heal=scene.rooms[room_index+1].heal_spell;
            if (heal<0 || hp==scene.max_hp || spells[heal].cost_sp>sp || (silence[0]>=0 && spells[heal].cost_sp)) return;
            auto c=scene.caster;c.cast_speed_pct+=path_speed(path.id);
            const double rate=dfo_spell::rate(c);
            const Time release_at=now+static_cast<Time>(std::ceil(200000./rate));
            if (release_at<open_at) start_cast(heal,-1,release_at,now+static_cast<Time>(std::ceil(700000./rate)));
            return;
        }
        if (!overlaps_rest(now)) for (const Rule& rule:policy) {
            const Spell& s=spells[rule.spell];
            if (rule.hp_below_pct>=0 && Time(hp)*100>=Time(scene.max_hp)*rule.hp_below_pct) continue;
            if (rule.sp_below_pct>=0 && Time(sp)*100>=Time(scene.max_sp)*rule.sp_below_pct) continue;
            if (rule.shield_below>=0 && shield>=rule.shield_below) continue;
            int target=rule.target<0 ? first_alive() : rule.target;
            if (s.range_type==0) target=-1;
            else if (target<0 || !foes[target]) continue;
            if (s.range_type==1 && target_distance(target)>3250+scene.enemies[target].radius_mm) continue;
            if (s.cost_sp>sp) continue;
            if (silence[0]>=0 && s.cost_sp>0) continue;
            auto c=scene.caster;c.cast_speed_pct+=path_speed(path.id);
            const double rate=dfo_spell::rate(c);
            const Time release_at=now+static_cast<Time>(std::ceil(200000./rate));
            const Time ready_at=now+static_cast<Time>(std::ceil(700000./rate));
            Time finish=ready_at;
            if (s.range_type==2 || s.range_type==4) {
                const auto flight_us=static_cast<Time>(std::ceil(target_distance(target)*40.));
                finish=std::max(finish,release_at+std::min<Time>(8000000,flight_us));
            }
            if (overlaps_rest(finish)) continue;
            start_cast(rule.spell,target,release_at,ready_at);
            decision=cast_ready;
            return;
        }
        if (scene.backup && out.end_fatigue>8) {
            const auto& move=fighters[0].move();
            for (int t=0;t<int(foes.size());++t) if (foes[t] && target_distance(t)<=2500 && !overlaps_rest(now+move.ready_us)) {
                swing_target=t;swing_at=now+move.impact_us;
                decision=cast_ready=now+move.ready_us;
                ++out.melee_swings;note(swing_start,t,-1,move.ready_us);return;
            }
        }
        note(wait);
    }
    void wake() { if (decision==never && room_alive>0) decision=std::max(now,cast_ready); }
    void enter_room(size_t index) {
        const auto& room=scene.rooms[index];
        room_index=index;
        entered_at=now;
        incoming_i=0;
        open_at=never;
        room_alive=static_cast<int>(room.enemies.size());
        for (int index:room.enemies) foes[index]=scene.enemies[index].hp;
        if (room.rest_sp>=0) {
            const int before_hp=hp,before_sp=sp;
            hp=std::max(hp,room.rest_hp);
            sp=std::max(sp,room.rest_sp);
            gains(before_hp,before_sp);
            out.rest_us+=room.delay_us;
        }
        if (index>0) note(room_open,-1,-1,static_cast<int>(index));
        decision=std::max(now,cast_ready);
    }
    void leave_if_cleared() {
        if (room_alive || !survivors || open_at!=never || scene.rooms.empty()) return;
        // Scene transition retires missiles and the old room's future attacks.
        flights.clear();
        swing_at=never;
        incoming_i=scene.rooms[room_index].incoming.size();
        decision=never;
        open_at=now+scene.rooms[room_index+1].delay_us;
        if (scene.rooms[room_index+1].heal_spell>=0 && std::max(now,cast_ready)<open_at)
            decision=std::max(now,cast_ready);
    }
public:
    Run(const Encounter& e,const std::vector<Spell>& s,const std::vector<Rule>& p,
        std::uint32_t seed,bool trace,Budget& b):scene(e),spells(s),policy(p),budget(b),traced(trace),
        hp(e.hp),sp(e.caster.available_sp),survivors(static_cast<int>(e.enemies.size())),next_round(e.first_round_us) {
        rng.state=seed?seed:0x6d2b79f5; rng.borrowed=&e.tape;
        fighters=e.fighters;out.physical=!fighters.empty();out.end_fatigue=e.fatigue;
        path.id=e.path_id;
        path.martial_id=e.martial_id;
        for (const auto& foe:e.enemies) {foes.push_back(e.rooms.empty()?foe.hp:0);foe_sp.push_back(foe.sp);}
        silence.assign(e.enemies.size()+1,-1);
        find_next_rest();
        out.initial_sp=out.min_sp=sp; out.min_hp=hp;
        if (e.rooms.empty()) room_alive=survivors;
        else enter_room(0);
    }
    Trial play() {
        while (hp>0 && survivors>0 && !budget.data.end) {
            const auto& attacks=scene.rooms.empty()?scene.incoming:scene.rooms[room_index].incoming;
            const Time incoming=incoming_i<attacks.size() ? entered_at+attacks[incoming_i].time_us : never;
            const Time recovery=recovery_i<scene.recovery.size() ? scene.recovery[recovery_i].time_us : never;
            auto flight=std::min_element(flights.begin(),flights.end(),[](const Flight& a,const Flight& b){
                return std::tie(a.when,a.cast)<std::tie(b.when,b.cast);
            });
            const Time flight_time=flight==flights.end() ? never : flight->when;
            now=std::min({open_at,incoming,recovery,next_round,flight_time,swing_at,decision});
            if (now>scene.horizon_us) {now=scene.horizon_us;break;}
            if (!budget.take()) break;
            if (now==open_at) enter_room(room_index+1);
            else if (now==incoming) {
                const auto& hit=attacks[incoming_i++];
                if (foes[hit.source]>0) {
                    const int old=hp;
                    if (hit.spell==-2) strike(hit.source,false);
                    else if (hit.spell<0) hurt(hit.damage,hit.blow);
                    else landed(-1,Flight{now,hit.spell,-1,0,0,true},hit.source);
                    if (hit.spell!=-2) note(incoming_hit,hit.source,hit.spell,old-hp);
                }
                wake();
            } else if (now==recovery) {
                recover(scene.recovery[recovery_i++]);
                if (next_rest<recovery_i) {next_rest=recovery_i;find_next_rest();}
                wake();
            }
            else if (now==next_round) {magic_round();wake();}
            else if (now==flight_time) {Flight f=*flight; flights.erase(flight);apply_flight(f);wake();}
            else if (now==swing_at) {swing_at=never;strike(swing_target,true);wake();}
            else decide();
            leave_if_cleared();
        }
        if (!hp) note(death);
        out.dead=hp==0;out.cleared=survivors==0;out.end_us=now;
        out.end_hp=hp;out.end_sp=sp;out.draws=rng.cursor;
        return std::move(out);
    }
};

inline Report evaluate(const Encounter& e,const std::vector<Spell>& spells,const std::vector<std::vector<Rule>>& policies,
                       const std::vector<std::uint32_t>& seeds,const Limits& limits,dfo_spell::Token& token) {
    Budget budget(limits,token);
    if (!budget.check()) return std::move(budget.data);
    // Include all packed, read-only data retained during the loop, including
    // the borrowed replay tape. The Python request and output are outside it.
    std::uint64_t packed=sizeof(Encounter)+e.enemies.capacity()*sizeof(Foe)+e.rooms.capacity()*sizeof(Room)
        +e.incoming.capacity()*sizeof(Incoming)+e.recovery.capacity()*sizeof(Recovery)+e.tape.capacity()*sizeof(double)
        +seeds.capacity()*sizeof(std::uint32_t)+spells.capacity()*sizeof(Spell)+policies.capacity()*sizeof(std::vector<Rule>)
        +e.wards.set_absorb_chances.capacity()*sizeof(int)+e.fighters.capacity()*sizeof(Fighter);
    for (const auto& foe:e.enemies) packed+=foe.wards.set_absorb_chances.capacity()*sizeof(int);
    for (const auto& room:e.rooms) packed+=room.incoming.capacity()*sizeof(Incoming)+room.enemies.capacity()*sizeof(int);
    for (const auto& spell:spells) packed+=spell.effects.capacity()*sizeof(Effect);
    for (const auto& policy:policies) packed+=policy.capacity()*sizeof(Rule);
    const auto workspace=sizeof(Run)+(e.enemies.size()+1)*sizeof(int)*6
        +sizeof(Flight)*64+spells.size()*3*sizeof(Regen)*4+e.fighters.size()*sizeof(Fighter);
    if (!budget.reserve(packed+workspace)) return std::move(budget.data);
    auto check_attacks=[&spells](const std::vector<Incoming>& attacks) {
        for (const auto& hit:attacks) {
            if (hit.spell<0) continue;
            if (size_t(hit.spell)>=spells.size()) throw std::invalid_argument("Incoming spell index outside admitted catalog");
            if (spells[hit.spell].range_type!=1 && spells[hit.spell].range_type!=2)
                throw std::invalid_argument("Observed incoming bundle must be a single-target landing");
        }
    };
    check_attacks(e.incoming);
    for (const auto& room:e.rooms) {
        check_attacks(room.incoming);
        if (room.heal_spell<0) continue;
        if (size_t(room.heal_spell)>=spells.size() || spells[room.heal_spell].range_type!=0 ||
            !std::all_of(spells[room.heal_spell].effects.begin(),spells[room.heal_spell].effects.end(),
                         [](const Effect& effect){return effect.type==10 && effect.subtype==8;}))
            throw std::invalid_argument("Unsupported protected room heal");
    }
    for (size_t i=0;i<policies.size() && budget.check();++i) {
        PolicyResult row;row.policy_index=static_cast<int>(i);
        row.payload_bytes=seeds.size()*sizeof(Trial);
        if (!budget.reserve(row.payload_bytes)) break;
        row.trials.reserve(seeds.size());
        for (size_t n=0;n<seeds.size();++n) {
            auto t=Run(e,spells,policies[i],seeds[n],limits.trace && n==0,budget).play();
            if (budget.data.end) break;
            add_trial(row.score,t,e.horizon_us);
            row.payload_bytes+=t.trace.capacity()*sizeof(Event);
            row.trials.push_back(std::move(t));++budget.data.trials_completed;
        }
        if (row.trials.size()==seeds.size()) {
            if (!budget.check() || !retain_policy(budget.data.rows,std::move(row),limits,budget)) break;
            ++budget.data.policies_completed;
            if (budget.data.first_native_seconds<0) budget.data.first_native_seconds=budget.elapsed();
            if (limits.mark_incumbent) token.incumbent.store(true,std::memory_order_relaxed);
        }
    }
    return std::move(budget.data);
}
} // namespace dfo_enc
