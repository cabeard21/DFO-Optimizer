import {views,el,action,select,field,panel,disclosure,facts,table,pretty,replayAction} from "./view.js";
import {editors,importedClass} from "./editor.js";
import {beginnerInputs,recommendationPane} from "./beginner.js";
import {discoveryEditor} from "./discovery-editor.js";
import {resultsPane,comparePane} from "./results.js";
import {parseDocument,retainNumbers,stringifyDocument} from "./exact-json.js";

const byId=id=>document.getElementById(id);
const sessions=new Map(), compare={};
let meta,library,view="beginner";
const session=()=>sessions.get(view);
const status=(message,error=false)=>{byId("status").textContent=message;byId("status").dataset.error=String(error);};
function notifyError(error){status(error.message||String(error),true);}
function guarded(fn){return (...args)=>Promise.resolve().then(()=>fn(...args)).catch(notifyError);}
async function api(path,options){
  const response=await fetch("/api/"+path,options);
  const data=parseDocument(await response.text());
  if(!response.ok)throw Error(data.error||data.message||("Local service returned "+response.status));
  return data;
}
const post=(path,body)=>api(path,{method:"POST",headers:{"Content-Type":"application/json"},body:stringifyDocument(body)});
function download(label,value){
  const url=URL.createObjectURL(new Blob([stringifyDocument(value,2)+"\n"],{type:"application/json"}));
  const a=el("a");a.href=url;a.download=label;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function exportRequest(s){
  if(s.source?.example)return location.assign("/api/examples/"+encodeURIComponent(s.source.example)+"?download=1");
  if(s.source?.upload)return location.assign("/api/uploads/"+encodeURIComponent(s.source.upload));
  if(s.source?.library_request)return location.assign("/api/library/export?request=1&id="+encodeURIComponent(s.source.library_request));
  download("dfo-request.json",s.request);
}
function dialog(title,children){
  byId("dialog-title").textContent=title;byId("dialog-content").replaceChildren(...children);
  if(!byId("drawer").open)byId("drawer").showModal();
}
byId("close").addEventListener("click",()=>byId("drawer").close());
function getSession(key){
  if(!sessions.has(key))sessions.set(key,{operation:null,example:null,request:null,job:null,index:0,changed:false,load:0,
    mode:["beginner","discovery"].includes(key)?"request":library?.preferences?.mode??"request"});
  return sessions.get(key);
}
async function loadExample(s,operation,example){
  const ticket=++s.load;
  s.loading=true;
  try{
    const request=await api("examples/"+encodeURIComponent(example));
    if(s.load!==ticket)return;
    Object.assign(s,{operation,example,request,source:{example},changed:Boolean(s.job),
      discoveryBudget:example.startsWith("discovery-")?{nodes:request.search.max_nodes,panel:request.class_search.top_k}:null});
    if(s===session()){status("Loaded "+example+".");render();}
  }finally{
    if(s.load===ticket)s.loading=false;
  }
}
function currentAction(s){return views[view].operations[s.operation][0];}
function examplesFor(actionName,defaultName){
  let names=meta.examples.filter(name=>{
    if(actionName==="class optimize")return name==="max-intelligence";
    if(actionName.startsWith("gear "))return name===defaultName||(defaultName==="gear-owned"&&/^gear-(auto|fixed)-from-save$/.test(name));
    if(actionName.startsWith("build "))return actionName==="build replan"?name.startsWith("build-replan"):
      name.startsWith("build-")&&!name.startsWith("build-replan");
    if(actionName==="spell curve")return name==="spell-scaling";
    if(actionName.startsWith("spell "))return name.startsWith(actionName==="spell evaluate"?"spell-fixed":"spell-auto");
    if(actionName.startsWith("spellbook "))return name===defaultName;
    return name.startsWith(actionName.split(" ")[0]+"-");
  });
  return names.includes(defaultName)?names:[defaultName,...names];
}
function filePicker(label,accept,fn){
  const button=action(label,()=>input.click());
  const input=el("input");input.type="file";input.accept=accept;input.hidden=true;
  input.addEventListener("change",guarded(async()=>{const file=input.files[0];input.value="";if(file)await fn(file);}));
  const wrap=el("span");wrap.append(button,input);return wrap;
}
async function readUpload(kind,file,query=""){
  const item=await api("import/"+kind+query,{method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file});
  if(item.warnings?.length)status(item.warnings.join(" · "),true);
  return item;
}
async function saveJob(s){
  const job=s.job;
  if(!job.result)throw Error("Wait for a completed search.");
  const label=(job.example||job.action)+" · "+(job.result.result_hash||job.id).slice(0,8);
  library=await post("library/item",{job_id:job.id,label,preferences:{mode:s.mode}});
  status("Saved "+label+".");
}
function offerSnapshot(s,snapshot){
  const req=s.request||{},operation=currentAction(s);
  if(operation==="progression plan"){
    return {...req,start:{type:"current_character",character:snapshot}};
  }
  if(operation==="build replan"){
    const id=snapshot.name||snapshot.character_id||"Imported character";
    return {...req,families:[{id,start:{type:"current_character",character:snapshot}}]};
  }
  if(/^(gear|spell|spellbook) /.test(operation)){
    const {caster,career,inventory,character,character_file,...rest}=req;
    return {...rest,character:snapshot};
  }
  throw Error("Open Gear, Spell Lab or a current-character progression request to use a snapshot.");
}
function attachSnapshot(s,snapshot){
  s.request=retainNumbers(s.request,offerSnapshot(s,snapshot));s.source=null;s.changed=Boolean(s.job);render();
}
async function importCharacter(file,s){
  let query="";
  if(file.name.toLowerCase().endsWith(".zip")){
    const {value}=await readUpload("slots",file,"?format=zip");
    const list=Array.isArray(value)?value:value.slots;
    if(!Array.isArray(list)||!list.length)throw Error("No save slots in the archive.");
    if(list.length>1){
      dialog("Choose save slot",list.map(slot=>action("Slot "+slot.slot+" · "+(slot.character_name||slot.save_name||"Character"),
        guarded(async()=>{byId("drawer").close();await finish("?format=zip&slot="+slot.slot);}))));
      return;
    }
    query="?format=zip&slot="+list[0].slot;
  }
  await finish(query);
  async function finish(suffix){
    const {value}=await readUpload("character",file,suffix+(suffix?"&":"?")+"save_as="+encodeURIComponent(file.name));
    library=await api("library");status("Saved "+file.name+".");
    if(s&&s===session())attachSnapshot(s,value);
    else if(!s){await openLibrary();status("Saved "+file.name+".");}
  }
}
async function openLibrary(){
  library=await api("library");
  const controls=el("div",null,"actions");
  controls.append(filePicker("Import character",".zip,.json,.txt",file=>importCharacter(file,null)),
    filePicker("Open archive",".json",async file=>{
      const item=await readUpload("archive",file,"?save_as="+encodeURIComponent(file.name));
      await openLibrary();if(item.warnings?.length)status(item.warnings.join(" · "),true);
    }),filePicker("Open result",".json",async file=>{
      const {warnings}=await readUpload("result",file,"?save_as="+encodeURIComponent(file.name));
      await openLibrary();if(warnings?.length)status(warnings.join(" · "),true);
    }));
  const list=library.items.map(item=>{
    const row=el("div",null,"library-item");row.append(el("strong",item.label||item.action||"Snapshot"));
    if(item.kind==="character")row.append(action("Use character",guarded(()=>{
      if(!session()?.request)throw Error("Open a request first.");attachSnapshot(session(),item.value);byId("drawer").close();
    })));
    else row.append(action("Inspect",()=>inspectSaved(item)));
    return row;
  });
  dialog("Local library",[controls,...(list.length?list:[el("p","Saved characters and results appear here.","empty")])]);
}
function inspectSaved(item){
  const children=[];
  if(item.ruleset_hash!==meta.ruleset_hash)children.push(el("p","This result uses a different ruleset. Re-run its frozen request before comparing scores.","warning"));
  children.push(facts({action:item.action,status:item.result?.status,ruleset:item.ruleset_hash?.slice(0,12)}));
  if(item.request&&item.action){
    children.push(action("Open frozen request",guarded(async()=>{
      const isDiscovery=item.request?.class_search?.profile==="spellcaster_discovery_v1";
      const match=Object.entries(views).find(([key,v])=>(key!=="discovery"||isDiscovery)&&Object.values(v.operations||{}).some(([op])=>op===item.action));
      if(!match)throw Error("No editor for this operation.");
      const [key,config]=match,s=getSession(key);
      const gearMode={owned_only:"Best owned",owned_plus_budget:"Budget upgrades",available_catalog:"Available catalog",
        theoretical_bis:"Theoretical BIS"}[item.request.mode];
      const operation=key==="gear"&&gearMode?gearMode:Object.keys(config.operations).find(name=>config.operations[name][0]===item.action);
      if(s.submitting)throw Error("Finish or cancel the current search before opening another request.");
      s.load++; Object.assign(s,{operation,request:item.request,source:{library_request:item.id},discoveryBudget:null,
        example:item.label,job:null,comparisonJob:null,index:0,changed:false});
      byId("drawer").close();location.hash=key;await navigate();
    })));
  }
  if(item.result?.kind==="beginner_recommendation"&&item.ruleset_hash===meta.ruleset_hash) {
    const file=(family,checklist)=>location.assign("/api/library/export?"+new URLSearchParams(
      {id:item.id,family,...(checklist?{checklist:"1"}:{})}));
    children.push(recommendationPane(item.result,{exportFamily:key=>file(key,false),exportChecklist:key=>file(key,true)}));
  }
  const savedReplay=replayAction(item.result);
  if(savedReplay)children.push(action("Verify saved result",guarded(async()=>{
    const replay=await runAndWait(savedReplay,{library_result:item.id});
    dialog("Replay verification",[disclosure("Verification details",replay.result||replay.error),
      facts({status:replay.result?.valid?"Verified":replay.state})]);
  })));
  children.push(disclosure("Saved result",item.result),action("Export result",()=>location.assign("/api/library/export?id="+encodeURIComponent(item.id))));
  dialog(item.label||"Saved result",children);
}
byId("library").addEventListener("click",guarded(openLibrary));

const done=job=>["completed","cancelled","failed"].includes(job.state);
async function waitForJob(job,update){
  update(job);
  while(!done(job)){
    await new Promise(resolve=>setTimeout(resolve,250));
    job=await api("jobs/"+encodeURIComponent(job.id)); update(job);
  }
  return job;
}
async function runAndWait(operation,source){
  return waitForJob(await post("jobs",{action:operation,source,mode:"request",ruleset_hash:meta.ruleset_hash}),()=>{});
}
async function submit(s){
  if(s.submitting||s.comparing||s.job&&!done(s.job))return;
  if(s.loading)throw Error("Wait for the selected example to load.");
  if(!s.request)throw Error("Load a request first.");
  const controls=[...byId("content").querySelectorAll("input,textarea,select")];
  if(controls.some(node=>!node.reportValidity()))return;
  s.submitting=true;s.changed=false;s.index=0;s.selectedBuild=null;s.comparisonJob=null;
  const frozen=s.request,name=currentAction(s),example=s.example;
  try{
    const input=s.source?{source:s.source}:{request:frozen};
    const job=await post("jobs",{action:name,...input,mode:s.mode,ruleset_hash:meta.ruleset_hash});
    await waitForJob(job,next=>{s.job={...next,example};if(s===session())drawResults();});
    if(s===session())status(s.job.error||pretty(s.job.state),Boolean(s.job.error));
  }finally{s.submitting=false;if(s===session())drawResults();}
}
async function compareSlower(s,row){
  if(s.submitting||s.comparing||!done(s.job))return;
  const request={schema_version:2,thoroughness:s.job.result.frozen_request.thoroughness,
    compare_slower:{class:row.class,race_id:row.race_id}};
  s.comparing=true;
  try{
    const job=await post("jobs",{action:"build recommend",request,mode:"request",ruleset_hash:meta.ruleset_hash});
    await waitForJob(job,next=>{s.comparisonJob=next;if(s===session())drawResults();});
    if(s===session())status(s.comparisonJob.error||pretty(s.comparisonJob.state),Boolean(s.comparisonJob.error));
  }finally{s.comparing=false;if(s===session())drawResults();}
}
function drawResults(){
  const s=session(),area=byId("result-area");if(!area||!s)return;
  const job=s.job,link=query=>location.assign("/api/jobs/"+encodeURIComponent(job.id)+"/export"+query);
  area.dataset.jobId=job?.id??"";
  area.dataset.state=job?.state??"";
  if(view==="beginner"&&!job){area.replaceChildren();return;}
  area.replaceChildren(resultsPane(s,{
    refresh:drawResults,cancel:guarded(async()=>{s.job={...await post("jobs/"+job.id+"/cancel",{}),example:job.example};drawResults();}),
    catalog:meta.catalog, save:guarded(()=>saveJob(s)),exportClass:i=>link("?index="+i),
    exportFamily:(name,preview=false)=>link("?"+new URLSearchParams({family:name,...(preview?{preview:"1"}:{})})),
    exportChecklist:(name,preview=false)=>link("?"+new URLSearchParams({family:name,checklist:"1",...(preview?{preview:"1"}:{})})),exportResult:()=>link(""),exportArchive:()=>link("?archive=1"),
    exportPreview:()=>link("?archive=1&preview=1"),
    compareSlower:guarded(row=>compareSlower(s,row)),
    cancelComparison:guarded(async()=>{s.comparisonJob=await post("jobs/"+s.comparisonJob.id+"/cancel",{});drawResults();}),
    exportComparison:()=>location.assign("/api/jobs/"+encodeURIComponent(s.comparisonJob.id)+"/export?archive=1"),
    replay:guarded(async()=>{const replay=await runAndWait(replayAction(job.result),{job_result:job.id});
      if(replay.error)throw Error(replay.error);dialog("Replay verification",[facts(replay.result)]);})
  }));
}
function searchEditor(s){
  const config=views[view],chosen=config.operations[s.operation],stage=el("div"),advanced=el("textarea",null,"mono");
  const scope=el("div",null,"scenario-band");
  const operation=select(Object.keys(config.operations).map(k=>[k,k]),s.operation,guarded(v=>loadExample(s,v,config.operations[v][1])));
  const discovery=view==="discovery";
  const presets=new Map(meta.discovery_presets.map(p=>["discovery-"+p.id,p]));
  const examples=discovery?[...presets.keys()]:examplesFor(chosen[0],chosen[1]);
  if(!examples.includes(s.example))examples.unshift(s.example);
  const chooseExample=select(examples.map(v=>[v,presets.get(v)?.label||v]),s.example,guarded(v=>loadExample(s,s.operation,v)));
  function update(next,initial=false){
    s.request=retainNumbers(s.request,next);if(!initial)s.source=null;s.changed=Boolean(s.job);
    advanced.value=stringifyDocument(next,2);advanced.setCustomValidity("");
    const opened=new Set([...stage.querySelectorAll("details[open] > summary")].map(n=>n.textContent));
    stage.replaceChildren(...(discovery?discoveryEditor(next,meta.catalog,update,s.discoveryBudget):editors(view,next,meta.catalog,update)));
    const tags=view==="creator"?["Difficulty "+(next.difficulty_points??-12),
      "HP "+(next.hp_values??[30]).join(" / "),"Magery "+(next.magicka_multiplier===null?"unlocked":(next.magicka_multiplier??3)+"× INT")]:
      [next.mode, next.scenario?.id||next.target?.id, next.budget?.gold!=null?next.budget.gold+" gold":null,
       next.checkpoints?next.checkpoints.length+" checkpoints":null,
       next.seeds?next.seeds.length+" paired seeds":null].filter(Boolean);
    scope.replaceChildren(el("strong",view==="creator"?"Class constraints":"Scenario"),...tags.map(t=>el("span",pretty(String(t)))));
    scope.hidden=!tags.length;
    for(const d of stage.querySelectorAll("details"))if(opened.has(d.firstChild.textContent))d.open=true;
    if(s.job)drawResults();
  }
  const changed=s.changed;
  update(s.request,true);
  s.changed=changed;
  advanced.addEventListener("change",()=>{
    try{const value=parseDocument(advanced.value);if(!value||Array.isArray(value)||typeof value!=="object")throw Error("A request must be an object.");update(value);}
    catch(e){advanced.setCustomValidity(e.message);advanced.reportValidity();}
  });
  const raw=el("details");raw.append(el("summary","Full request JSON"),field("Frozen request inputs",advanced));
  const run=action(discovery?"Discover builds":"Run "+(view==="creator"?"class search":view==="gear"?"gear search":s.operation.toLowerCase()),guarded(()=>submit(s)),"primary");
  const inputs=el("div",null,"actions");
  inputs.append(filePicker("Open request",".json",async file=>{
    const {value,upload_id}=await readUpload("request",file);
    s.load++;s.loading=false;s.example=file.name;s.discoveryBudget=null;update(value);s.source={upload:upload_id};render();
  }),
    action("Export request",()=>exportRequest(s)));
  if(view==="creator")inputs.append(filePicker("Import game class",".json",async file=>{
    const {value}=await readUpload("class",file);if(!value.normalized||!value.create_legal||value.skipped?.length){
      dialog("Class validation",[disclosure("Validation details",value)]);return;
    }
    update(importedClass(value.normalized,meta.catalog,s.request));status("Imported "+value.normalized.name+". Class choices are locked.");
  }));
  if(discovery)inputs.append(filePicker("Compare a game class",".json",async file=>{
    const {value}=await readUpload("class",file);
    if(!value.normalized||!value.create_legal||value.skipped?.length){
      dialog("Class validation",[disclosure("Validation details",value)]);return;
    }
    const doc=value.normalized;
    let raceId=meta.catalog.races[0].id;
    const picker=select(meta.catalog.races.map(r=>[String(r.id),r.name]),String(raceId),v=>{raceId=Number(v);});
    dialog("Compare a game class",[field("Race for imported class",picker),action("Add comparison",guarded(()=>{
      const families=s.request.families??[],race=meta.catalog.races.find(r=>r.id===raceId);
      const base=doc.name+" · "+race.name;
      let id=base;
      for(let i=2;families.some(f=>f.id===id);i++)id=base+" ("+i+")";
      update({...s.request,families:[...families,{id,start:{type:"new_character",profile:"custom",race_id:raceId,class:doc}}]});
      byId("drawer").close();status("Added "+id+" to the paired comparison.");
    }))]);
  }));
  if(["gear","spells","progression"].includes(view))inputs.append(filePicker("Import character",".zip,.txt,.json",file=>importCharacter(file,s)));
  const mode=select(Object.keys(meta.modes).map(k=>[k,k==="request"?"Use request limits":pretty(k)]),s.mode,v=>{
    s.mode=v;if(s.job){s.changed=true;drawResults();}
  });
  return panel("Search inputs",[...(discovery?[]:[field("Operation",operation)]),field(discovery?"Scenario preset":"Example",chooseExample),scope,stage,raw,
    ...(discovery?[]:[field("Search limits",mode)]),run,inputs]);
}
function render(){
  byId("title").textContent=views[view].name;document.title=views[view].name+" · DFO Optimizer";
  for(const a of byId("navigation").children){if(a.hash==="#"+view)a.setAttribute("aria-current","page");else a.removeAttribute("aria-current");}
  const content=byId("content"),s=session();
  content.classList.toggle("beginner-flow",view==="beginner");
  if(view==="compare"){content.replaceChildren(comparePane(library.items,compare,render,meta));return;}
  if(view==="diagnostics"){
    const coverage=meta.coverage;
    content.replaceChildren(panel("Ruleset and engine",[facts({source:meta.source_sha,ruleset:meta.ruleset_hash,
      mode:meta.mode,snapshot_verified:coverage.snapshot_verified?.length,live_verified:coverage.live_verified?.length}),
      disclosure("Native engine",meta.engine)]),panel("Mechanics registry",[table(["Mechanic","Evidence","Scope"],(coverage.mechanics||[]).map(row=>
        [row.mechanic_id,row.verification_status,noteOf(row.known_limits??row.limits??row.mode_applicability)]))]),
      panel("Benchmark evidence",[filePicker("Open benchmark JSON",".json",async file=>{
        const {value}=await readUpload("benchmark",file);
        dialog("Benchmark report",[facts({suite:value.suite,workers:value.workers,ruleset:value.ruleset_hash}),disclosure("Measured workloads",value.workloads||value)]);
      })]));return;
  }
  if(!s?.request){content.replaceChildren(el("p","Loading request…","note"));return;}
  if(view==="beginner"){
    const inputs=beginnerInputs(s,guarded(()=>submit(s)),next=>{
      const changedProfile=next.schema_version!==s.request.schema_version||Boolean(next.compare_slower)!==Boolean(s.request.compare_slower);
      s.request=next;s.source=null;s.changed=Boolean(s.job);
      if(changedProfile)render();else if(s.job)drawResults();
    });
    const out=el("div");out.id="result-area";out.className="beginner-results";
    content.replaceChildren(inputs,out);drawResults();return;
  }
  const columns=el("div",null,"columns"),out=el("div");out.id="result-area";
  columns.append(searchEditor(s),out);content.replaceChildren(columns);drawResults();
}
function noteOf(value){return typeof value==="string"?value:value==null?"—":JSON.stringify(value);}
async function navigate(){
  const key=location.hash.slice(1);view=Object.hasOwn(views,key)?key:"beginner";const s=getSession(view);
  if(view==="beginner"&&!s.request)Object.assign(s,{request:{schema_version:2,thoroughness:"standard"},operation:"Recommend My First Spellcaster",mode:"request"});
  render();
  if(views[view].operations&&!s.request){
    const [name,[,example]]=Object.entries(views[view].operations)[0];await loadExample(s,name,example);
  }else status("");
}
async function start(){
  [meta,library]=await Promise.all([api("meta"),api("library")]);
  byId("source").textContent=meta.source_sha.slice(0,12);
  for(const [key,{name,icon}] of Object.entries(views)){
    const a=el("a");a.href="#"+key;const glyph=el("span",icon,"nav-icon");glyph.setAttribute("aria-hidden","true");
    a.append(glyph,el("span",name));byId("navigation").append(a);
  }
  window.addEventListener("hashchange",guarded(navigate));await navigate();
}
guarded(start)();
