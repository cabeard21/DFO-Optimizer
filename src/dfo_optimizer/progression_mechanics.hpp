#pragma once

#include "spell_kernel.hpp"
#include <array>
#include <tuple>

namespace dfo_progression {
using i64 = std::int64_t;
using u64 = std::uint64_t;
template<typename T> using Skills = std::array<T,35>;
using Stats = std::array<int,8>;
using Book = std::array<u64,4>;

struct Career {
    Skills<int> group{}, multipliers{};
    double advancement{};
    int reflexes{}, starting_sum{};
    int hp_setting{}, magery_quarters{}, fatigue_multiplier{};
    bool career_regeneration{};
};

struct State {
    Skills<int> skills{};
    Skills<i64> uses{}, spam_at{};
    Skills<double> fractions{}, progress{}, spam_recent{};
    Skills<double> move_mark{}, move_credit{};
    double odometer_h{}, odometer_v{};
    Stats attributes{};
    Book known{};
    u64 mastered{}, oghma{}, collected_gold{};
    int firmament{-1};
    int level{}, current_sum{}, pending_level{-1}, pending_pool{-1};
    int allocation_policy{-1};
    int arcane_path{-1}, martial_path{-1}, challenge_level{};
    i64 minutes{}, last_check{}, last_training{}, last_rest{-1}, real_ms{}, challenge_at{-1};
    i64 gold{}, bank_gold{}, sp{}, fatigue{};
    std::uint32_t hp_roll_state{};
    bool hp_known{true};
    int raw_max_hp{}, max_hp{}, hp{}, max_sp{}, max_fatigue{};
    auto fields() const {
        return std::tie(skills, uses, fractions, progress, attributes, known, mastered, level,
            current_sum, pending_level, pending_pool, arcane_path, martial_path, challenge_level,
            minutes, last_check, last_training, last_rest, real_ms, challenge_at, gold, bank_gold, sp, fatigue,
            spam_recent, spam_at, move_mark, move_credit, odometer_h, odometer_v, oghma, firmament,
            hp_roll_state, hp_known, raw_max_hp, max_hp, hp, max_sp, max_fatigue, collected_gold, allocation_policy);
    }
};

enum Kind { skip, practice, rest, check, train, master, level_up, choose, reset, buy, read_oghma, allocate_star, collect_gold };
struct Action {
    int kind{}, skill{}, count{1}, amount{1}, challenge_level{}, spell{-1}, roll{10};
    int family{}, path{-1}, first{}, second{}, member{-1}, bonus{}, focus{};
    i64 cadence_ms{}, minutes{}, real_elapsed_ms{}, sp_cost{}, gold_cost{}, fatigue_cost{1980};
    i64 refill_sp{-1}, refill_fatigue{-1};
    double price_factor{1.};
    bool recipe_set{}, if_due{}, if_eligible{}, use_order{};
    bool movement{}, short_rest{};
    bool until_spent{}, full_bed{}, self_heal{};
    int component_gold{-1}, range_multiplier_twice{};
    int allocation_policy{-1};
    double horizontal_m{}, vertical_m{};
    int until_skill{201};
    Stats allocation{}, order{};
    std::array<int,7> recipe{};
};

struct Effort {
    i64 practice{}, rest_passes{}, minutes{}, spent{};
    bool dominates(const Effort &b) const {
        return practice<=b.practice && rest_passes<=b.rest_passes && minutes<=b.minutes && spent<=b.spent;
    }
};

inline u64 bit(int i) { return u64(1) << i; }
inline bool mastered(const State &s, int i) { return (s.mastered & bit(i)) != 0; }
inline bool knows(const Book &book, int i) { return (book[i/64] & bit(i%64)) != 0; }
inline int effective(const State &s, int i) {
    int v = s.skills[i];
    if (v<=100) return v;
    if (!mastered(s,i)) return 100;
    return 100 + (v-100)/4 + (v>=125?2:0) + (v>=150?3:0) + (v>=175?4:0) + (v>=200?6:0);
}

inline int skill_sum(const State &s, const Career &c) {
    int primary=0, first=0, second=0, minor=0;
    for (int i=0; i<35; ++i) {
        const int v=effective(s,i);
        if (c.group[i]==1) primary+=v;
        if (c.group[i]==2) {
            if (v>=first) { second=first; first=v; }
            else second=std::max(second,v);
        }
        if (c.group[i]==3) minor=std::max(minor,v);
    }
    return primary + first + second + minor;
}

inline int earned_level(int birth, int current) {
    const int room=800-birth;
    if (room<=0) return 45;
    return std::clamp((28*room + 647*std::min(current-birth,room))/(15*room),1,45);
}

inline int requirement(const Career &c, int i, int skill, int level) {
    return int(std::floor(skill*c.multipliers[i]*c.advancement*std::pow(1.04,level)*2/5))+1;
}
inline double ladder(int v) { return v<125?1.5:v<150?2.:v<200?4.:INFINITY; }

inline void latch(State &s, const Career &c) {
    if (s.level>=45) { s.pending_level=-1; s.pending_pool=-1; }
    else if (earned_level(c.starting_sum,s.current_sum)>s.level) s.pending_level=s.level+1;
}

inline bool raise_one(State &s, const Career &c, int i, int price_level) {
    if (!s.uses[i] && s.progress[i]<1.) return false;
    const int v=s.skills[i], n=requirement(c,i,v,price_level);
    const double weighted=double(s.uses[i])*(65536-(c.reflexes-2)*8192);
    if (v>=100 && mastered(s,i)) {
        if (v>=200) return false;
        const double cost=n*ladder(v);
        s.progress[i]+=std::floor(weighted/65536.)/cost;
        s.uses[i]=0;
        if (s.progress[i]<1.) return false;
        s.progress[i]=(s.progress[i]-1.)*cost/(requirement(c,i,v+1,price_level)*ladder(v+1));
    } else {
        // advancement.js uses signed int32 >> 16 in the classic branch.
        // Oversized tallies can survive an import even though new ordinary
        // earnings are clamped at 20000. Conversion here is portable in C++17.
        const u64 hi=static_cast<u64>(std::fmod(weighted,4294967296.)) >> 16;
        const int classic=int(hi)-(hi>=32768 ? 65536 : 0);
        if (classic<n) return false;
        s.uses[i]=0;
        if (v>=100) return false;
    }
    ++s.skills[i];
    return true;
}
inline void raise_pass(State &s, const Career &c, Effort &cost) {
    if (s.minutes-s.last_check<=360) return;
    s.last_check=s.minutes;
    ++cost.rest_passes;
    const int price=std::max(s.level,earned_level(c.starting_sum,std::max(s.current_sum,skill_sum(s,c))));
    bool raised=false;
    for (int i=0; i<35; ++i) raised=raise_one(s,c,i,price) || raised;
    if (raised) s.current_sum=std::max(s.current_sum,skill_sum(s,c));
    latch(s,c);
}
inline double quality(int lv, int skill) {
    if (!lv) return 0;
    const double ratio=double(5*lv+30)/skill;
    if (ratio<.75) return 0;
    if (ratio<1) { const double ramp=(ratio-.75)/.25; return ramp*ramp; }
    return 1+.5*std::min(1.,(ratio-1)/.5);
}
inline void add_weight(State &s,int i,double weight) {
    const double total=s.fractions[i]+weight;
    const auto whole=i64(std::floor(total));
    s.uses[i]+=whole;
    s.fractions[i]=total-whole;
}
inline void tally(State &s,int i,int amount) {
    const int skill=s.skills[i];
    if (skill<100 || !mastered(s,i)) { s.uses[i]=std::min<i64>(20000,s.uses[i]+amount); return; }
    if (skill>=200) return;
    const bool magic=i>=22 && i<=27, combat=i==19 || i==20 || i>=28;
    const int foe=(s.challenge_at>=0 && s.real_ms-s.challenge_at<=6000)?s.challenge_level:0;
    const double q=magic?std::max(.25,quality(foe,skill)):combat?quality(foe,skill):1.;
    if (q<=0) return;
    const double weighted=amount*q;
    s.spam_recent[i]=s.spam_recent[i]*std::pow(.5,double(s.real_ms-s.spam_at[i])/60000.)+weighted;
    s.spam_at[i]=s.real_ms;
    const int free=magic?10:combat?40:6;
    add_weight(s,i,weighted*std::min(1.,free/s.spam_recent[i]));
}

inline void motion(State &s,const Action &a) {
    const int i=a.skill;
    s.odometer_h+=a.horizontal_m;
    s.odometer_v+=a.vertical_m;
    if (s.skills[i]<100 || !mastered(s,i)) { tally(s,i,a.amount); return; }
    if (s.skills[i]>=200) return;
    const double now=i==17?s.odometer_h+s.odometer_v:i==18?s.odometer_v:s.odometer_h;
    const double prior=s.move_mark[i];
    s.move_mark[i]=now;
    if (prior<0 || now<prior) { s.move_credit[i]=0.; return; }
    const double stride=i==17?3.:i==18?.5:1.;
    const double credit=std::min(2.,s.move_credit[i]+(now-prior)/stride);
    const double used=std::min(double(a.amount),credit);
    s.move_credit[i]=credit-used;
    add_weight(s,i,used);
}

inline i64 cast_cost(const State &s,const Action &a) {
    if (a.component_gold >= 0) {
        const i64 live = std::max(0, effective(s,a.skill) + a.bonus);
        const i64 base = live > 100 ? a.component_gold * 1000LL / (400 * live)
                                    : a.component_gold * (110 - live) / 400;
        const i64 price = std::max<i64>(5, base * a.range_multiplier_twice / 2);
        return (price * (100 - std::clamp(a.focus,0,30)) + 50) / 100;
    }
    if (!a.recipe_set) return a.sp_cost;
    dfo_spell::Context ctx;
    ctx.live_skill=std::max(0,effective(s,a.skill)+a.bonus);
    ctx.focus_pct=a.focus;
    const auto &r=a.recipe;
    return dfo_spell::price(ctx,{r[0],r[1],r[2],r[3],r[4],r[5],r[6]}).cost;
}
inline bool practice_batch(State &s,const Action &a,Effort &e) {
    if (a.spell>=0 && !knows(s.known,a.spell)) return false;
    const i64 price = cast_cost(s,a);
    const int count = a.until_spent && price ? int(std::min<i64>(a.count,s.sp/price)) : a.count;
    if (count && a.self_heal && s.hp != s.max_hp) return false;
    const i64 cost=price*count;
    if (s.sp<cost || s.fatigue<a.fatigue_cost) return false;
    s.sp-=cost;
    s.fatigue-=a.fatigue_cost;
    e.practice+=count;
    for (int i=0;i<count;++i) {
        s.real_ms+=a.cadence_ms;
        if (a.challenge_level>0) {
            s.challenge_at=s.real_ms;
            s.challenge_level=a.challenge_level;
        }
        if (a.movement) motion(s,a);
        else tally(s,a.skill,a.amount);
    }
    s.real_ms += (a.count - count) * a.cadence_ms;
    return true;
}
inline bool master_skill(State &s,const Career &c,int skill) {
    int group=c.group[skill], used=0;
    if (!group || mastered(s,skill) || s.skills[skill]<100) return false;
    for (int i=0;i<35;++i) used+=c.group[i]==group && mastered(s,i);
    if (used>=4-group) return false;
    s.mastered|=bit(skill);
    s.uses[skill]=0;
    return true;
}
inline bool distribute(State &s,const Action &a,int pool) {
    Stats deltas=a.allocation;
    if (a.use_order) {
        int left=pool;
        for (int i:a.order) { deltas[i]=std::min(left,100-s.attributes[i]); left-=deltas[i]; }
    }
    int room=0, allocated=0;
    for (int i=0;i<8;++i) {
        room+=100-s.attributes[i];
        if (s.attributes[i]+deltas[i]>100) return false;
        allocated+=deltas[i];
    }
    if (allocated!=std::min(room,pool)) return false;
    for (int i=0;i<8;++i) s.attributes[i]+=deltas[i];
    return true;
}
inline bool level(State &s,const Career &c,const Action &a) {
    const bool due = s.pending_level==s.level+1 && s.level<45;
    if (a.allocation_policy>=0) {
        if ((s.allocation_policy>=0 || !due) && a.allocation_policy!=std::max(s.allocation_policy,0)) return false;
        if (due) s.allocation_policy=a.allocation_policy;
    }
    if (!due) return a.if_due;
    const int lower = c.hp_setting/2;
    if (c.hp_setting) {
        s.hp_roll_state = 1664525u*s.hp_roll_state + 1013904223u;
        const int draw = lower + int((u64(s.hp_roll_state) * (c.hp_setting+1-lower)) >> 32);
        s.raw_max_hp += std::max(1, draw + s.attributes[4]/10 - 5);
    }
    if (!distribute(s,a,s.pending_pool<0?5:s.pending_pool)) return false;
    ++s.level; s.pending_level=-1; s.pending_pool=-1;
    if (c.hp_setting) {
        const int twice_average = lower+c.hp_setting + 2*(s.attributes[4]/10-5);
        const int floor = 25+c.hp_setting + (s.level-1)*std::max(2,twice_average)/2;
        s.max_hp = std::max(floor,s.raw_max_hp);
        s.hp = std::min(s.hp,s.max_hp);
        s.max_sp = s.attributes[1]*c.magery_quarters/4;
        s.max_fatigue = (s.attributes[0]+s.attributes[4])*c.fatigue_multiplier;
    }
    latch(s,c);
    return true;
}
inline bool pay(State &s,Effort &e,i64 amount) {
    if (amount>s.gold) return false;
    s.gold-=amount;
    e.spent+=amount;
    return true;
}
inline bool train_skill(State &s,const Career &c,const Action &a,Effort &e) {
    const i64 price=a.member<0?a.gold_cost:std::max<i64>(1,std::llround((a.member?100:400)*s.level*a.price_factor));
    if (s.skills[a.skill]>50 || s.minutes-s.last_training<720 || s.fatigue<a.fatigue_cost || !pay(s,e,price)) return false;
    s.last_training=s.minutes;
    s.fatigue-=a.fatigue_cost;
    tally(s,a.skill,a.roll*c.multipliers[a.skill]);
    ++e.practice;
    e.minutes+=180; s.minutes+=180;
    return true;
}

inline bool short_rest_available(i64 last_night, i64 now) {
    return last_night>=0 && now>=last_night && now-last_night<120;
}

inline bool apply_action(State &s,const Career &c,const Action &a,Effort &e) {
    s.real_ms+=a.real_elapsed_ms;
    int &path=a.family==0?s.arcane_path:s.martial_path;
    switch (a.kind) {
    case skip: return true;
    case practice:
        if (s.skills[a.skill]>=a.until_skill) return true;
        if (!practice_batch(s,a,e)) return false;
        s.minutes+=a.minutes; e.minutes+=a.minutes;
        return true;
    case rest:
        if (short_rest_available(s.last_rest,s.minutes)) return false;
        s.last_rest=s.minutes+480;
        for (int hour=0;hour<8;++hour) tally(s,0,1);
        if (a.refill_sp>=0) s.sp=std::max(s.sp,a.refill_sp);
        if (a.refill_fatigue>=0) s.fatigue=std::max(s.fatigue,a.refill_fatigue);
        if (a.full_bed) {
            s.hp=s.max_hp;
            s.hp_known=true;
            s.sp=s.max_sp;
            s.fatigue=s.max_fatigue;
        }
        [[fallthrough]];
    case check:
        s.minutes+=a.minutes; e.minutes+=a.minutes;
        if (a.short_rest && !short_rest_available(s.last_rest,s.minutes)) return false;
        raise_pass(s,c,e); return true;
    case train: return train_skill(s,c,a,e);
    case collect_gold:
        if (s.collected_gold & bit(a.first)) return false;
        s.collected_gold|=bit(a.first);
        s.gold+=a.amount;
        return true;
    case master: return master_skill(s,c,a.skill) || a.if_eligible;
    case level_up: return level(s,c,a);
    case read_oghma:
        if (!(s.oghma&bit(a.first)) || !distribute(s,a,30)) return false;
        s.oghma&=~bit(a.first);
        s.pending_level=-1; s.pending_pool=-1;
        return true;
    case allocate_star:
        if (s.firmament!=a.first) return false;
        s.firmament=a.second;
        return true;
    case choose:
        if (path>=0 || !mastered(s,a.first) || !mastered(s,a.second)) return false;
        path=a.path; return true;
    case reset:
        if (path<0 || s.gold+s.bank_gold<200000) return false;
        s.bank_gold-=std::max<i64>(0,200000-s.gold);
        s.gold=std::max<i64>(0,s.gold-200000);
        e.spent+=200000; path=-1; return true;
    case buy:
        if ((a.path>=0 && path!=a.path) || knows(s.known,a.spell) || !pay(s,e,a.gold_cost)) return false;
        s.known[a.spell/64]|=bit(a.spell%64); return true;
    default: return false;
    }
}
inline bool apply(State &s,const Career &c,const Action &a,Effort &e) {
    const auto minutes = s.minutes;
    const auto real_ms = s.real_ms;
    const bool injured = s.hp<s.max_hp;
    if (!apply_action(s,c,a,e)) return false;
    if (c.career_regeneration && !a.full_bed && injured && (minutes!=s.minutes || real_ms!=s.real_ms))
        s.hp_known=false;
    return true;
}
} // namespace dfo_progression
