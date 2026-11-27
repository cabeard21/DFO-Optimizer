export const views = {
  beginner: {name:"Beginner spellcaster",icon:"✦",operations:{"Recommend My First Spellcaster":["build recommend",null]}},
  discovery: {name:"Discover Spellcaster Build",icon:"✧",operations:{"Discover builds":["build optimize","discovery-early"]}},
  creator: {name:"Character Creator", icon:"◇", operations:{"Class search":["class optimize","max-intelligence"]}},
  progression: {name:"Progression", icon:"↗", operations:{
    "Plan training":["progression plan","progression-tradeoffs"],
    "Plan from creation":["build optimize","build-lifecycle"],
    "Replan a character":["build replan","build-replan-current"]}},
  spells: {name:"Spell Lab",icon:"✧", operations:{
    "Spellmaker search":["spell optimize","spell-auto"],"Evaluate spell":["spell evaluate","spell-fixed"],
    "Plot spell scaling":["spell curve","spell-scaling"],
    "Spellbook search":["spellbook optimize","spellbook-auto"],"Evaluate spellbook":["spellbook evaluate","spellbook-fixed"],
    "Encounter search":["encounter optimize","encounter-dungeon"],"Evaluate encounter":["encounter evaluate","encounter-miss"]}},
  gear: {name:"Gear & Loadouts",icon:"⬡",operations:{
    "Best owned":["gear optimize","gear-owned"],"Budget upgrades":["gear optimize","gear-budget"],
    "Available catalog":["gear optimize","gear-catalog"],"Theoretical BIS":["gear optimize","gear-bis"]}},
  firmament: {name:"Firmament",icon:"✷"},
  compare: {name:"Compare Builds",icon:"≍"},
  diagnostics: {name:"Data & Diagnostics",icon:"◎"}
};

export function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (cls) node.className = cls;
  return node;
}
export function action(label, fn, cls) {
  const control = el("button",label,cls);
  control.type = "button";
  control.addEventListener("click",fn);
  return control;
}
export function field(label, control) {
  const box = el("label",null,"field");
  box.append(el("span",label),control);
  return box;
}
export function select(pairs, value, change) {
  const box = el("select");
  for (const [key,label] of pairs) {
    const option = el("option",label);
    option.value = key;
    box.append(option);
  }
  box.value = value;
  box.addEventListener("change",() => change(box.value));
  return box;
}
export function panel(title,children) {
  const box=el("section",null,"panel"), head=el("div",null,"section-head"), body=el("div",null,"panel-body");
  head.append(el("h2",title)); body.append(...children); box.append(head,body);
  return box;
}
export function disclosure(title,value) {
  const box=el("details");
  box.append(el("summary",title),el("pre",JSON.stringify(value,null,2)));
  return box;
}
export const pretty = key => key.replaceAll("_"," ").replace(/([a-z])([A-Z])/g,"$1 $2");
export const format = v => typeof v === "number" ? v.toLocaleString(undefined,{maximumFractionDigits:5}) : String(v ?? "Unknown");
export function facts(values) {
  const list = el("dl",null,"keyvalues");
  for (const [label,value] of Object.entries(values)) list.append(el("dt",pretty(label)),el("dd",format(value)));
  return list;
}
export function table(headers,rows) {
  const wrap=el("div",null,"scroll"), grid=el("table"), head=el("thead"), titles=el("tr"), body=el("tbody");
  for(const h of headers){const th=el("th",h);th.scope="col";titles.append(th);}
  for(const values of rows){
    const row=el("tr");
    for(const value of values){
      const cell=el("td");
      if(value instanceof Node)cell.append(value);else cell.textContent=format(value);
      row.append(cell);
    }
    body.append(row);
  }
  head.append(titles); grid.append(head,body); wrap.append(grid); return wrap;
}

export function resultRows(result) {
  for(const key of ["candidates","routes","frontier"]){
    if(Array.isArray(result[key]))return result[key];
  }
  return [];
}
export function replayAction(result) {
  return {beginner_recommendation:"build replay",encounter_result:"encounter replay",lifecycle:"build replay",progression_plan:"progression replay"}[result?.kind]??null;
}
export function metrics(row) {
  const values={};
  for(const source of [row.metrics,row.effort,row]) {
    for(const [key,val] of Object.entries(source || {})){
      if(typeof val==="number" && !["race_id","roll_seed","index"].includes(key)) values[key]=val;
    }
  }
  if(Number.isFinite(row.checkpoints?.at(-1)?.dps))values.final_dps=row.checkpoints.at(-1).dps;
  if(row.total_cost?.gold !== undefined)values.gold=row.total_cost.gold;
  return values;
}
export function nameOf(row,i) {
  return row.family_id || row.family || row.policy_id || row.id || row.name || row.class_doc?.name || ("Option "+(i+1));
}
export function graph(points,x,y,selected,onPick) {
  const ns="http://www.w3.org/2000/svg";
  function svg(kind,attrs,text) {
    const e=document.createElementNS(ns,kind);
    for(const [k,v] of Object.entries(attrs))e.setAttribute(k,String(v));
    if(text!==undefined)e.textContent=text;
    return e;
  }
  const chart=svg("svg",{viewBox:"0 0 480 195",class:"chart",role:"img","aria-label":pretty(y)+" versus "+pretty(x)+". Use the table to select a point."});
  const valid=points.map((row,i)=>({m:metrics(row),i})).filter(p=>Number.isFinite(p.m[x])&&Number.isFinite(p.m[y]));
  if(!valid.length)return el("p","No shared numeric points for these axes.","note");
  const range = axis => valid.reduce(([lo,hi],p)=>[Math.min(lo,p.m[axis]),Math.max(hi,p.m[axis])],[Infinity,-Infinity]);
  const [xmin,xmax]=range(x),[ymin,ymax]=range(y);
  const frac=(v,min,max)=>max===min ? 0.5 : (v-min)/(max-min);
  chart.append(svg("path",{d:"M62 18 V152 H453",fill:"none",stroke:"#aaa9bf"}));
  for(const [px,py,label,anchor] of [[58,23,format(ymax),"end"],[58,151,format(ymin),"end"],[62,169,format(xmin),"start"],[453,169,format(xmax),"end"],[250,188,pretty(x),"middle"],[68,13,pretty(y),"start"]])
    chart.append(svg("text",{x:px,y:py,"text-anchor":anchor},label));
  for(const {m,i} of valid) {
    const dot=svg("circle",{cx:68+380*frac(m[x],xmin,xmax),cy:145-119*frac(m[y],ymin,ymax),r:i===selected?6:4,class:i===selected?"selected":""});
    dot.append(svg("title",{},nameOf(points[i],i)+" · "+format(m[x])+" / "+format(m[y])));
    dot.addEventListener("click",()=>onPick(i)); chart.append(dot);
  }
  return chart;
}
