import {action, disclosure, el, field, format, panel, pretty, select, table} from "./view.js";

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
  const controls = el("div", null, "beginner-controls");
  const frozen=s.request.schema_version!==2;
  const compare=Boolean(s.request.compare_slower);
  controls.append(thoroughness, action(compare?"Run saved comparison":"Recommend My First Spellcaster", submit, "primary"));
  if(frozen||compare)controls.append(action("Start a new 0.30× recommendation",()=>update({schema_version:2,thoroughness:s.request.thoroughness||"standard"})));
  const advanced = el("a", "Set your own class and scenario constraints");
  advanced.href = "#discovery";
  const body = [el("p","Compare spellcasters in solo fights from creation to level 45. Take the selected class file and its creation checklist into the game.","intro"),
                el("p",frozen?"This saved request uses its original rules.":compare?"This saved request compares slower classes.":"Requires 0.30× advancement.","note"),
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

const pathNames={none:"No path",battlemage:"Battlemage",battlemage_aegis:"Battlemage with Aegis Bolt",
  soulbinder:"Soulbinder",spellbreaker:"Spellbreaker",riftwalker:"Riftwalker"};
const stageNames={birth:"Creation",midgame:"Level 15",cap:"Level 45"};
const percent=v=>Number.isFinite(v)?format(100*v)+"%":"Unreported";

function spellMakerRecipes(row) {
  const example=row.progression?.rolls?.find(r=>r.seed===row.progression.representative_seed);
  const reach=["Self","Touch","Single target at range","Close area","Area at range"];
  const elements=["Fire","Frost","Poison","Shock","Magic"];
  const effects={"4,0":"Damage Health","10,8":"Heal Health","18,255":"Regeneration","35,255":"Shield"};
  const recipes=(example?.stages||[]).flatMap(stage=>(stage.spells||[]).filter(s=>Number.isFinite(s.gold)).map(s=>[
    stageNames[stage.stage],reach[s.range_type],elements[s.element],s.gold,s.effects.map(({effect_id,...settings})=>
      (effects[effect_id]||effect_id)+". "+Object.entries(settings).map(([key,value])=>pretty(key)+" "+value).join(", ")).join(" / ")
  ]));
  if(!recipes.length)return [];
  const box=el("details");
  box.append(el("summary","Tested Spell Maker recipes"),el("p","Buy only when you have access and enough gold. Prices use the scenario’s chapter multiplier.","note"),
    table(["Stage","Target","Element","Gold cost","Spell settings"],recipes));
  return [box];
}

function refinementEvidence(row) {
  const refinement=row.refinement;
  if(!refinement)return [];
  const gear=refinement.gear, arcane=refinement.arcane, children=[];
  if(arcane){
    const selected=pathNames[arcane.selected]||arcane.selected;
    children.push(el("p",arcane.selected==="none"?"Keep your arcane path open for now.":"After mastering its required schools, aim for "+selected+"."));
    const paths=Object.entries(arcane.paths||{});
    if(paths.length){
      const box=el("details");
      box.append(el("summary","Tested arcane paths at level 45"),
        table(["Path","Survived","Survived and cleared","Damage per second","Spell points spent / fight","Spell points restored / fight"],
          paths.map(([id,m])=>[pathNames[id]||id,percent(m.survival),percent(m.clear),m.dps,m.sp_spent,m.sp_restored])));
      if(arcane.coverage)box.append(el("p",arcane.coverage,"note"));
      children.push(box);
    }
  }
  if(gear){
    const rows=Object.keys(stageNames).flatMap(stage=>{
      const match=gear.same_spellbook?.[stage];
      return match?[[stageNames[stage],match.owned,match.representative]]:[];
    });
    if(gear.theoretical)rows.push(["Level 45 · theoretical catalog",null,gear.theoretical]);
    const box=el("details");
    box.append(el("summary","How equipment access changes fights"),
      el("p","The paired practical fights use the same spellbook. Gear access is hypothetical. The separate theoretical row also assumes access to the selected Spell Maker recipes.","note"),
      table(["Stage","Owned survival","Upgraded survival","Owned clear rate","Upgraded clear rate","Owned melee damage / fight","Upgraded melee damage / fight","Upgraded DPS"],
        rows.map(([stage,owned,upgraded])=>[stage,percent(owned?.survival),percent(upgraded?.survival),percent(owned?.clear),percent(upgraded?.clear),
          owned?.melee_damage,upgraded?.melee_damage,upgraded?.dps])));
    const backup=[];
    const names={owned:"Owned gear",representative:"Practical upgrades",theoretical:"Theoretical gear"};
    for(const [mode,stages] of Object.entries(gear.no_magicka||{})){
      for(const stage of Object.keys(stageNames)){
        const trial=stages[stage];
        if(trial?.status==="replayed")backup.push([stageNames[stage],names[mode]||mode,
          percent(trial.survival),percent(trial.clear),trial.melee_damage]);
      }
    }
    if(backup.length)box.append(el("h3","Backup weapon with no magicka"),
      table(["Stage","Gear access","Survived","Survived and cleared","Melee damage / fight"],backup));
    children.push(box);
  }
  return children.length?[panel("Gear and arcane path",[...children,...spellMakerRecipes(row)])]:[];
}

function raceEvidence(rows) {
  const matched=rows.filter(r=>r.status==="replayed"&&["submitted_archive","race_comparison"].includes(r.origin));
  if(!matched.length)return [];
  const losses=matched.map(r=>[r.race,r.refinement?.magic_pressure?.cap?.mean_hp_lost]);
  const least=Math.min(...losses.map(([,loss])=>Number.isFinite(loss)?loss:Infinity));
  const strongest=losses.filter(([,loss])=>loss===least).map(([race])=>race);
  const children=[el("p","This comparison keeps the submitted class choices fixed and changes only race.")];
  if(matched.length>1&&strongest.length===1)children.push(el("p",
    strongest[0]+" had the lowest mean health loss among these races in the capped hostile Magic test."));
  if(strongest.length>1)children.push(el("p",strongest.join(", ")+" tied for the lowest mean health loss in the capped hostile Magic test."));
  children.push(table(["Race","Survived and cleared","Level-cap DPS","Mean net HP loss in the capped Magic fight"],matched.map(r=>[
    r.race,metric(r,"mean_clear_rate","percent"),metric(r,"cap_damage_per_second"),r.refinement?.magic_pressure?.cap?.mean_hp_lost
  ])),el("p","Breton's magic resistance applies to the hostile Magic test. High Elf paralysis immunity and Wood Elf's bow bonus are outside these fights. The submitted Wood Elf uses Long Blade, so its short-blade bonus is outside this race comparison.","note"));
  return [panel("How race affects the choice",children)];
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

function slowerComparison(result) {
  const rows=result.slower_comparison||[];
  return [el("p","These alternatives trade faster leveling for possible equipment or defensive benefits. Your 0.30× recommendation stays available.","note"),
    ...(rows.length?[table(["Build","Advancement","Compatible metals","Survived","Survived and cleared","Level-cap DPS","Practice to cap","Status"],
      rows.map(r=>[
        r.race+" · "+(r.origin==="fast_reference"?"Your 0.30× reference":
          r.origin?.includes("_keeps_")?"Keeps "+r.origin.split("_keeps_")[1]:label(r)),
        metric({metrics:r.permanent},"advancement_multiplier","multiplier"),
        metric(r,"plate_weapon_materials"), metric(r,"mean_survival_rate","percent"),metric(r,"mean_clear_rate","percent"),
        metric(r,"cap_damage_per_second"),metric(r,"mean_practice"),r.reason||"Replayed"
      ]))]:[el("p","No slower build finished the common comparison panel.","note")])];
}

function slowerJob(job,handlers) {
  if(!job)return [];
  const children=[el("p",job.error||job.state,"state")];
  if(job.result)children.push(...slowerComparison(job.result),action("Export slower comparison",handlers.exportComparison));
  if(!["completed","cancelled","failed"].includes(job.state))children.push(action("Cancel comparison",handlers.cancelComparison));
  const box=panel("Advancement comparison",children);
  box.dataset.comparisonJobId=job.id;
  box.dataset.state=job.state;
  return [box];
}
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
  if(result.frozen_request?.compare_slower){
    area.append(panel("Advancement comparison",slowerComparison(result)),...notes("Limits of this comparison",result.limitations));
    return area;
  }
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
    if(handlers.compareSlower&&row.metrics?.advancement_multiplier===0.30){
      const compare=action("Compare slower builds",()=>handlers.compareSlower(row));
      compare.disabled=Boolean(session.comparing);
      controls.append(compare);
    }
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
                             ...refinementEvidence(row),compareBuild(row,compared),...scenarioEvidence(row));
  }
  if(selector)area.append(selector);
  area.append(selected);choose(initial);
  area.append(...slowerJob(session.comparisonJob,handlers));
  area.append(...raceEvidence(compared));
  area.append(...sensitivityPanel(result,compared));
  area.append(...notes("Scenario assumptions",result.assumptions),...notes("Limits of this recommendation",result.limitations));
  if(result.diagnostics)area.append(disclosure("Search diagnostics",result.diagnostics));
  return area;
}
