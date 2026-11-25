import {action,disclosure,el,facts,field,format,graph,metrics,nameOf,panel,pretty,replayAction,resultRows,select,table} from "./view.js";
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
  const usePreview=Boolean(job.incumbent&&(!job.result||job.state==="cancelled"&&!resultRows(job.result).length));
  const result=usePreview?job.incumbent:job.result;
  const head=[el("span",pretty(job.state),"state")];
  if(!completed)head.push(action("Cancel search",handlers.cancel));
  const toolbar=el("div",null,"row");toolbar.append(...head);
  const children=[toolbar];
  if(job.error)children.push(el("p",job.error,"warning"));
  if(session.changed)children.push(el("p","Inputs have changed since this search was submitted.","warning"));
  if(job.progress?.phase&&!job.result)children.push(el("p",pretty(job.progress.phase),"note"));
  if(!result)return panel("Search progress",children);
  if(usePreview)children.push(el("p",completed?"Last independently validated preview.":"First validated result. Search is running.","note"),
    action("Export validated preview",handlers.exportPreview));
  const rows=resultRows(result);
  children.push(facts({status:result.status??(result.valid===true?"Verified":"Available"),
    termination:result.termination??job.state,retained:rows.length,
    ...(result.counters?.nodes!==undefined?{nodes:result.counters.nodes}:{}),
    ruleset:(result.ruleset_hash??job.ruleset_hash??"Unknown").slice(0,12)}));
  children.push(...warningList([result.blockers,result.first_gap,result.unsupported_mechanics,result.missing_observations]));
  if(result.proof_scope)children.push(disclosure("Search scope",result.proof_scope));
  if(result.assumptions||result.scenario)children.push(disclosure("Encounter assumptions",result.assumptions??result.scenario));
  if(!rows.length){
    children.push(disclosure("Result details",result)); 
  }else{
    const i=Math.min(Math.max(0,session.index||0),rows.length-1),row=rows[i];
    const axes=commonAxes(rows);
    const pick=(n)=>{session.index=n;handlers.refresh();};
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
      const button=action(nameOf(r,start+k),()=>pick(start+k));
      button.setAttribute("aria-pressed",String(i===start+k));
      return [button,...axes.slice(0,3).map(a=>metrics(r)[a])];
    })));
    children.push(el("h3","Selected option","gap"),facts(metrics(row)),...candidateDetails(row),disclosure("Complete selected option",row));
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
export function comparePane(archives,state,refresh){
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
  return panel("Frontier comparison",children);
}
