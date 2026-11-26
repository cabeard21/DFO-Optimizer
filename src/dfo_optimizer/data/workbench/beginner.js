import {action, disclosure, el, field, format, panel, select, table} from "./view.js";

const metrics = [
  ["worst_clear_rate", "Lowest scenario clear rate", "percent"],
  ["worst_survival_rate", "Lowest scenario survival rate", "percent"],
  ["mean_clear_rate", "Average clear rate", "percent"],
  ["min_hp_fraction", "Lowest remaining health", "percent"],
  ["mean_censored_clear_fraction", "Average share of the time limit used", "percent"],
  ["cap_damage_per_second", "Level-cap damage per second"],
  ["mean_damage_per_sp", "Average damage per spell point"],
  ["mean_practice", "Average practice effort"],
  ["plate_weapon_materials", "Equipment material coverage"],
  ["advancement_multiplier", "Advancement multiplier", "multiplier"]
];

export function beginnerInputs(s, submit, update) {
  const thoroughness = field("Search thoroughness", select([
    ["quick","Quick"],["standard","Standard"],["thorough","Thorough"]
  ], s.request.thoroughness, value=>update({...s.request, thoroughness:value})));
  const fast = el("input");
  fast.type="checkbox";
  fast.checked=s.request.require_fast_advancement===true;
  fast.addEventListener("change",()=>update({...s.request, require_fast_advancement:fast.checked}));
  const advancement=field("Require 0.30× advancement",fast);
  const controls = el("div", null, "beginner-controls");
  controls.append(thoroughness, advancement, action("Recommend My First Spellcaster", submit, "primary"));
  const advanced = el("a", "Set your own class and scenario constraints");
  advanced.href = "#discovery";
  const body = [el("p","Compare spellcasters in solo fights from creation to level 45. Take the selected class file and its creation checklist into the game.","intro"),
                controls, advanced];
  return panel("Start a new spellcaster", body);
}

function label(row) {
  const name=row.label||row.name||row.class?.name;
  if(name&&name!=="DFO class")return name;
  const skills=row.class?.skills?.primary||[];
  return skills.length?skills.join(" / "):row.id;
}
function metric(row, key, unit) {
  const value = row.metrics?.[key];
  if (!Number.isFinite(value)) return "Unreported";
  if (unit === "percent") return format(100*value)+"%";
  if (unit === "multiplier") return format(value)+"×";
  return format(value);
}

function guideCard(row) {
  const box=el("article", null, "creation-guide");
  box.append(el("h3","Your creation checklist"),el("p",label(row)+" · "+row.race,"guide-byline"));
  if(row.progression?.representative_seed!=null)
    box.append(el("p","Development example for birth seed "+row.progression.representative_seed+".","note"));
  const list=el("ol",null,"guide-steps");
  for (const section of row.guide?.sections || []) {
    const li=el("li"), text=el("div");
    text.append(el("h4",section.title));
    for (const sentence of section.items) text.append(el("p",sentence));
    li.append(text);list.append(li);
  }
  box.append(list);
  return box;
}

function printGuide(card) {
  document.getElementById("print-checklist")?.remove();
  const copy=card.cloneNode(true);
  copy.id="print-checklist";
  document.body.append(copy);
  const cleanup=()=>copy.remove();
  window.addEventListener("afterprint",cleanup,{once:true});
  window.print();
}

function notes(title, contents) {
  const rows = (Array.isArray(contents)?contents:contents?[contents]:[]).filter(s=>typeof s==="string" && s);
  if (!rows.length) return [];
  const container=el("details");container.append(el("summary",title));
  const list=el("ul");
  for (const s of rows) list.append(el("li",s));
  container.append(list);
  return [container];
}

function buildLabel(row) {
  return [row.role || row.origin, row.race, label(row)].filter(Boolean).join(" · ");
}

function compareBuild(row, rows) {
  const peers=rows.filter(r=>r.id!==row.id), area=el("div"), body=el("div");
  function show(index) {
    const other=peers[index];
    const header=["Measured outcome", "Selected build", ...(other?["Comparison build"]:[])];
    const differences=metrics.map(([key,title,unit])=>[
      title,metric(row,key,unit),...(other?[metric(other,key,unit)]:[])
    ]);
    const children=[table(header,differences)];
    if(other?.reason)children.unshift(el("p",String(other.reason).replaceAll("_"," "),"note"));
    if(other?.tradeoff)children.push(el("p",other.tradeoff,"note"));
    body.replaceChildren(...children);
  }
  if(peers.length)area.append(field("Compare with",select(peers.map((r,i)=>[String(i),buildLabel(r)]),"0",v=>show(Number(v)))));
  show(0);area.append(body);
  return panel("Measured comparisons",[area]);
}

const cases={
  ordinary:"ordinary opponents", physical:"melee pressure", enemy_caster:"enemy spellcaster",
  resistant:"high resistance", multiple:"multiple opponents", low_sp:"low spell points",
  sustained:"sustained clearing", defensive:"defensive casting"
};
const variants={
  baseline:"baseline conditions", owned_only:"owned gear only", no_spell_purchase:"no spell purchase",
  higher_pressure:"higher incoming pressure", protected_recovery:"protected recovery"
};

function weakest(row){
  const counts=new Map();
  for(const t of row.outcomes||[]){
    if(t.status!=="replayed")continue;
    const name=[cases[t.scenario]||t.scenario,t.stage,variants[t.variant]||t.variant].join(" · ");
    const group=counts.get(name)||{name,total:0,success:0};
    group.total++;group.success+=Number(t.cleared&&t.survived);counts.set(name,group);
  }
  const sorted=[...counts.values()].sort((a,b)=>a.success/a.total-b.success/b.total);
  if(!sorted.length)return [];
  const [worst]=sorted, same=sorted.filter(g=>g.success*worst.total===worst.success*g.total);
  return [el("p","The lowest clear rate occurred for "+worst.name+". Survived and cleared "+worst.success+" of "+worst.total+
    " fights."+(same.length>1?" "+(same.length-1)+" other conditions shared that clear rate.":""))];
}

function sensitivityPanel(result,rows){
  const changes=result.sensitivity||[];
  const summary=result.sensitivity_notes;
  const guidance=typeof summary==="string"?[summary]:Array.isArray(summary)?summary:[];
  const children=guidance.map(v=>el("p",v));
  if(changes.length){
    const name=id=>rows.find(r=>r.id===id);
    children.push(table(["Change to assumptions","Selected under that change","Changed selection"],changes.map(change=>{
      const r=name(change.variant_family);
      return [variants[change.variant]||change.variant,r?buildLabel(r):change.variant_family,change.winner_changed?"Yes":"No"];
    })));
  }
  return children.length?[panel("How the choice changes",children)]:[];
}

function scenarioEvidence(row) {
  const trials=(row.outcomes||[]).filter(t=>t.status==="replayed");
  if(!trials.length)return [];
  const tested=[...new Set(trials.map(t=>t.variant))], box=el("details"), summary=el("div");
  function show(variant) {
    const groups=new Map();
    for(const t of trials.filter(t=>t.variant===variant)){
      const id=(cases[t.scenario]||t.scenario)+" / "+t.stage;
      const g=groups.get(id)||{count:0,cleared:0,survived:0,seconds:0,minimum:Infinity,healing:0,mitigated:0,melee:0};
      g.count++;g.cleared+=Number(t.cleared&&t.survived);g.survived+=Number(t.survived);
      g.seconds+=t.censored_clear_us/1000000;g.minimum=Math.min(g.minimum,t.minimum_hp);
      g.healing+=t.healing||0;g.mitigated+=t.mitigated||0;g.melee+=t.physical_damage||0;
      groups.set(id,g);
    }
    summary.replaceChildren(table(["Scenario / stage","Survived and cleared","Survived","Mean time (s)","Lowest HP","Healing / fight","Mitigation / fight","Melee damage / fight"],
      [...groups].map(([name,g])=>[name.replaceAll("_"," "),g.cleared+"/"+g.count,g.survived+"/"+g.count,
                                   format(g.seconds/g.count),g.minimum,g.healing/g.count,g.mitigated/g.count,g.melee/g.count])));
  }
  const first=tested.includes("baseline")?"baseline":tested[0];
  box.append(el("summary","Encounter outcomes by stage"));
  if(tested.length>1)box.append(field("Encounter assumptions",select(tested.map(v=>[v,variants[v]||v]),first,show)));
  show(first);box.append(el("p","Unfinished encounters count for their whole time limit.","note"),summary);
  return [box];
}

export function recommendationPane(result, handlers, session={}) {
  const area=el("div",null,"recommendation");
  const choices=[result.recommendation,...(result.alternatives||[])].filter(Boolean);
  if (!choices.length) {
    const reasons=(result.comparisons||[]).filter(r=>r.reason);
    area.append(panel("No qualifying recommendation",[
      el("p","The search did not produce a class with the required evidence.","note"),
      ...(reasons.length?[table(["Build","First missing requirement"],reasons.map(r=>[buildLabel(r),String(r.reason).replaceAll("_"," ")]))]:[]),
      ...notes("Limitations",result.limitations)
    ]));
    return area;
  }
  const selected=el("div");
  const initial=Math.max(0,choices.findIndex(r=>r.id===session.selectedRecommendation));
  const selector=choices.length>1?field("View a build",select(choices.map((r,i)=>[
    String(i),(i===0?"Recommended":r.role||"Alternative "+i)+" · "+r.race+" · "+label(r)
  ]),String(initial),v=>choose(Number(v)))):null;
  const rows=[...choices,...(result.comparisons||[]).filter(r=>!choices.some(p=>p.id===r.id))];
  const compared=Array.from(new Map(rows.map(r=>[r.id,r])).values());
  function choose(index) {
    const row=choices[index], card=guideCard(row);
    session.selectedRecommendation=row.id;
    const controls=el("div",null,"actions");
    controls.append(action("Download game class",()=>handlers.exportFamily(row.id),"primary"),
                    action("Download checklist",()=>handlers.exportChecklist(row.id)),
                    action("Print checklist",()=>printGuide(card)));
    const body=[];
    body.push(el("h3",row.race+" · "+label(row)));
    if(result.summary && typeof result.summary==="string" && index===0)body.push(el("p",result.summary));
    if(row.tradeoff) body.push(el("p",row.tradeoff));
    body.push(...weakest(row));
    body.push(controls,card);
    const paths=row.guide?.specialization_reference||[];
    if(paths.length){
      const reference=el("details");
      reference.append(el("summary","All earned arcane paths"),table(["Path","Required mastered skills","Signature spell"],
        paths.map(p=>[p.path,p.masteries.join(" + "),p.signature])));
      body.push(reference);
    }
    selected.replaceChildren(panel(index===0?"Recommended build":row.role||"Alternative build",body),
                             compareBuild(row,compared),...scenarioEvidence(row));
  }
  if(selector)area.append(selector);
  area.append(selected);choose(initial);
  area.append(...sensitivityPanel(result,compared));
  area.append(...notes("Scenario assumptions",result.assumptions),...notes("Limits of this recommendation",result.limitations));
  if(result.diagnostics)area.append(disclosure("Search diagnostics",result.diagnostics));
  return area;
}
