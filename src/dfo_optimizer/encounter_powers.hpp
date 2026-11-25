#pragma once
#include "encounter_effects.hpp"

namespace dfo_enc {
enum ArcanePath {
    none, battlemage, trickster, riftwalker, warden, wardwright, shadowcaster, spellbreaker,
    bloodmage, elementalist, seer, lightbringer, enchanter, necromancer, soulbinder, hierophant
};
struct PathState {
    int id=none, stacks=0, martial_id=0;
    double stacks_until_ms=0, hurt_ready_ms=0, heal_owed=0, mana_owed=0;
    double martial_ready_ms=0, guard_owed=0;
    int last_cast=-1;
};

inline int path_damage(const PathState& path, double now_ms, int hp, int max_hp, int shield,
                       bool undead_daedra, bool concealed) {
    switch (path.id) {
    case battlemage: return shield > 0 ? 15 : 0;
    case shadowcaster: return concealed ? 25 : 0;
    case bloodmage: return max_hp > 0 ? std::clamp(int(50LL*(max_hp-hp)/max_hp), 0, 25) : 0;
    case elementalist: return now_ms < path.stacks_until_ms ? 3*path.stacks : 0;
    case lightbringer: return undead_daedra ? 20 : 0;
    default: return 0;
    }
}
inline int path_pierce(int id, bool marked=false) {
    return id == spellbreaker ? 10 : id == seer && marked ? 20 : 0;
}
inline int path_speed(int id) { return id == riftwalker ? 20 : 0; }
inline double path_cost(int id, bool all_wards, double sp) {
    return id == wardwright && all_wards ? sp*80/100 : sp;
}
inline bool path_evades(int id, Draws& draws) { return id == seer && draws.next() < 1./8; }
inline int martial_speed(int id) { return id==15 ? 10 : 0; } // Windborne is an attribute fold.
inline bool martial_evades(const PathState& p, Draws& draws) { return p.martial_id==5 && draws.next()<.1; }
inline int martial_guard(PathState& p, int amount) {
    if (p.martial_id != 3 || amount <= 0) return amount;
    const double accumulated = amount*.1+p.guard_owed;
    const int reduction = int(std::floor(accumulated+1e-9));
    p.guard_owed = accumulated-reduction;
    return amount-reduction;
}
inline void path_landed(PathState& path, double now_ms, int cast_id, int took) {
    if (path.id != elementalist || took <= 0 || cast_id == path.last_cast) return;
    path.last_cast = cast_id;
    path.stacks = std::min(5, 1+(now_ms < path.stacks_until_ms ? path.stacks : 0));
    path.stacks_until_ms = now_ms+10000;
}

// playerHeal.js carries each resource's fraction across powers, including when
// a whole-point gain would hit its cap. A heal cannot revive a fallen player.
inline void credit(double amount, int& current, int maximum, double& owed) {
    if (amount <= 0) return;
    const double exact = amount + owed;
    auto whole = static_cast<int64_t>(std::floor(exact + 1e-9));
    owed = exact - whole;
    current = static_cast<int>(std::min<int64_t>(maximum, int64_t(current)+whole));
}
inline void path_hurt(PathState& path, double now_ms, int before, int& hp, int max_hp) {
    if (!(hp > 0 && hp < max_hp*.3 && before >= max_hp*.3)) return;
    // Both listeners see the same (before, after) pair even if one heals the player.
    if (path.id == hierophant && now_ms >= path.hurt_ready_ms) {
        path.hurt_ready_ms = now_ms+180000;
        credit(max_hp*.25, hp, max_hp, path.heal_owed);
    }
    if (path.martial_id==10 && now_ms>=path.martial_ready_ms) {
        path.martial_ready_ms = now_ms+180000;
        credit(max_hp*.2, hp, max_hp, path.heal_owed);
    }
}
inline void path_round(PathState& path, int shield, int& hp, int max_hp) {
    if (path.id == warden && shield > 0 && hp > 0 && hp < max_hp)
        credit(max_hp/100., hp, max_hp, path.heal_owed);
    if (path.martial_id==14 && hp>0 && hp<max_hp)
        credit(max_hp/100., hp, max_hp, path.heal_owed);
}
inline void path_kill(PathState& path, bool eligible, bool trapped, int& hp, int max_hp, int& sp, int max_sp) {
    if (!eligible) return;
    if (path.id == necromancer) {
        if (hp > 0) credit(max_hp*.05, hp, max_hp, path.heal_owed);
        credit(max_sp*.05, sp, max_sp, path.mana_owed);
    } else if (path.id == soulbinder) {
        credit(max_sp*(trapped ? .2 : .1), sp, max_sp, path.mana_owed);
    }
    if (path.martial_id==6 && hp>0) credit(max_hp*.05,hp,max_hp,path.heal_owed);
}
inline void path_signature(PathState& path, int took, int paid, int& hp, int max_hp, int& sp, int max_sp) {
    if (took <= 0) return;
    if (path.id == spellbreaker) credit(paid*(1./3), sp, max_sp, path.mana_owed);
    if (path.id == necromancer && hp > 0) credit(took*.5, hp, max_hp, path.heal_owed);
    if (path.id == soulbinder) credit(took*.25, sp, max_sp, path.mana_owed);
}
inline int aegis_bolt(int took, int max_hp, Draws& draws) {
    if (took <= 0) return 0;
    // A power-cast CasterOnly Shield still calls rollMagnitude for its two fixed endpoints.
    draws.next(); draws.next();
    return static_cast<int>(std::max<int64_t>(1, std::min<int64_t>(int64_t(took)*2,(int64_t(max_hp)+2)/5)));
}
inline void gear_kill(PathState& path, int wellspring_pct, bool eligible, int& sp, int max_sp) {
    if (eligible) credit(double(max_sp)*std::clamp(wellspring_pct,0,10)/100, sp, max_sp, path.mana_owed);
}
} // namespace dfo_enc
