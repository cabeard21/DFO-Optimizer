import {el,field,select,pretty,table} from "./view.js";
import {control,fold} from "./editor.js";

const objectives=[
  ["overall_pve","Overall PvE caster discovery"],["endgame_damage","Endgame direct damage"],
  ["encounter_damage","Encounter damage"],["clear_performance","Clear performance"],
  ["damage_per_sp","Damage per spell point"],["resource_sustain","Resource sustain"],
  ["survivability","Survivability"],["progression_effort","Progression effort"],["pareto","Pareto exploration"]
];
const encounterOnly=new Set(["encounter_damage","clear_performance","resource_sustain","survivability"]);
const attributes=["strength","intelligence","willpower","agility","endurance","personality","speed","luck"];

function check(label,active,toggle){
  const body=el("label",null,"race-choice"),input=el("input");
  input.type="checkbox";input.checked=active;
  input.addEventListener("change",()=>toggle(input.checked));
  body.append(input,el("span",label));return body;
}
function membership(values,value,selected){
  return selected?[...values.filter(v=>v!==value),value]:values.filter(v=>v!==value);
}
function numberField(label,value,apply,min,max,step=1){
  const box=control(label,value,apply,"number"),input=box.querySelector("input");
  input.min=min;input.max=max;input.step=step;
  return box;
}
function locks(query,catalog,setQuery){
  const names=catalog.skills.map(s=>[s.name,s.name]);
  const traitControls=catalog.traits.map(trait=>{
    const key=[trait.primary,trait.secondary].filter(Boolean).join("/");
    const required=query.required_traits??[],excluded=query.excluded_traits??[];
    return field(pretty(key.replace("/"," / "))+" ("+(trait.cost>=0?"+":"")+trait.cost+")",
      select([["eligible","Eligible"],["require","Require"],["exclude","Exclude"]],
        required.includes(key)?"require":excluded.includes(key)?"exclude":"eligible",
        v=>setQuery({required_traits:membership(required,key,v==="require"),excluded_traits:membership(excluded,key,v==="exclude")})));
  });
  const schoolNames=catalog.skills.filter(s=>s.magic).map(s=>s.name);
  const required=(query.required_masteries??schoolNames).map(value=>catalog.skills.find(s=>s.id===value)?.name??value);
  const groups=["primary","major","minor"];
  const skillControls=groups.flatMap(group=>Array.from({length:group==="minor"?6:3},(_,i)=>{
    const key=group+"_"+(i+1),current=query.skill_locks??{},currentName=catalog.skills.find(s=>s.id===current[key])?.name??current[key];
    return field(pretty(key),select([["","Automatic"],...names],currentName??"",value=>{
      const updated={...current};if(value)updated[key]=value;else delete updated[key];
      setQuery({skill_locks:updated});
    }));
  }));
  return [
    fold("Mastery requirements",[
      el("p","Eligible together at mastery quotas of three primary, two major and one minor skill.","note"),
      ...schoolNames.map(name=>check(name,required.includes(name),active=>setQuery({required_masteries:membership(required,name,active)})))
    ]),
    fold("Skill slot locks",skillControls),
    fold("Skill requirements",catalog.skills.map(s=>{
      const namesFor=key=>(query[key]??[]).map(v=>catalog.skills.find(row=>row.id===v)?.name??v);
      const req=namesFor("required_skills"),exc=namesFor("excluded_skills");
      return field(s.name,select([["eligible","Eligible"],["require","Require"],["exclude","Exclude"]],
        req.includes(s.name)?"require":exc.includes(s.name)?"exclude":"eligible",
        v=>setQuery({required_skills:membership(req,s.name,v==="require"),excluded_skills:membership(exc,s.name,v==="exclude")})));
    })),
    fold("Advantages and disadvantages",traitControls)
  ];
}

function gear(req,change){
  const domain=req.equipment??{},offers=domain.offers??[];
  return fold("Gear assumptions",[
    ...offers.map((offer,index)=>{
      const acq=offer.acquisition??{};
      const label=offer.instance_id+" · "+(acq.owned?"owned":(acq.price?.gold??"unknown")+" gold");
      if(acq.owned)return el("p",label);
      return check(label,acq.obtainable===true,active=>change({...req,equipment:{...domain,
        offers:offers.map((entry,i)=>i===index?{...entry,acquisition:{...acq,obtainable:active}}:entry)}}));
    }),
    ...offers.filter(o=>o.acquisition?.source).map(o=>el("p",o.acquisition.source,"note")),
    ...(!offers.length?[el("p","The scenario declares no purchase offers.","note")]:[]),
    control("Total gold ceiling (blank for available funds)",req.budget_gold??"",value=>{
      const updated={...req};
      if(value==="")delete updated.budget_gold;
      else if(/^\d+$/.test(value)&&Number.isSafeInteger(Number(value)))updated.budget_gold=Number(value);
      else throw Error("Enter a nonnegative whole gold amount.");
      change(updated);
    })
  ]);
}

function opportunities(req,catalog,change){
  const plan=req.progression,policy=plan?.itinerary;
  if(!policy)return [];
  const patch=values=>change({...req,progression:{...plan,itinerary:{...policy,...values}}});
  const intelligence=[1,6,4,2,0,3,5,7],speed=[6,1,4,2,0,3,5,7];
  const allocations={both:[intelligence,speed],intelligence:[intelligence],speed:[speed]};
  const actual=JSON.stringify([policy.allocation_order,...(policy.alternate_allocation_orders??[])]);
  const mode=Object.keys(allocations).find(k=>JSON.stringify(allocations[k])===actual)??"custom";
  const options=[["both","Explore Intelligence-first and Speed-first"],["intelligence","Lock Intelligence-first"],["speed","Lock Speed-first"]];
  if(mode==="custom")options.push(["custom","Imported allocation orders"]);
  const skillName=v=>catalog.skills.find(s=>s.id===v)?.name??v;
  return [fold("Progression assumptions",[
    el("p",policy.evidence,"note"),
    numberField("Training circuits available",policy.cycles,v=>patch({cycles:v}),1,4000),
    numberField("Time per qualifying activity (ms)",policy.cadence_ms,v=>patch({cadence_ms:v}),1400,1000000),
    numberField("Practice challenge level",policy.challenge_level,v=>patch({challenge_level:v}),0,2000),
    numberField("Spell Maker price factor",policy.maker_price_factor,v=>patch({maker_price_factor:v}),0.01,100,0.01),
    numberField("Hypothetical gold cache after birth",policy.cache_gold,v=>patch({cache_gold:v}),0,Number.MAX_SAFE_INTEGER),
    field("Level-up attribute allocation",select(options,mode,key=>{
      const [order,...others]=allocations[key];patch({allocation_order:order,alternate_allocation_orders:others});
    })),
    control("Mastery priority (ordered skill names, blank for scenario default)",(policy.mastery_priority??[]).map(skillName).join(", "),text=>{
      const names=text.trim()?text.split(",").map(s=>s.trim().toLowerCase()):[];
      const skills=names.map(name=>catalog.skills.find(s=>s.name.toLowerCase()===name)?.name);
      if(skills.includes(undefined)||new Set(skills).size!==skills.length)throw Error("Enter distinct catalog skill names separated by commas.");
      patch({mastery_priority:skills});
    }),
    el("p",policy.specialization?"Conditional specialization · "+policy.specialization.path:
      "The itinerary leaves specialization unselected. The full request can supply a path and a separate signature spell offer.","note")
  ])];
}

function comparisons(req,change){
  const families=req.families??[];
  const baselines=[["m1-breton-caster","Breton caster"],["comparison-high-elf-caster","High Elf caster"]];
  return fold("Comparison classes",[
    ...baselines.map(([baseline,label])=>check(label,families.some(f=>f.baseline_id===baseline),active=>{
      const next=active?[...families,{id:baseline,baseline_id:baseline}]:families.filter(f=>f.baseline_id!==baseline);
      change({...req,families:next});
    })),
    ...(families.length?[table(["Family","Source"],families.map(f=>[f.id,f.baseline_id??"Imported class"]))]:[])
  ]);
}

function thoroughness(req,change,defaults){
  const {nodes,panel}=defaults??{nodes:1_000_000,panel:8};
  const choices=[
    {id:"quick",label:"Quick · 30 seconds",wall:30,nodes:Math.max(1,Math.floor(nodes/4)),panel:Math.max(1,Math.floor(panel/2))},
    {id:"standard",label:"Standard · 2 minutes",wall:120,nodes,panel},
    {id:"thorough",label:"Thorough · 10 minutes",wall:600,nodes:Math.min(Number.MAX_SAFE_INTEGER,nodes*5),panel:Math.min(10000,panel*2)}
  ];
  const chosen=choices.find(c=>c.nodes===req.search?.max_nodes&&c.wall===req.search?.wall_seconds&&c.panel===req.class_search.top_k);
  const options=choices.map(c=>[c.id,c.label]);
  if(!chosen)options.push(["custom","Custom budget"]);
  return field("Search thoroughness",select(options,chosen?.id??"custom",key=>{
    const choice=choices.find(c=>c.id===key);
    if(choice)change({...req,search:{...req.search,max_nodes:choice.nodes,wall_seconds:choice.wall},
      class_search:{...req.class_search,top_k:choice.panel}});
  }));
}

export function discoveryEditor(req,catalog,change,defaults){
  const query=req.class_search;
  if(!query)return [el("p","Choose a discovery preset or open a request with a class search.","warning")];
  const setQuery=patch=>change({...req,class_search:{...query,...patch}});
  const setBudget=patch=>change({...req,search:{...req.search,...patch}});
  const races=query.race_ids??catalog.races.map(r=>r.id);
  const choices=objectives.filter(([id])=>req.encounter?id!=="endgame_damage":!encounterOnly.has(id));
  const assumptions=[req.description,req.encounter?.evidence,req.encounter?.scenario?.evidence].filter(Boolean);
  const classControls=[
    numberField("Required class health",query.hp_values?.[0]??30,v=>setQuery({hp_values:[v]}),4,30),
    field("Advancement difficulty",select(Array.from({length:53},(_,i)=>[String(i-12),(i-12)+" points · "+(0.30+2.70*i/52).toFixed(2)+"×"]),
      String(query.difficulty_points??-12),v=>setQuery({difficulty_points:Number(v)}))),
    field("Magery",select([["any","Any legal multiplier"],...[0.5,1,1.5,1.75,2,3].map(n=>[String(n),n+" × Intelligence"])],
      query.magicka_multiplier===null?"any":String(query.magicka_multiplier??3),v=>setQuery({magicka_multiplier:v==="any"?null:Number(v)}))),
    check("Require casting in daylight and darkness",query.require_day_and_night_casting??true,v=>setQuery({require_day_and_night_casting:v})),
    check("Allow high-risk disadvantages",query.allow_high_risk_disadvantages??false,v=>setQuery({allow_high_risk_disadvantages:v})),
    fold("Eligible races",catalog.races.map(r=>check(r.name,races.includes(r.id),v=>setQuery({race_ids:membership(races,r.id,v)})))),
    fold("Attribute domains",[
      numberField("Coarse attribute step",query.attribute_grid_step??10,v=>setQuery({attribute_grid_step:v}),1,65),
      ...attributes.map(name=>control(pretty(name)+" values (blank for automatic)",query.attribute_domains?.[name]?.join(", ")??"",text=>{
        const domains={...query.attribute_domains};
        if(text.trim()){
          const values=text.split(",").map(s=>s.trim());
          if(!values.every(s=>/^\d+$/.test(s)&&Number(s)>=10&&Number(s)<=75))throw Error("Class attributes range from 10 to 75.");
          domains[name]=[...new Set(values.map(Number))];
        }else delete domains[name];
        setQuery({attribute_domains:domains});
      }))
    ]),...locks(query,catalog,setQuery)
  ];
  return [
    ...assumptions.map(s=>el("p",s,"note")),
    field("Optimization objective",select(choices,req.objective??"overall_pve",objective=>change({...req,objective}))),
    el("p",catalog.objective_definitions[req.objective??"overall_pve"],"note"),
    fold("Class decisions",classControls),
    ...opportunities(req,catalog,change),gear(req,change),
    thoroughness(req,change,defaults),
    field("Class admission strategy",select([["adaptive","Adaptive refinement"],["diverse","Mechanics-guided panel"],
      ["exhaustive","Exhaustive finite domain"],["examples","Diagnostic examples"]],req.class_admission_strategy??"adaptive",
      v=>change({...req,class_admission_strategy:v}))),
    fold("Computational budget",[
      numberField("Total search nodes",req.search?.max_nodes??100000,v=>setBudget({max_nodes:v}),1,Number.MAX_SAFE_INTEGER),
      numberField("Wall time in seconds",req.search?.wall_seconds??5,v=>setBudget({wall_seconds:v}),0,86400,0.1),
      numberField("Memory ceiling in MiB",(req.search?.memory_bytes??(128*1024*1024))/1048576,v=>setBudget({memory_bytes:v*1048576}),1,4096),
      numberField("Candidate panel size",query.top_k??20,v=>setQuery({top_k:v}),1,10000)
    ]),
    comparisons(req,change)
  ];
}
