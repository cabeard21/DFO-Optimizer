import {el,field,select,pretty} from "./view.js";
import {parseDocument,stringifyDocument} from "./exact-json.js";

const attributes=["strength","intelligence","willpower","agility","endurance","personality","speed","luck"];
const defaultSkills=[22,0,20,23,16,17,1,3,13,14,18,21];
const numericList = text => {
  if (!text.trim()) return [];
  const values=text.split(",").map(t=>t.trim());
  if(values.some(v=>!/^[-+]?\d+$/.test(v)))throw Error("Enter whole numbers separated by commas.");
  return values.map(Number);
};
export function control(label,value,apply,type="text"){
  const input=el("input");input.type=type;input.value=value;
  input.addEventListener("change",()=>{
    try{
      if(type==="number"&&(input.value===""||!Number.isFinite(input.valueAsNumber)))throw Error("Enter a number.");
      apply(type==="number"?input.valueAsNumber:input.value);input.setCustomValidity("");
    }catch(error){input.setCustomValidity(error.message);input.reportValidity();}
  });
  return field(label,input);
}
function properties(label,value,update){
  const area=el("textarea",null,"mono");area.rows=4;area.value=stringifyDocument(value,2);
  area.addEventListener("change",()=>{
    try{const parsed=parseDocument(area.value);update(parsed);area.setCustomValidity("");}
    catch(error){area.setCustomValidity(error.message);area.reportValidity();}
  });
  return field(label,area);
}
export function fold(label,children){
  const details=el("details");details.append(el("summary",label),...children);return details;
}
export function importedClass(doc,catalog,original){
  const bySkill=new Map(catalog.skills.map(s=>[s.name,s.id]));
  const traits=[...doc.advantages,...doc.disadvantages].map(t=>catalog.traits.find(x=>
    x.primary===t.primary&&(x.secondary||"")===(t.secondary||""))?.id);
  const skills=["primary","major","minor"].flatMap(group=>doc.skills[group].map(s=>[bySkill.get(s)]));
  if(traits.some(v=>v===undefined)||skills.some(([v])=>v===undefined))throw Error("The class has unknown traits or skills.");
  return {...original,hp_values:[doc.hitPointsPerLevel],attribute_domains:Object.fromEntries(
    Object.entries(doc.attributes).map(([key,value])=>[key,[value]])),
    skill_domains:skills,trait_ids:traits,required_trait_ids:traits};
}
function creator(req,catalog,change){
  const children=[];
  const entries=(rows,ids)=>rows.filter(r=>ids.includes(r.id)).map(r=>r.name).join(", ");
  const list=(label,key,defaults)=>control(label,(req[key]??defaults).join(", "),v=>change({...req,[key]:numericList(v)}));
  children.push(field("Objective",select([["max_intelligence","Highest Intelligence"],["examples","Legal class examples"]],
    req.objective??"examples",v=>change({...req,objective:v}))));
  const races=el("fieldset",null,"race-set"), choices=el("div",null,"race-choices");
  const eligible=req.race_ids??catalog.races.map(r=>r.id);
  races.append(el("legend","Eligible races"));
  for(const race of catalog.races){
    const option=el("label",null,"race-choice"), check=el("input");
    check.type="checkbox";check.checked=eligible.includes(race.id);
    check.addEventListener("change",()=>change({...req,race_ids:check.checked?[...eligible,race.id].sort((a,b)=>a-b):eligible.filter(x=>x!==race.id)}));
    option.append(check,el("span",race.name));choices.append(option);
  }
  races.append(choices);children.push(races);
  children.push(list("HP settings","hp_values",[30]));
  children.push(field("Magery requirement",select([["any","Any legal multiplier"],
    ...[0.5,1,1.5,1.75,2,3].map(v=>[String(v),v+" × Intelligence"])],
    req.magicka_multiplier===null?"any":String(req.magicka_multiplier??3),
    v=>change({...req,magicka_multiplier:v==="any"?null:Number(v)}))));
  children.push(control("Required difficulty",req.difficulty_points??-12,v=>change({...req,difficulty_points:v}),"number"));
  children.push(fold("Attribute domains",attributes.map(name=>control(pretty(name),
    (req.attribute_domains?.[name]??[50]).join(", "),v=>change({...req,attribute_domains:{...req.attribute_domains,[name]:numericList(v)}})))));
  const skills=req.skill_domains??defaultSkills.map(n=>[n]);
  children.push(fold("Skill slots",skills.map((ids,i)=>control(
    (i<3?"Primary "+(i+1):i<6?"Major "+(i-2):"Minor "+(i-5))+" · "+entries(catalog.skills,ids),
    ids.join(", "),v=>change({...req,skill_domains:skills.map((s,j)=>j===i?numericList(v):s)})))));
  children.push(fold("Trait locks and IDs",[list("Required trait IDs","required_trait_ids",[]),
    list("Eligible trait IDs","trait_ids",catalog.traits.map(t=>t.id)),
    el("p",catalog.traits.map(t=>t.id+" "+t.primary+(t.secondary?" / "+t.secondary:"")).join(" · "),"note")]));
  const constraints=[["require_day_and_night_casting","Require casting in daylight and darkness",true],
    ["require_magic_school","Require a magic school",true],["allow_high_risk_disadvantages","Allow high-risk disadvantages",false]];
  children.push(fold("Casting and disadvantage constraints",constraints.map(([key,title,fallback])=>{
    const line=el("label",null,"race-choice"),box=el("input");
    box.type="checkbox";box.checked=req[key]??fallback;
    box.addEventListener("change",()=>change({...req,[key]:box.checked}));line.append(box,el("span",title));return line;
  })));
  return children;
}
function gear(req,catalog,change){
  const children=[];
  if(req.mode==="owned_plus_budget")children.push(control("Gold budget",req.budget?.gold??0,
    v=>change({...req,budget:{...req.budget,gold:v}}),"number"));
  const items=[...(req.inventory??[]),...(req.offers??[])].map(item=>item.instance_id).filter(Boolean);
  if(items.length){
    const locks=req.locks??{};
    children.push(fold("Equipment locks",Object.keys(catalog.slots).map(slot=>
      field(slot,select([["*","Available"],["","Keep empty"],...items.map(id=>[id,id])],
        Object.hasOwn(locks,slot)?(locks[slot]??""):"*",v=>{
          const next={...locks};if(v==="*")delete next[slot];else next[slot]=v||null;
          change({...req,locks:next});
        })))));
  }
  return children;
}
export function editors(view,req,catalog,change){
  if(view==="creator")return creator(req,catalog,change);
  const children=view==="gear"?gear(req,catalog,change):[];
  if(req.curve){
    const axes=[["level","Level"],["destruction_live","Live Destruction"],["destruction_trained","Earned Destruction"]];
    children.push(field("Scaling axis",select(axes,req.curve.axis,v=>change({...req,curve:{
      axis:v,values:v==="level"?[1,5,10,15,20,25,30,35,40,45]:[25,50,75,100,125,150,175,200]}}))),
      control("Values to measure",req.curve.values.join(", "),v=>change({...req,curve:{...req.curve,values:numericList(v)}})));
  }
  if(req.caster)for(const [key,label] of [["level","Caster level"],["current_sp","Available SP"],["destruction_live","Live Destruction"],["destruction_trained","Trained Destruction"]])
    if(typeof req.caster[key]==="number")children.push(control(label,req.caster[key],v=>change({...req,caster:{...req.caster,[key]:v}}),"number"));
  if(req.target)for(const [key,label] of [["hp","Target HP"],["willpower","Target Willpower"]])
    if(typeof req.target[key]==="number")children.push(control(label,req.target[key],v=>change({...req,target:{...req.target,[key]:v}}),"number"));
  if(req.spell)children.push(fold("Spellmaker settings",Object.entries(req.spell).filter(([,v])=>Number.isFinite(v)).map(([k,v])=>
    control(pretty(k),v,n=>change({...req,spell:{...req.spell,[k]:n}}),"number"))));
  for(const [key,label] of [["domain","Spellmaker search ranges"],["spells","Spells"],["goal","Training goal"],["checkpoints","Checkpoints"],
    ["policies","Casting policies"],["scenario","Encounter conditions"],["actor","Starting resources"]]){
    if(req[key]&&typeof req[key]==="object")children.push(fold(label,[properties(label,req[key],v=>change({...req,[key]:v}))]));
  }
  return children;
}
