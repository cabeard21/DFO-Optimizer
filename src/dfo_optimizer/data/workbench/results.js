import {action,disclosure,el,facts,field,format,graph,metrics,nameOf,panel,pretty,replayAction,resultRows,select,table} from "./view.js";
import {recommendationPane} from "./beginner.js";
import {retainNumbers,stringifyDocument} from "./exact-json.js";

function note(value) {
  return typeof value==="string" ? value : JSON.stringify(value);
}
function warningList(values) {
  return values.filter(v=>v!=null).flatMap(value=>Array.isArray(value)?value:[value])
    .filter(v=>typeof v==="object"?Object.keys(v).length:Boolean(v)).map(v=>el("p",note(v),"warning"));
}
function commonAxes(rows) {
  const values=new Set();
  for(const row of rows)for(const key of Object.keys(metrics(row)))values.add(key);
  const preferred=["clear_probability","kills_per_minute","dps","final_dps","damage_per_sp","total_spent_gold","gold","objective_value","minutes","practice"];
  return [...preferred.filter(k=>values.has(k)),...[...values].filter(k=>!preferred.includes(k))];
}
function buildFamily(result,row,catalog){
  const request=result.frozen_request??{},admission=request.class_admission;
  const family=[...(admission?.families??[]),...(request.families??[])].find(f=>f.id===row.family);
  const doc=family?.start?.class??catalog?.caster_classes?.[family?.baseline_id];
  if(!doc)return null;
  const features=admission?.screening_features?.[row.family];
  const raceId=family.start?.race_id??catalog?.caster_races?.[family.baseline_id];
  const race=catalog?.races?.find(r=>r.id===raceId)?.name??features?.race;
  return {family,doc,features,race};
}
function familyLabel(result,name){
  const features=result.frozen_request?.class_admission?.screening_features?.[name];
  return features?.race?features.race+" · "+name.slice(0,10):name;
}
const traitsText=picks=>picks.map(t=>pretty([t.primary,t.secondary].filter(Boolean).join(" / "))).join(", ")||"None";
function buildDetails(result,row,catalog){
  const build=buildFamily(result,row,catalog);
  if(!build)return [];
  const {doc,features,race}=build;
  const fields=[facts({family:familyLabel(result,row.family),race:race??row.family,roll_seed:row.roll_seed,class_health:doc.hitPointsPerLevel}),
    table(["Class attribute","Editor value"],Object.entries(doc.attributes).map(([k,v])=>[pretty(k),v])),
    facts({advantages:traitsText(doc.advantages),disadvantages:traitsText(doc.disadvantages)}),
    table(["Skill group","Ordered skills"],Object.entries(doc.skills).map(([k,v])=>[pretty(k),v.join(", ")]))];
  if(features){
    fields.push(facts({magery:features.magicka_multiplier+" × Intelligence",advancement:features.advancement_multiplier+"×",
      spell_absorption:features.spell_absorption,casts_in_daylight_and_darkness:features.unrestricted_day_and_night,
      required_masteries:features.required_masteries?.join(", "),eligible_arcane_paths:features.potential_arcane_paths?.join(", ")}));
    const rolled=features.paired_births?.find(b=>b.seed===row.roll_seed);
    if(rolled)fields.push(foldFacts("Realized birth on this seed",{
      ...rolled.attributes,health:rolled.hp,spell_points:rolled.sp,cast_rate:rolled.cast_rate,destruction:rolled.destruction
    }));
    const sources=features.equipment_class_compatibility??[];
    if(sources.length)fields.push(table(["Stage","Eligible equipment","Excluded equipment"],sources.map(
      s=>[s.stage,s.eligible.join(", ")||"None",Object.entries(s.excluded).map(([k,v])=>k+" · "+v.join(", ")).join("; ")||"None"])));
    fields.push(disclosure("Screening features and limits",features));
  }
  const chosen=(row.actions??[]).filter(a=>["master","choose"].includes(a.kind));
  if(chosen.length)fields.push(disclosure("Replayed mastery and specialization choices",chosen));
  for(const point of row.checkpoints??[]){
    const loadout=Object.entries(point.loadout??{}).map(([slot,item])=>pretty(slot)+" · "+item);
    fields.push(foldFacts("Level "+point.level+" · stage "+point.stage,{
      equipment:loadout.join(", ")||"Empty",casting_policy:point.casting_policy?.join(" → "),
      ...point.performance,ending_hp:point.encounter?.end_hp
    }));
  }
  return fields;
}
function foldFacts(label,values){
  const box=el("details");box.append(el("summary",label),facts(Object.fromEntries(
    Object.entries(values).filter(([,v])=>v!==undefined))));return box;
}
function candidateDetails(row) {
  const details=[];
  if(row.loadout)details.push(table(["Equipment slot","Physical copy"],Object.entries(row.loadout).map(([k,v])=>[k,v??"Empty"])));
  if(row.class_doc)details.push(facts(row.class_doc.attributes),disclosure("Game class",row.class_doc));
  if(row.actions?.length)details.push(el("h3","Next action"),el("p",note(row.actions[0])),
    disclosure("Training and decisions ("+row.actions.length+")",row.actions));
  if(row.checkpoints?.length){
    const combat=Object.hasOwn(row.checkpoints[0],"dps");
    details.push(el("h3","Milestones","gap"),combat?
      table(["Stage","Level","DPS","SP before","SP after","Gold spent","Casting policy"],
        row.checkpoints.map(s=>[s.stage,s.level,s.dps,s.sp_available,s.sp_after_policy,s.spent_gold,s.casting_policy?.join(" → ")])):
      table(["Stage","Level","Game minutes","SP","Gold","Arcane path"],
        row.checkpoints.map(s=>[s.stage,s.state.level,s.state.minutes,s.state.sp,s.state.gold,s.state.arcane_path||"—"])),
      disclosure("Checkpoint outcomes",row.checkpoints));
  }
  if(row.spell)details.push(disclosure("Spellmaker recipe",row.spell));
  if(row.purchases?.length)details.push(disclosure("Acquisition",row.purchases));
  if(row.trials?.length)details.push(disclosure("Encounter trials",row.trials));
  return details;
}

export function resultsPane(session,handlers){
  const job=session.job;
  if(!job)return panel("Results",[el("p","Run the selected request to inspect its legal results and search coverage.","empty")]);
  const completed=["completed","cancelled","failed"].includes(job.state);
  const usePreview=Boolean(job.incumbent&&(!job.result||job.state==="cancelled"&&!job.result.recommendation&&!resultRows(job.result).length));
  const result=usePreview?job.incumbent:job.result;
  const head=[el("span",pretty(job.state),"state")];
  if(!completed)head.push(action("Cancel search",handlers.cancel));
  const toolbar=el("div",null,"row");toolbar.append(...head);
  const children=[toolbar];
  if(job.error)children.push(el("p",job.error,"warning"));
  if(session.changed)children.push(el("p","Inputs have changed since this search was submitted.","warning"));
  if(job.progress?.phase&&!job.result)children.push(el("p",pretty(job.progress.phase),"note"));
  if(!result)return panel("Search progress",children);
  if(result.kind==="beginner_recommendation"){
    const buttons=el("div",null,"actions");
    const controls={...handlers,
      exportFamily:key=>handlers.exportFamily(key,usePreview),exportChecklist:key=>handlers.exportChecklist(key,usePreview)};
    if(usePreview){
      children.push(el("p","First checked recommendation. The search is still comparing classes.","note"));
      buttons.append(action("Export validated preview",handlers.exportPreview));
    }else{
      buttons.append(action("Save to library",handlers.save),action("Export archive",handlers.exportArchive),
                     action("Replay result",handlers.replay));
    }
    const container=el("div");
    container.append(...children,recommendationPane(result,controls,session),buttons);
    return container;
  }
  if(usePreview)children.push(el("p",completed?"Last independently validated preview.":"First validated result. Search is running.","note"),
    action("Export validated preview",handlers.exportPreview));
  const rows=[...resultRows(result),...(result.comparison_witnesses??[])];
  function pick(index){
    session.index=index;
    if(result.kind==="lifecycle"&&rows[index]){
      const row=rows[index];
      session.selectedBuild={family:row.family,seed:row.roll_seed,
        choices:stringifyDocument([row.progression_choices,row.choices],0,true)};
    }
    handlers.refresh();
  }
  // A preview and the final frontier can put the same family at different indices.
  if(result.kind==="lifecycle"&&session.selectedBuild){
    const selected=session.selectedBuild;
    const matches=r=>r.family===selected.family&&r.roll_seed===selected.seed;
    let index=rows.findIndex(r=>matches(r)&&stringifyDocument([r.progression_choices,r.choices],0,true)===selected.choices);
    if(index<0)index=rows.findIndex(matches);
    session.index=index<0?0:index;
  }
  children.push(facts({status:result.status??(result.valid===true?"Verified":"Available"),
    termination:result.termination??job.state,retained:rows.length,
    ...(result.counters?.nodes!==undefined?{nodes:result.counters.nodes}:{}),
    ruleset:(result.ruleset_hash??job.ruleset_hash??"Unknown").slice(0,12)}));
  children.push(...warningList([result.blockers,result.first_gap,result.unsupported_mechanics,result.missing_observations]));
  if(result.proof_scope)children.push(disclosure("Search scope",result.proof_scope));
  if(result.class_admission){
    children.push(el("h3","Class admission"),facts(result.class_admission));
    const paired=result.paired_family_frontier;
    if(paired?.points?.length){
      const names=paired.axes??Object.keys(paired.points[0].means);
      children.push(el("h3","Builds selected before birth","gap"),el("p",note(paired.scope),"note"),
        table(["Family",...names.map(pretty),"Replayed rolls"],paired.points.map(point=>{
          const cells=el("div",null,"row");
          for(const sample of point.rolls)cells.append(action("Seed "+sample.seed,()=>pick(sample.witness_index)));
          return [familyLabel(result,point.family),...names.map(k=>point.means[k]??"�"),cells];
        })));
    }
    if(result.family_comparisons?.length){
      const scalar=result.family_comparisons.some(f=>Object.hasOwn(f,"rank"));
      const clear=result.family_comparisons.some(f=>Object.hasOwn(f,"clear_fraction"));
      const ranked=scalar?[...result.family_comparisons].sort((a,b)=>(a.rank??Infinity)-(b.rank??Infinity)):result.family_comparisons;
      children.push(el("h3","Paired family comparison","gap"),table(["Family",...(scalar?["Rank","Mean score"]:[]),
        ...(clear?["Clear fraction","Censored mean clear time (s)"]:[]),"Early DPS range","Final DPS range","Paired birth rolls"],
        ranked.map(f=>{
          const links=el("div",null,"row");
          for(const roll of f.rolls){
            if(Number.isInteger(roll.witness_index)&&rows[roll.witness_index])
              links.append(action("Seed "+roll.seed,()=>pick(roll.witness_index)));
            else links.append(el("span","Seed "+roll.seed+" · "+pretty(roll.status)));
          }
          const range=key=>{
            const values=f.rolls.map(r=>r[key]).filter(Number.isFinite);
            return values.length?format(Math.min(...values))+" – "+format(Math.max(...values)):"—";
          };
          return [familyLabel(result,f.family),...(scalar?[f.rank??"—",f.mean_score??"—"]:[]),
            ...(clear?[f.clear_fraction??"—",f.censored_mean_clear_us==null?"—":f.censored_mean_clear_us/1e6]:[]),
            range("early_dps"),range("final_dps"),links];
        })));
    }else if(result.roll_spread?.length)children.push(table(["Family","Paired rolls evaluated","Lowest final DPS","Highest final DPS"],
      result.roll_spread.map(r=>[familyLabel(result,r.family),r.covered_rolls.length+" / "+result.paired_rolls.length,r.peak_final_dps_min,r.peak_final_dps_max])));
    if(result.gaps?.length)children.push(disclosure("Missing prerequisites",result.gaps));
    if(result.final_checkpoint_only?.length)children.push(disclosure("Final checkpoint comparison",result.final_checkpoint_only));
  }
  if(result.assumptions||result.scenario)children.push(disclosure("Encounter assumptions",result.assumptions??result.scenario));
  if(result.sensitivity?.length)children.push(disclosure("Sensitivity to scenario assumptions",result.sensitivity));
  if(!rows.length){
    children.push(disclosure("Result details",result)); 
  }else{
    const i=Math.min(Math.max(0,session.index||0),rows.length-1),row=rows[i];
    const axes=commonAxes(rows);
    if(result.kind==="spell_curve"){
      for(const [key,label] of [["dps","DPS if cast"],["damage_per_sp","Damage per SP"]]){
        children.push(el("h3",label,"gap"),graph(rows,result.axis,key,i,pick));
      }
      children.push(table([pretty(result.axis),"SP cost","Can cast","DPS if cast","Damage per SP"],
        rows.map(r=>[r[result.axis],r.metrics.cost_sp,r.metrics.affordable,r.metrics.dps,r.metrics.damage_per_sp])));
    }
    const page=Math.floor(i/25),start=page*25;
    const nav=el("div",null,"row gap");
    nav.append(el("h3","Retained options"),el("small",String(start+1)+"–"+Math.min(start+25,rows.length)+" of "+rows.length,"note"));
    if(start>0)nav.append(action("Previous",()=>pick(start-1)));
    if(start+25<rows.length)nav.append(action("Next",()=>pick(start+25)));
    children.push(nav,table(["Option",...axes.slice(0,3).map(pretty)],rows.slice(start,start+25).map((r,k)=>{
      const name=r.family?familyLabel(result,r.family)+" · seed "+r.roll_seed:nameOf(r,start+k);
      const button=action(name,()=>pick(start+k));
      button.setAttribute("aria-pressed",String(i===start+k));
      return [button,...axes.slice(0,3).map(a=>metrics(r)[a])];
    })));
    children.push(el("h3","Selected option","gap"),facts(metrics(row)),...candidateDetails(row),disclosure("Complete selected option",row));
    if(result.kind==="lifecycle"){
      children.push(...buildDetails(result,row,handlers.catalog));
      if(!usePreview&&row.validated&&buildFamily(result,row,handlers.catalog))
        children.push(action("Export game class",()=>handlers.exportFamily(row.family)));
    }
    if(result.marginals&&Object.keys(result.marginals).length){
      children.push(el("h3","Value of each item","gap"),table(["Excluded item","DPS difference","Damage/SP difference","Search status"],
        Object.entries(result.marginals).map(([item,m])=>[item,m.delta_best_dps,m.delta_best_damage_per_sp,m.status])),
        disclosure("Reoptimized upgrade deltas",result.marginals));
    }
    if(row.class_doc&&job.result&&!usePreview)children.push(action("Export game class",()=>handlers.exportClass(i)));
  }
  if(job.result) {
    const buttons=el("div",null,"actions");buttons.append(action("Save to library",handlers.save),action("Export result",handlers.exportResult),
      action("Export archive",handlers.exportArchive));
    if(replayAction(job.result))
      buttons.append(action("Replay result",handlers.replay));
    children.push(buttons);
  }
  return panel("Search results",children);
}

function compareContext(archive){
  const req=archive.request||{}, op=archive.action||"";
  if(archive.result?.kind==="lifecycle" && archive.result.comparison_hash)
    return JSON.stringify([archive.ruleset_hash,"lifecycle",archive.result.comparison_hash]);
  const keys=op.startsWith("gear ")?["caster","character","career","target","scenario","encounter","live_observations","domain","spell","spell_policy","capacity","objective","price_factor"]:
    op==="spell curve"?["caster","character","target","price_factor","live_observations","curve"]:
    op.startsWith("spell ")?["caster","character","target","price_factor","live_observations"]:
    op.startsWith("encounter ")?["actor","scenario","seeds","spells"]:null;
  const scope=keys?retainNumbers(req,Object.fromEntries(keys.map(k=>[k,req[k]]))):req;
  return stringifyDocument([archive.ruleset_hash,op,scope,req.search?.objective],0,true);
}
export function comparePane(archives,state,refresh,meta){
  const options=archives.filter(item=>item.result&&resultRows(item.result).length);
  if(!options.length)return panel("Compare results",[el("p","Save a completed search to the library to compare its tradeoffs.","empty")]);
  const selectItems=options.map((item,i)=>[String(i),item.label||item.action]);
  const controls=el("div",null,"row");
  function pick(key,defaultIndex){
    const i=Math.min(state[key]??defaultIndex,options.length-1);
    controls.append(field(key==="left"?"First search":"Second search",select(selectItems,String(i),v=>{
      state[key]=Number(v);state.point=0;refresh();
    })));
    return options[i];
  }
  const left=pick("left",0),right=pick("right",Math.min(1,options.length-1));
  const children=[controls];
  if(left!==right){
    children.push(table(["Search","Search status","Acquisition mode","Budget"],
      [left,right].map(item=>[item.label||item.action,item.result.status,item.request?.mode||"—",
        item.request?.budget?JSON.stringify(item.request.budget):item.request?.budget_gold??"—"])));
  }
  if(!left.request||!right.request||compareContext(left)!==compareContext(right)){
    children.push(el("p","Ruleset, scenario, search objective, or frozen inputs differ. Re-run both with matching inputs to compare numeric deltas.","warning"),
      disclosure("First search scope",left.request||left.result.proof_scope),disclosure("Second search scope",right.request||right.result.proof_scope));
    return panel("Compare results",children);
  }
  if(left!==right&&left.result.kind==="spell_curve"&&right.result.kind==="spell_curve"){
    const axis=left.result.axis, rightByValue=new Map(right.result.candidates.map(p=>[p[axis],p.metrics]));
    const delta=(a,b)=>Number.isFinite(a)&&Number.isFinite(b)?b-a:null;
    children.push(el("h3","Fixed recipes","gap"),table(["Search","Recipe"],
      [left,right].map(a=>[a.label||a.action,JSON.stringify(a.request.spell)])),
      el("h3","Matched scaling points","gap"),table([pretty(axis),"First DPS","Second DPS","DPS difference","Damage/SP difference"],
        left.result.candidates.filter(p=>rightByValue.has(p[axis])).map(p=>{
          const other=rightByValue.get(p[axis]);
          return [p[axis],p.metrics.dps,other.dps,delta(p.metrics.dps,other.dps),delta(p.metrics.damage_per_sp,other.damage_per_sp)];
        })));
    return panel("Spell scaling comparison",children);
  }
  const rows=[...resultRows(left.result),...(left===right?[]:resultRows(right.result))];
  const axes=commonAxes(rows),i=Math.min(state.point||0,rows.length-1);
  const updatePoint=n=>{state.point=n;refresh();};
  const x=axes.includes(state.x)?state.x:axes[1]??axes[0],y=axes.includes(state.y)?state.y:axes[0];
  if(axes.length>=2){
    for(const [key,value] of [["x",x],["y",y]])controls.append(field(key.toUpperCase()+" axis",select(axes.map(a=>[a,pretty(a)]),value,v=>{state[key]=v;refresh();})));
    children.push(graph(rows,x,y,i,updatePoint));
  }
  const page=Math.floor(i/50)*50,firstCount=resultRows(left.result).length;
  children.push(table(["Search","Option",...axes.slice(0,4).map(pretty)],rows.slice(page,page+50).map((r,k)=>{
    const idx=page+k,button=action(nameOf(r,idx),()=>updatePoint(idx));button.setAttribute("aria-pressed",String(idx===i));
    return [idx<firstCount?"First":"Second",button,...axes.slice(0,4).map(a=>metrics(r)[a])];
  })));
  if(page>0)children.push(action("Previous 50",()=>updatePoint(page-1)));
  if(page+50<rows.length)children.push(action("Next 50",()=>updatePoint(page+50)));
  const first=rows[0],current=rows[i];
  children.push(el("h3","Selected option","gap"),table(["Metric","First option","Selected","Difference"],
    axes.filter(a=>Number.isFinite(metrics(first)[a])&&Number.isFinite(metrics(current)[a])).map(a=>{
      const baseline=metrics(first)[a],picked=metrics(current)[a];return [pretty(a),baseline,picked,picked-baseline];
    })),...candidateDetails(current),disclosure("Complete selected option",current));
  const saved=i<firstCount?left:right;
  if(saved.result.kind==="lifecycle"&&saved.ruleset_hash===meta.ruleset_hash&&buildFamily(saved.result,current,meta.catalog)){
    children.push(...buildDetails(saved.result,current,meta.catalog),
      action("Export game class",()=>location.assign("/api/library/export?"+new URLSearchParams({id:saved.id,family:current.family}))));
  }
  return panel("Frontier comparison",children);
}
