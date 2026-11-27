#pragma once
#include "encounter_effects.hpp"
#include <array>
#include <cmath>

namespace dfo_enc {

// All integer divisions here are the source's truncation. PCAAO explicitly
// rounds its reduction/crit intermediates to float32 and its results to even.
struct MeleeMove { int skill, low, high, damage_mod, hit_mod, both, blunt, impact_us, ready_us; };
struct ArmorPiece {
    int condition=0, maximum=0, type=0, covers=0;
    std::array<int,8> rows{};
};
struct Fighter {
    std::array<int,8> stats{};
    int level=1, group=-1, index=-1, min_metal=-1, flags=0, adrenaline=0, dodge=0, crit=0;
    int weapon=-1, metal=-1, condition=0, maximum=0, repool=0;
    std::array<ArmorPiece,8> armor{};
    MeleeMove armed{}, bare{};
    const MeleeMove& move() const {return condition ? armed : bare;}
};
struct Blow { int damage=0; bool hit=false; int part=-1; };
inline int even(float value) {
    int low=static_cast<int>(std::floor(value)); float frac=value-low;
    return low+(frac>.5f || (frac==.5f && low%2!=0));
}
inline int reduced(const ArmorPiece& item,int damage,int channel,float natural) {
    if (!item.condition) return even(damage*(1.f-natural));
    const int pct=100*item.condition/item.maximum;
    const float wear=pct>=61?1.f:pct>=41?1.1f:pct>=16?1.2f:pct>=6?1.35f:1.5f;
    return even(damage*(std::min(item.rows[2*channel]/100.f*wear,item.rows[2*channel+1]/100.f)-natural));
}
inline int block_chance(const Fighter& target, const ArmorPiece& shield, bool covers) {
    constexpr int strong[4]={30,35,45,55}, weak[4]={20,10,5,-5};
    constexpr int keys[6]={3,6,0,4,2,7};
    constexpr float ratio[2][6]={{.3f,.2f,.2f,.1f,.1f,.1f},{.3f,.3f,.3f,.2f,.1f,.1f}};
    float value=(covers?strong:weak)[shield.type-109];
    for (int i=0;i<6;++i) value+=(target.stats[keys[i]]-50)*ratio[covers][i];
    return even(value);
}
inline void wear_piece(int& condition,int damage,Draws& rng) {
    if (!condition) return;
    int loss=(damage+5)/10;
    if (!loss) loss=int(rng.next()*100)<20;
    condition=std::max(0,condition-loss);
}
inline Blow physical_blow(Fighter& attacker,Fighter& target,bool player,int hp_a,int max_a,
                           int hp_t,int max_t,Draws& rng) {
    constexpr int parts[]={0,1,1,1,2,2,2,3,3,3,3,4,4,4,5,5,5,5,6,6};
    constexpr int metal_mod[]={-1,0,0,1,2,3,3,4,5,6};
    const auto& a=attacker.stats; const auto& t=target.stats;
    const auto& s=attacker.move(); const bool armed=attacker.condition>0;
    const int metal=armed?metal_mod[attacker.metal]:0;
    const bool crit=int(rng.next()*100)<attacker.crit/(4-int(std::floor((a[7]-50)/25.)));
    Blow out; out.part=parts[int(rng.next()*20)];
    int chance=(3*s.skill+1)/2+(player?10+s.hit_mod:50)+(armed?2*metal+2:0)
        +(a[7]-t[7])/10+(a[3]-t[3])/4+(a[6]-t[6])/8-even((t[7]-50)/10.f)-target.dodge/2
        +(crit?attacker.crit/4:0);
    if (attacker.adrenaline && hp_a<max_a/6) chance+=8;
    if (target.adrenaline && hp_t<max_t/6) chance-=8;
    out.hit=int(rng.next()*100)<std::clamp(chance,3,97);
    int damage=0;
    if (out.hit && (armed || player)) {
        damage=s.low+int(rng.next()*(1+s.high-s.low))+(player?s.damage_mod:0);
        if (armed && player && target.index==15) damage/=2;
        if (armed && player && attacker.metal==2 &&
            (target.index==15 || target.index==9 || target.index==14 || target.index==18)) damage*=2;
        damage+=int(std::floor((a[0]-50)/10.))*(1+s.both)+metal;
        if (damage>0) {
            const int will=(a[2]-50)/5;
            const int span=std::max(0,player?10+will-target.level/2:5+will+attacker.level/4);
            const int bonus=span?int(rng.next()*span):0;
            if (target.group>=0) {
                if (attacker.flags&(1<<target.group)) damage+=bonus;
                else if (attacker.flags&(16<<target.group))
                    damage-=std::max(0,player?target.level/2-will:target.level-attacker.level-will);
            }
        }
    }
    damage=std::max(0,damage);
    if (crit) damage=even(damage*(1.f+(attacker.crit/5)*.05f));
    if (armed && target.min_metal>attacker.metal)
        damage=even(damage*(1.f-std::min(.9f,(target.min_metal-attacker.metal)*.2f)));
    const float natural=(t[4]-50)*.002f+(t[0]-50)*.001f+(t[2]-50)*.001f;
    auto& shield=target.armor[7]; auto& piece=target.armor[out.part];
    const bool covered=shield.condition && (shield.covers&(1<<out.part));
    const bool blocked=shield.condition && int(rng.next()*100)<block_chance(target,shield,covered)
        && reduced(shield,100,3,natural)<=reduced(piece,100,3,natural);
    if (armed && player) {
        const int pct=100*attacker.condition/attacker.maximum;
        const float m=pct>=61?1.f:pct>=41?(s.blunt?.9f:.85f):pct>=16?(s.blunt?.8f:.7f):
                      pct>=6?(s.blunt?.65f:.45f):(s.blunt?.5f:.25f);
        damage=even(damage*m);
    }
    if (damage) damage=reduced(blocked?shield:piece,damage,!armed?0:s.blunt?1:2,natural);
    if (armed && damage>0) {
        if (attacker.repool) {
            // equip.lowerCondition migrates an old minted pool on first wear,
            // after this hit's condition modifier, even when the wear roll is zero.
            attacker.condition=int((int64_t(attacker.condition)*attacker.repool+attacker.maximum/2)/attacker.maximum);
            attacker.maximum=attacker.repool;
            attacker.repool=0;
        }
        wear_piece(attacker.condition,damage,rng);
        wear_piece((covered?shield:piece).condition,damage,rng);
    }
    out.damage=damage;
    return out;
}
} // namespace dfo_enc
