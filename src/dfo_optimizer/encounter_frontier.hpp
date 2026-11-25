// Included inside dfo_enc after Trial and PolicyResult.
inline void add_trial(EncounterScore& score,const Trial& t,Time horizon) {
        score.cleared+=t.cleared;
        score.alive+=!t.dead;
        score.kills+=t.kills;
        score.damage+=t.damage;
        score.spent+=t.spent_sp;
        score.elapsed+=t.end_us;
        score.censored+=t.cleared?t.end_us:horizon;
}
// Compare integer ratios exactly without cross-product overflow. Continued
// fractions have opposite order after each reciprocal step.
inline int compare_ratio(std::uint64_t an,std::uint64_t ad,std::uint64_t bn,std::uint64_t bd) {
    if (!ad || !bd) return int(ad!=0)-int(bd!=0); // undefined ranks last
    int sign=1;
    for (;;) {
        const auto aq=an/ad, bq=bn/bd;
        if (aq!=bq) return sign*(aq>bq?1:-1);
        const auto ar=an%ad, br=bn%bd;
        if (!ar || !br) return sign*(int(ar!=0)-int(br!=0));
        an=ad;ad=ar;bn=bd;bd=br;sign=-sign;
    }
}
inline int metric_order(std::int64_t a,std::int64_t b) {return (a>b)-(a<b);}
inline bool encounter_dominates(const EncounterScore& a,const EncounterScore& b,int objective) {
    switch (objective) {
        case 1:return a.cleared>=b.cleared;
        case 2:return compare_ratio(a.kills,a.elapsed,b.kills,b.elapsed)>=0;
        case 3:return a.alive>=b.alive;
        case 4:return compare_ratio(a.damage,a.spent,b.damage,b.spent)>=0;
        default:return a.cleared>=b.cleared && a.alive>=b.alive &&
            compare_ratio(a.kills,a.elapsed,b.kills,b.elapsed)>=0 &&
            a.damage>=b.damage && a.spent<=b.spent && a.censored<=b.censored;
    }
}
template<class Budget>
inline bool retain_policy(std::vector<PolicyResult>& rows, PolicyResult&& candidate,const Limits& limits,Budget& budget) {
    std::size_t removed=0;
    if (limits.frontier) for (std::size_t i=0;i<rows.size();++i) {
        if (!(i%64) && !budget.check()) return false;
        if (encounter_dominates(rows[i].score,candidate.score,limits.objective)) {
            budget.release_bytes(candidate.payload_bytes);
            return true;
        }
        removed+=encounter_dominates(candidate.score,rows[i].score,limits.objective);
    }
    if (rows.size()-removed==rows.capacity() &&
        !budget.grow(rows,std::max<std::size_t>(1,rows.capacity()*2))) return false;
    // Only mutate the certified frontier after all checks/allocations succeed.
    if (removed) rows.erase(std::remove_if(rows.begin(),rows.end(),[&](const PolicyResult& row) {
        if (!encounter_dominates(candidate.score,row.score,limits.objective)) return false;
        budget.release_bytes(row.payload_bytes);
        return true;
    }),rows.end());
    rows.push_back(std::move(candidate));
    return true;
}
