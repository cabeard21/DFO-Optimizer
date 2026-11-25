#pragma once

#include "progression_mechanics.hpp"
#include <deque>
#include <queue>
#include <unordered_map>

namespace dfo_progression {
using Clock = std::chrono::steady_clock;
struct Cancel {
    std::atomic<bool> requested{false}, incumbent{false};
    void cancel() noexcept { requested.store(true,std::memory_order_relaxed); }
    bool has_incumbent() const noexcept { return incumbent.load(std::memory_order_relaxed); }
};
struct Goal {
    int level{}, arcane{-1}, martial{-1}, firmament{-1};
    Skills<int> skills{};
    Stats attributes{};
    u64 mastered{};
    Book known{};
};
inline int missing(const State &s,const Goal &g) {
    int d=std::max(0,g.level-s.level);
    for (int i=0;i<35;++i) d+=std::max(0,g.skills[i]-s.skills[i])+int(bool((g.mastered & ~s.mastered)&bit(i)));
    for (int i=0;i<8;++i) d+=std::max(0,g.attributes[i]-s.attributes[i]);
    for (int i=0;i<4;++i) {
        u64 bits=g.known[i]&~s.known[i];
        while (bits) { bits&=bits-1; ++d; }
    }
    return d+(g.arcane>=0 && g.arcane!=s.arcane_path)+(g.martial>=0 && g.martial!=s.martial_path)
            +(g.firmament>=0 && g.firmament!=s.firmament);
}
struct Limits {
    u64 max_nodes{}, memory_bytes{};
    double wall_seconds{};
    bool retain_states{}, final_stage_only{};
};
struct Node {
    State state;
    Effort effort;
    int parent{-1}, choice{-1}, depth{}, distance{};
};
struct Path {
    State state;
    Effort effort;
    std::vector<int> choices;
};
struct Report {
    std::vector<Path> results;
    Path prefix;
    u64 nodes{}, pruned{}, leaves{}, hits{}, work_bytes{};
    double first_seconds{-1};
    int end{};
};
using Stages=std::vector<std::vector<Action>>;

// A compact bucket key only speeds up lookups. Every collision, including keys
// sharing this projection, is resolved by comparing the full state and effort.
inline u64 bucket(const Node &n) {
    u64 key=n.depth;
    auto mix=[&](u64 v){ key=(key^v)*1099511628211ULL; };
    mix(n.state.minutes); mix(n.state.gold); mix(n.state.sp); mix(n.state.mastered);
    mix(n.state.current_sum); mix(n.state.level); mix(n.state.known[0]);
    for (int i=0;i<35;++i) { mix(n.state.skills[i]); mix(n.state.uses[i]); }
    return key;
}

struct Priority {
    const std::deque<Node> *arena;
    bool operator()(int x,int y) const {
        const auto &a=(*arena)[x], &b=(*arena)[y];
        // A heuristic for traversal only. It never excludes a feasible continuation.
        return std::make_tuple(a.distance,-a.depth,a.effort.practice,x)>
               std::make_tuple(b.distance,-b.depth,b.effort.practice,y);
    }
};
class Search {
    const Career &career;
    const Stages &stages;
    const Goal &goal;
    const Limits &limits;
    Cancel &cancel;
    const Clock::time_point begin=Clock::now();
    std::deque<Node> arena;
    std::priority_queue<int,std::vector<int>,Priority> open{Priority{&arena}};
    std::unordered_multimap<u64,int> seen;
    std::vector<int> winners;
    Report report;
    u64 input_bytes{}, winner_bytes{};
    int best{};
    bool cache{};
    double elapsed() const { return std::chrono::duration<double>(Clock::now()-begin).count(); }
    bool stopped() {
        if (cancel.requested.load(std::memory_order_relaxed)) report.end=4;
        else if (limits.max_nodes && report.nodes>=limits.max_nodes) report.end=1;
        else if (limits.wall_seconds && elapsed()>=limits.wall_seconds) report.end=2;
        return report.end!=0;
    }
    bool fits(u64 total) {
        if (total>limits.memory_bytes) { report.end=3; return false; }
        report.work_bytes=std::max(report.work_bytes,total);
        return true;
    }
    static u64 path_bytes(const Node &n) { return sizeof(Path)+sizeof(int)*(n.depth+1U)+64U; }
    u64 storage(size_t nodes) const {
        return input_bytes+winner_bytes+nodes*(sizeof(Node)+sizeof(int)*5+112)+
            (cache?nodes*80:0)+path_bytes(arena[best]);
    }
    bool duplicate(const Node &n,u64 key) {
        auto found=seen.equal_range(key);
        for (auto it=found.first;it!=found.second;++it) {
            const auto &prev=arena[it->second];
            if (prev.depth==n.depth && prev.effort.dominates(n.effort) &&
                prev.state.fields()==n.state.fields()) return true;
        }
        return false;
    }
    void accept(int index) {
        const auto &n=arena[index];
        u64 replaced=0;
        if (!limits.retain_states) {
            for (int w:winners) if (arena[w].effort.dominates(n.effort)) return;
            for (int w:winners) if (n.effort.dominates(arena[w].effort)) replaced+=path_bytes(arena[w]);
        }
        if (!fits(storage(arena.size())-replaced+path_bytes(n))) return;
        if (replaced) {
            winners.erase(std::remove_if(winners.begin(),winners.end(),[&](int w) {
                return n.effort.dominates(arena[w].effort);
            }),winners.end());
            winner_bytes-=replaced;
        }
        winners.push_back(index);
        winner_bytes+=path_bytes(n);
        if (report.first_seconds<0) {
            report.first_seconds=elapsed();
            cancel.incumbent.store(true,std::memory_order_relaxed);
        }
    }
    void queue(Node n) {
        const auto key=cache?bucket(n):0;
        if (cache && duplicate(n,key)) { ++report.hits; ++report.pruned; return; }
        if (arena.size()>=std::numeric_limits<int>::max()) { report.end=3; return; }
        if (!fits(storage(arena.size()+1)+n.depth*sizeof(int))) return;
        const int idx=int(arena.size());
        arena.push_back(std::move(n));
        const auto &node=arena[idx];
        if (cache) seen.emplace(key,idx);
        if (node.depth>arena[best].depth ||
            (node.depth==arena[best].depth && node.distance<arena[best].distance)) best=idx;
        dispatch(idx);
    }
    Path path(int idx) const {
        const auto &n=arena[idx];
        Path p{n.state,n.effort,{}};
        p.choices.resize(n.depth);
        for (int pos=n.depth-1;pos>=0;--pos) {
            p.choices[pos]=arena[idx].choice; idx=arena[idx].parent;
        }
        return p;
    }
    void dispatch(int idx) {
        const auto &n=arena[idx];
        if ((!limits.final_stage_only || n.depth==int(stages.size())) && !n.distance) {
            ++report.leaves; accept(idx); return;
        }
        if (n.depth==int(stages.size())) { ++report.leaves; return; }
        open.push(idx);
    }
    void expand(int idx) {
        const auto &n=arena[idx];
        const auto &actions=stages[n.depth];
        for (int j=0;j<int(actions.size());++j) {
            if (stopped()) return;
            ++report.nodes;
            Node child{n.state,n.effort,idx,j,n.depth+1,0};
            if (!apply(child.state,career,actions[j],child.effort)) { ++report.pruned; continue; }
            child.distance=missing(child.state,goal);
            queue(std::move(child));
            if (report.end) return;
        }
    }
public:
    Search(const Career &c,const Stages &st,const Goal &g,const Limits &l,Cancel &token):
        career(c),stages(st),goal(g),limits(l),cancel(token) {}
    Report run(const State &start) {
        input_bytes=sizeof(*this)+sizeof(Career)+sizeof(Goal)+sizeof(State)+stages.size()*sizeof(Stages::value_type);
        for (const auto &row:stages) {
            input_bytes+=row.size()*sizeof(Action);
            if (row.size()>1 && !limits.retain_states) cache=true;
        }
        arena.push_back(Node{start,{},-1,-1,0,missing(start,goal)});
        if (cancel.requested.load(std::memory_order_relaxed)) report.end=4;
        else if (fits(storage(1))) dispatch(0);
        while (!open.empty() && !report.end) {
            // Already-generated states can qualify even when the last expansion
            // exactly spent the node budget. Only new edges consume nodes.
            if (cancel.requested.load(std::memory_order_relaxed)) { report.end=4; break; }
            if (limits.wall_seconds && elapsed()>=limits.wall_seconds) { report.end=2; break; }
            int idx=open.top(); open.pop(); expand(idx);
        }
        report.prefix=path(best);
        report.results.reserve(winners.size());
        for (int w:winners) report.results.push_back(path(w));
        return std::move(report);
    }
};
inline Report search(const Career &c,const State &s,const Stages &st,const Goal &g,const Limits &l,Cancel &cancel) {
    return Search(c,st,g,l,cancel).run(s);
}
} // namespace dfo_progression
