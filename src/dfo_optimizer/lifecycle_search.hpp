#pragma once
#include "spell_kernel.hpp"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace dfo_lifecycle {
using Mask = uint64_t;
using Clock = std::chrono::steady_clock;
struct Cancel : dfo_spell::Token {
    bool cancelled() const noexcept { return stopped.load(); }
};
inline void mark_replayed(Cancel& token) noexcept { token.incumbent.store(true); }
struct Option { Mask requires_mask; double score; int64_t sp=0; };
struct Stage {
    std::vector<Option> options;
    std::vector<int64_t> prices;
    int64_t ceiling=0, sp_ceiling=INT64_MAX;
    int64_t remaining_debt_cap=INT64_MAX;
};
struct Witness {
    std::vector<int> choices;
    std::vector<Mask> bought;
    std::vector<double> scores;
    int64_t spent = 0;
};
struct Report {
    std::vector<Witness> routes;
    uint64_t nodes=0, pruned=0, leaves=0, work_bytes=0;
    double first_seconds=-1;
    int end=0;
};
inline bool covers(const Witness& a, const Witness& b) {
    if (a.spent>b.spent) return false;
    for (size_t i=0;i<a.scores.size();++i) if (a.scores[i]<b.scores[i]) return false;
    return true;
}

class Search {
    const std::vector<Stage>& stages;
    uint64_t node_limit, memory_limit, fixed_bytes=0;
    double time_limit;
    Clock::time_point started=Clock::now();
    Cancel& flag;
    std::vector<Mask> future_use;
    std::vector<double> max_scores;
    Witness path;
    Report out;

    double elapsed() const { return std::chrono::duration<double>(Clock::now()-started).count(); }
    bool step() {
        if (flag.cancelled()) out.end=4;
        else if (node_limit && out.nodes>=node_limit) out.end=1;
        else if (time_limit && elapsed()>=time_limit) out.end=2;
        if (out.end) return false;
        ++out.nodes;
        return true;
    }
    bool fits(uint64_t points) {
        const auto bytes=fixed_bytes+points*(sizeof(Witness)+stages.size()*24+128);
        if (bytes>memory_limit) {out.end=3; return false;}
        out.work_bytes=std::max(out.work_bytes, bytes);
        return true;
    }
    void publish(int64_t spent) {
        ++out.leaves;
        path.spent=spent;
        for (const auto& other:out.routes) if (covers(other,path)) return;
        auto& rows=out.routes;
        rows.erase(std::remove_if(rows.begin(),rows.end(),[&](const Witness& other) {
            return covers(path,other);
        }),rows.end());
        if (!fits(rows.size()+1)) return;
        rows.push_back(path);
        if (out.first_seconds<0) out.first_seconds=elapsed();
    }
    // Only advance purchases which could matter. If tomorrow's offer is
    // available at an equal/lower price, deferral preserves every completion.
    void extras(size_t s, size_t i, Mask held, Mask buys, int64_t spent,int64_t sp) {
        if (!step()) return;
        const auto& prices=stages[s].prices;
        while (s+1<stages.size() && i<prices.size()) {
            const Mask bit=Mask(1)<<i;
            const auto price=prices[i], next=stages[s+1].prices[i];
            if (!(held&bit) && (future_use[s+1]&bit) && price>=0 &&
                price<=stages[s].ceiling-spent && (next<0 || next>price)) {
                extras(s,i+1,held,buys,spent,sp);
                if (!out.end) extras(s,i+1,held|bit,buys|bit,spent+price,sp);
                return;
            }
            ++i;
        }
        path.bought[s]=buys;
        if (s+1==stages.size()) publish(spent);
        else visit(s+1,held,spent,std::min(stages[s].remaining_debt_cap,sp));
    }
    void visit(size_t s, Mask held, int64_t spent,int64_t sp) {
        const Stage& stage=stages[s];
        if (spent>stage.ceiling) {++out.pruned; return;}
        // Relax resource and access constraints for every future checkpoint.
        // A complete witness that matches even this bound excludes all descendants.
        for (const auto& route:out.routes) {
            if (route.spent>spent) continue;
            bool covered=true;
            for (size_t j=0;j<stages.size();++j) {
                const double ceiling=j<s ? path.scores[j] : max_scores[j];
                if (route.scores[j]<ceiling) {covered=false; break;}
            }
            if (covered) {++out.pruned; return;}
        }
        for (size_t choice=0;choice<stage.options.size();++choice) {
            if (!step()) return;
            const Option& option=stage.options[choice];
            if (option.sp>stage.sp_ceiling-sp) {++out.pruned;continue;}
            Mask needed=option.requires_mask&~held;
            int64_t total=spent;
            bool allowed=true;
            for (size_t i=0;i<stage.prices.size();++i) if (needed&(Mask(1)<<i)) {
                const auto price=stage.prices[i];
                if (price<0 || price>stage.ceiling-total) {allowed=false; break;}
                total+=price;
            }
            if (!allowed) {++out.pruned; continue;}
            path.choices[s]=int(choice);
            path.scores[s]=option.score;
            extras(s,0,held|needed,needed,total,sp+option.sp);
            if (out.end) return;
        }
    }
public:
    Search(const std::vector<Stage>& st, uint64_t n, uint64_t mem, double wall, Cancel& token)
        : stages(st),node_limit(n),memory_limit(mem),time_limit(wall),flag(token) {}
    Report run(Mask owned) {
        const auto n=stages.size();
        future_use.resize(n+1,0);
        max_scores.resize(n,0);
        fixed_bytes=sizeof(*this)+(n+1)*512;
        for (size_t i=n;i-->0;) {
            future_use[i]=future_use[i+1];
            for (const auto& o:stages[i].options) {
                future_use[i]|=o.requires_mask;
                max_scores[i]=std::max(o.score,max_scores[i]);
            }
            fixed_bytes+=stages[i].options.capacity()*sizeof(Option)+stages[i].prices.capacity()*8;
        }
        path.choices.resize(n); path.bought.resize(n); path.scores.resize(n);
        if (fits(0)) visit(0,owned,0,0);
        return std::move(out);
    }
};
inline Report search(const std::vector<Stage>& stages, Mask owned, uint64_t nodes, uint64_t memory,
                     double wall, Cancel& flag) {
    return Search(stages,nodes,memory,wall,flag).run(owned);
}
// Across class families and progression paths, each row has the same ordered
// checkpoint axes. Maximize each coordinate. Preserve equal alternatives.
inline std::vector<int> frontier(const std::vector<std::vector<double>>& rows) {
    std::vector<int> out;
    auto better=[&](int a,int b){
        bool strict=false;
        for (size_t j=0;j<rows[a].size();++j) {
            if (rows[a][j]<rows[b][j]) return false;
            strict|=rows[a][j]>rows[b][j];
        }
        return strict;
    };
    for (size_t i=0;i<rows.size();++i) {
        if (std::any_of(out.begin(),out.end(),[&](int a){return better(a,static_cast<int>(i));})) continue;
        out.erase(std::remove_if(out.begin(),out.end(),[&](int b){return better(static_cast<int>(i),b);}),out.end());
        out.push_back(static_cast<int>(i));
    }
    return out;
}
}
