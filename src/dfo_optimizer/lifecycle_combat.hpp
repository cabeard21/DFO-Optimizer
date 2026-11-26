#pragma once
#include "gear_search.hpp"
#include "lifecycle_search.hpp"
#include "spellbook.hpp"
namespace dfo_lifecycle {
struct Layout {
    std::vector<int> slots;
    dfo_gear::Mods mods{};
    Mask need=0;
    bool changes=false;
    int retained_int=0;
    int wellspring=0;
};
struct Physical {
    std::vector<dfo_gear::Option> items;
    std::vector<dfo_gear::Slot> slots;
    std::vector<std::vector<int>> declared;
    std::vector<int> wellspring;
    std::vector<dfo_book::Bundle> hostile_book;
    bool automatic=true;
};
struct CombatStage {
    dfo_spell::Context ctx;
    int64_t ceiling;
    int intelligence, quarters, worn_int;
    bool uncertain_worn;
    int64_t sp_ceiling;
    int64_t remaining_debt_cap;
    std::vector<int64_t> prices;
    std::shared_ptr<const dfo_enc::Encounter> encounter;
    uint32_t seed=0;
};
struct JointResult {
    Report search;
    std::vector<std::vector<std::vector<int>>> slots;
    std::vector<std::vector<int>> policies;
    uint64_t evaluations=0, cache_hits=0, layout_count=0, uncertain=0, preparation_nodes=0;
};
class Joint {
    const Physical& gear;
    const std::vector<CombatStage>& stages;
    const std::vector<dfo_book::Bundle>& spells;
    const std::vector<std::vector<int>>& policies;
    const uint64_t max_nodes, memory;
    const double seconds;
    const int metric;
    Cancel& cancel;
    Clock::time_point start=Clock::now();
    JointResult out;
    std::vector<int> anchors=std::vector<int>(27,-1);
    std::vector<Layout> layouts;
    std::vector<std::vector<std::pair<int,int>>> choices;
    std::vector<Stage> graph;
    uint64_t reserved=0;
    double elapsed() const { return std::chrono::duration<double>(Clock::now()-start).count(); }
    bool step(uint64_t extra=0) {
        if (cancel.cancelled()) out.search.end=4;
        else if (max_nodes && out.preparation_nodes>=max_nodes) out.search.end=1;
        else if (seconds && elapsed()>=seconds) out.search.end=2;
        else if (reserved+extra>=memory) out.search.end=3;
        if (out.search.end) return false;
        ++out.preparation_nodes;
        reserved+=extra;
        return true;
    }
    void add_layout(Mask used) {
        if (!step(384)) return;
        Layout row;
        row.slots=anchors;
        row.need=used;
        std::vector<int> seen;
        for (const auto& s:gear.slots) {
            int id=anchors[s.id];
            row.changes|=id!=s.current;
            if (id<0) continue;
            const auto& item=gear.items[id];
            if (s.preferred>=0 && anchors[s.preferred]<0 && s.current!=id) {
                const auto& first=gear.slots[s.preferred];
                bool donor=first.current>=0 && first.current!=id;
                for (const auto& p:first.entries) donor|=p.item!=id && gear.items[p.item].owned;
                // An equivalent lone jewel in the first position is enumerated automatically.
                if (!donor) return;
            }
            bool first=item.legendary<0 || std::find(seen.begin(),seen.end(),item.legendary)==seen.end();
            dfo_gear::fold(row.mods,item,first);
            if (first && !gear.wellspring.empty()) row.wellspring+=gear.wellspring[id];
            if (item.legendary>=0) seen.push_back(item.legendary);
            if (id==s.current && item.legendary<0) row.retained_int+=item.mods[7];
        }
        layouts.push_back(std::move(row));
    }
    void generate(size_t i, Mask used, uint32_t occupied, const std::vector<int>* fixed) {
        if (!step()) return;
        while (i<27 && gear.slots[i].entries.empty() && gear.slots[i].lock<0 &&
               (!fixed || (*fixed)[i]<0)) ++i;
        if (i==27) { add_layout(used); return; }
        const auto& slot=gear.slots[i];
        int wanted=fixed ? (*fixed)[i] : slot.lock;
        if (fixed && slot.lock!=-2 && slot.lock!=wanted) return;
        if (wanted<0) generate(i+1,used,occupied,fixed);
        for (const auto& p:slot.entries) {
            if (out.search.end) return;
            if ((wanted!=-2 && wanted!=p.item) || (used&(Mask(1)<<p.item)) || (occupied&p.mask)) continue;
            bool empty_conflict=false;
            for (int pos=0;pos<27;++pos) if ((p.mask&(1u<<pos)) && gear.slots[pos].lock==-1) empty_conflict=true;
            if (empty_conflict) continue;
            anchors[i]=p.item;
            generate(i+1,used|(Mask(1)<<p.item),occupied|p.mask,fixed);
            anchors[i]=-1;
        }
    }
    void score(size_t i) {
        const auto& cs=stages[i];
        Stage st;
        st.ceiling=cs.ceiling;
        st.prices=cs.prices;
        st.sp_ceiling=cs.sp_ceiling;
        st.remaining_debt_cap=cs.remaining_debt_cap;
        std::map<dfo_gear::Mods,std::vector<dfo_book::Prize>> cache;
        std::map<dfo_gear::Mods,std::shared_ptr<const std::vector<dfo_enc::Spell>>> encounter_books;
        uint64_t cache_bytes=0;
        choices.emplace_back();
        for (size_t j=0;j<layouts.size();++j) {
            if (!step()) break;
            const Layout& row=layouts[j];
            auto ctx=dfo_gear::apply(cs.ctx,row.mods);
            // A checkpoint must be reversible before resuming the original practice route.
            if (row.changes && (cs.uncertain_worn || (cs.worn_int>row.retained_int &&
                (cs.quarters<=0 || ctx.available_sp>std::min(100,cs.intelligence+row.retained_int)*cs.quarters/4)))) {
                ++out.uncertain; continue;
            }
            if (cs.encounter) {
                if (row.wellspring && (stages.size()>1 || row.mods[7]!=cs.worn_int)) {
                    ++out.uncertain; continue;
                }
                auto book=encounter_books.find(row.mods);
                if (book==encounter_books.end()) {
                    if (!step((spells.size()+gear.hostile_book.size())*256+128)) break;
                    auto compiled=std::make_shared<std::vector<dfo_enc::Spell>>();
                    for (const auto& spell:spells) compiled->push_back(dfo_enc::from_bundle(ctx,spell));
                    for (const auto& spell:gear.hostile_book) compiled->push_back(dfo_enc::from_bundle(ctx,spell));
                    book=encounter_books.emplace(row.mods,compiled).first;
                    out.evaluations+=spells.size();
                }
                for (size_t p=0;p<policies.size();++p) {
                    if (!step(512+policies[p].size()*sizeof(dfo_enc::Rule))) break;
                    Mask need=row.need;
                    EncounterOption probe{cs.encounter,ctx,book->second,{},cs.seed};
                    probe.wellspring_pct=std::min(10,row.wellspring);
                    for (int k:policies[p]) {
                        need|=Mask(1)<<(gear.items.size()+k);
                        dfo_enc::Rule rule; rule.spell=k; probe.rules.push_back(rule);
                    }
                    st.encounters.push_back(std::move(probe));
                    st.options.push_back({need,0.,0});
                    choices.back().emplace_back(static_cast<int>(j),static_cast<int>(p));
                }
                if (out.search.end) break;
                continue;
            }
            auto it=cache.find(row.mods);
            if (it==cache.end()) {
                const auto cost=256+spells.size()*sizeof(dfo_book::Prize);
                if (!step(cost)) break;
                cache_bytes+=cost;
                std::vector<dfo_book::Prize> values;
                for (const auto& spell:spells) {
                    if (!step()) break;
                    const auto deadline=start+std::chrono::duration_cast<Clock::duration>(
                        std::chrono::duration<double>(seconds));
                    dfo_book::SpellAccess access{&cancel,seconds ? &deadline : nullptr,
                                                 static_cast<size_t>(memory-reserved)};
                    try {
                        values.push_back(dfo_book::evaluate(ctx,spell,&access));
                    } catch (const dfo_book::SearchLimitReached& stop) {
                        const std::string reason=stop.reason;
                        out.search.end=reason=="cancelled" ? 4 : reason=="time_limit" ? 2 : 3;
                        break;
                    }
                    ++out.evaluations;
                }
                if (out.search.end) break;
                it=cache.emplace(row.mods,std::move(values)).first;
            } else ++out.cache_hits;
            for (size_t p=0;p<policies.size();++p) {
                if (!step()) break;
                Mask needs=row.need;
                int64_t sp=0;
                double total=0, health_loss=0;
                for (int id:policies[p]) {
                    needs|=Mask(1)<<(gear.items.size()+id);
                    const auto& value=it->second[id];
                    sp+=value.cost_sp;
                    total+=value.dps;
                    health_loss+=value.expected_health_loss;
                }
                const bool unarmed_birth=policies[p].empty() && i==0 && stages.size()>1;
                if (sp>ctx.available_sp || (total<=0 && !unarmed_birth)) continue;
                if (!step(64)) break;
                st.options.push_back({needs,unarmed_birth ? 0. : total/policies[p].size(),sp,health_loss});
                choices.back().emplace_back(static_cast<int>(j),static_cast<int>(p));
            }
            if (out.search.end) break;
        }
        reserved-=cache_bytes;
        graph.push_back(std::move(st));
    }
public:
    Joint(const Physical& g,const std::vector<CombatStage>& s,const std::vector<dfo_book::Bundle>& b,
          const std::vector<std::vector<int>>& p,uint64_t n,uint64_t m,double w,Cancel& f,int objective)
        :gear(g),stages(s),spells(b),policies(p),max_nodes(n),memory(m),seconds(w),metric(objective),cancel(f){}
    JointResult run(Mask owned) {
        if (gear.automatic) generate(0,0,0,nullptr);
        else for (const auto& row:gear.declared) {if (out.search.end) break; generate(0,0,0,&row);}
        out.layout_count=layouts.size();
        for (size_t i=0;i<stages.size() && !out.search.end;++i) score(i);
        if (!out.search.end && max_nodes && out.preparation_nodes>=max_nodes) out.search.end=1;
        if (!out.search.end) out.search=search(graph,owned,max_nodes?max_nodes-out.preparation_nodes:0,
                                               memory-reserved,seconds?std::max(1e-12,seconds-elapsed()):0,cancel,metric);
        for (const auto& w:out.search.routes) {
            out.slots.emplace_back(); out.policies.emplace_back();
            for (size_t i=0;i<w.choices.size();++i) {
                auto [j,p]=choices[i][w.choices[i]];
                out.slots.back().push_back(layouts[j].slots);
                out.policies.back().push_back(p);
            }
        }
        out.search.nodes+=out.preparation_nodes;
        out.search.work_bytes+=reserved;
        return std::move(out);
    }
};
inline void set_encounter(CombatStage& stage,const dfo_enc::Encounter& scene,uint32_t seed) {
    stage.encounter=std::make_shared<const dfo_enc::Encounter>(scene);
    stage.seed=seed;
}
inline JointResult joint(const Physical& g,const std::vector<CombatStage>& s,const std::vector<dfo_book::Bundle>& b,
                         const std::vector<std::vector<int>>& p,Mask owned,uint64_t n,uint64_t m,double w,Cancel& f,int objective) {
    return Joint(g,s,b,p,n,m,w,f,objective).run(owned);
}
}
