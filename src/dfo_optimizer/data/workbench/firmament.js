import {action,el,facts,field,format,panel,pretty,select,table} from "./view.js";
import {firmamentGraph,pointBalance} from "./firmament-graph.js";

const emptyTree={start:null,keys:[]};
const sameTree=(a,b)=>a.start===b.start&&a.keys.length===b.keys.length&&a.keys.every(key=>b.keys.includes(key));

function numberInput(value,min,max){
  const input=el("input");input.type="number";input.required=true;input.min=min;input.max=max;input.value=value;
  return input;
}

function row(...children){
  const node=el("div",null,"actions");
  node.append(...children);
  return node;
}

function signName(catalog,tree){
  const node=catalog.nodes[tree.start];
  return node?.name??(tree.start||"None");
}

function supportedSpells(snapshot){
  return (snapshot?.observations?.spells?.records??[]).flatMap((spell,index)=>{
    const effects=spell.effects?.filter(effect=>effect?.type!==-1);
    return effects?.length===1&&effects[0]?.type===4&&effects[0]?.subType===0?
      [[String(index),spell.name||"Saved spell "+(index+1)]]:[];
  });
}

export function createFirmamentWorkspace(services){
  const {api,post,waitForJob,done,status,guarded,readCharacter,filePicker,rulesetHash}=services;
  let catalog,profiles=[],profile=null,tree=emptyTree,history=[],selected=null,zoom=1;
  let job=null,jobSource=null,searching=false,results,root;

  async function refresh(){
    const [data,listing]=await Promise.all([catalog??api("firmament/catalog"),api("firmament/profiles")]);
    catalog=data;profiles=listing.profiles;
    if(!profiles.length){profile=null;return;}
    const current=profiles.find(candidate=>candidate.id===profile?.id)??profiles[0];
    if(current.id!==profile?.id||current.revision!==profile?.revision)await openProfile(current.id);
  }

  function remember(updated){
    if(profile?.id===updated.id)profile={...profile,...updated};
    const index=profiles.findIndex(candidate=>candidate.id===updated.id);
    if(index===-1)profiles.push(updated);
    else profiles[index]=updated;
  }

  async function openProfile(id){
    profile=await api("firmament/profile?id="+encodeURIComponent(id));
    tree=profile.tree;history=[];selected=tree.start;
  }

  async function save(changes){
    const updated=await post("firmament/profile",{
      id:profile.id,revision:profile.revision,...changes,
    });
    remember(updated);
    return updated;
  }

  async function importProfile(file,replace=false){
    await readCharacter(file,async ({value,upload_id})=>{
      const first=supportedSpells(value)[0]?.[0];
      const changes={character_upload:upload_id,spell:null,spell_index:first==null?null:Number(first)};
      if(replace){
        await save(changes);
        await openProfile(profile.id);
      }else{
        const created=await post("firmament/profile",{...changes,
          label:value.observations?.name??value.provenance?.character_name??file.name,
          target:{id:"ordinary_pve",hp:60,willpower:50}});
        remember(created);
        await openProfile(created.id);
      }
      status(replace?"Updated the save for "+profile.label+".":"Created a profile for "+profile.label+".");
      draw();
    });
  }

  function editTree(next,key){
    const oldFrame=root.querySelector(".firmament-scroll");
    const viewport={left:oldFrame.scrollLeft,top:oldFrame.scrollTop};
    history.push(tree);tree=next;selected=key;
    draw();
    const frame=root.querySelector(".firmament-scroll");
    frame.scrollTo(viewport);
    const node=[...root.querySelectorAll("[data-node]")].find(item=>item.dataset.node===key);
    node?.focus({preventScroll:true});
  }

  function pointsEditor(){
    const stars=numberInput(profile.stars,0,catalog.max_stars??98);
    const craft=numberInput(profile.craft,0,catalog.max_craft??125);
    const balance=pointBalance(catalog,tree,profile.stars,profile.craft);
    const values=el("div",null,"firmament-points");
    values.append(el("strong",balance.stars+" Stars left"),el("strong",balance.craft+" Craft points left"));
    const totals=action("Save point totals",guarded(async()=>{
      if(![stars,craft].every(input=>input.reportValidity()))return;
      await save({stars:Number(stars.value),craft:Number(craft.value)});
      status("Point totals updated.");draw();
    }));
    const additional=el("details");
    const addStars=numberInput(0,0,Number(stars.max)-profile.stars);
    const addCraft=numberInput(0,0,Number(craft.max)-profile.craft);
    const add=action("Add points",guarded(async()=>{
      if(![addStars,addCraft].every(input=>input.reportValidity()))return;
      await save({stars:profile.stars+Number(addStars.value),craft:profile.craft+Number(addCraft.value)});
      status("Added newly earned points.");draw();
    }));
    additional.append(el("summary","Add earned points"),field("New Stars",addStars),field("New Craft points",addCraft),add);
    return panel("Point budget",[values,field("Total Stars",stars),field("Total Craft points",craft),totals,additional]);
  }

  function treeEditor(){
    const changeable=!sameTree(tree,profile.tree);
    const store=action("Save my tree",guarded(async()=>{
      await save({tree});tree=profile.tree;history=[];
      status("Saved tracked tree.");draw();
    }),"primary");
    store.disabled=!changeable;
    const undo=action("Undo tree edit",()=>{
      tree=history.pop();draw();
    });
    undo.disabled=!history.length;
    return panel("Tree",[
      el("p","Tracked sign: "+signName(catalog,profile.tree),"note"),
      firmamentGraph(catalog,profile,tree,selected,editTree,{focused:key=>{selected=key;},zoom,onZoom:value=>{zoom=value;}}),
      row(store,undo),...(changeable?[el("p","Save the draft to use it in your next recommendation.","note")]:[]),
    ]);
  }

  function scenarioEditor(){
    const spells=supportedSpells(profile.character);
    const spell=select([["","Choose a saved damage spell"],...spells],
      profile.spell_index==null?"":String(profile.spell_index),()=>{});
    const target=profile.target??{};
    const label=el("input");label.type="text";label.required=true;label.value=target.id??"ordinary_pve";
    const hp=numberInput(target.hp??60,1,1_000_000),willpower=numberInput(target.willpower??50,0,200);
    const start=action("Run Firmament search",guarded(async()=>{
      if(searching)return;
      if(![label,hp,willpower].every(input=>input.reportValidity()))return;
      const selection=spell.value===""?null:Number(spell.value);
      if(selection===null&&!profile.spell)throw Error("Choose a damage spell in the saved spellbook.");
      const nextTarget={...target,id:label.value.trim(),hp:Number(hp.value),willpower:Number(willpower.value)};
      if(!nextTarget.id)throw Error("Enter a target name.");
      searching=true;start.disabled=true;job=null;jobSource=null;drawResults();
      try{
        let input=profile;
        if(selection!==profile.spell_index||Object.keys(nextTarget).some(key=>nextTarget[key]!==target[key])){
          input=await save({spell:selection===null?profile.spell:null,spell_index:selection,target:nextTarget});
        }
        const {id,revision}=input;
        jobSource={id,revision};
        const first=await post("jobs",{action:"firmament optimize",firmament_profile:{id,revision},
          mode:"request",ruleset_hash:rulesetHash});
        await waitForJob(first,next=>{job=next;drawResults();});
        status(job.error||"Firmament search "+job.state+".",Boolean(job.error));
      }finally{searching=false;draw();}
    }),"primary");
    start.disabled=searching||!sameTree(tree,profile.tree);
    const inputs=el("div",null,"firmament-scenario");
    inputs.append(field("Saved damage spell",spell),field("Target name",label),field("Target HP",hp),field("Target Willpower",willpower));
    const notes=[el("p","Ordinary unmentored PvE with the saved loadout.","note")];
    if(!spells.length&&!profile.spell)notes.push(el("p","This save has no supported single-effect Damage Health spell.","warning"));
    return panel("Combat scenario",[...notes,inputs,start]);
  }

  function drawResults(){
    if(!results)return;
    if(!job&&!searching){results.replaceChildren();return;}
    const children=[];
    if(searching){
      children.push(el("p",job?.state?pretty(job.state):"Queuing native search…","state"));
      if(job&&!done(job))children.push(action("Cancel Firmament search",guarded(async()=>{
        job=await post("jobs/"+encodeURIComponent(job.id)+"/cancel",{});drawResults();
      })));
    }
    if(job?.error)children.push(el("p",job.error,"warning"));
    const result=job?.result;
    if(result){
      children.push(facts({status:result.exact?"Exact for this scenario":pretty(result.status??"best found"),
        termination:result.termination,nodes:result.nodes??result.counters?.nodes}));
      if(result.limits)children.push(facts({node_limit:result.limits.max_nodes||"Unlimited",
        time_limit:result.limits.wall_seconds?result.limits.wall_seconds+" s":"Unlimited"}));
      for(const item of [...(result.advisories??[]),...(result.blockers??[])]){
        children.push(el("p",typeof item==="string"?item:JSON.stringify(item),"warning"));
      }
      const options=result.candidates??[];
      const value=(item,key)=>item?.[key]??item?.metrics?.[key];
      const metricCells=item=>[value(item,"damage_per_second")??value(item,"dps"),value(item,"damage_per_sp"),
        value(item,"cost_sp"),value(item,"available_sp")];
      const baseline=result.baseline;
      const rows=baseline?[["Tracked tree",...metricCells(baseline),"—"]]:[];
      const mayAdopt=!searching&&jobSource?.id===profile?.id&&jobSource?.revision===profile?.revision;
      options.forEach((option,index)=>{
        const steps=(option.additions??[]).map(key=>catalog.nodes[key]?.name??key);
        const tools=el("div","", "firmament-route");
        tools.append(el("p",steps.length?steps.join(" → "):"Keep tracked tree"));
        if(mayAdopt&&steps.length){
          tools.append(action("Adopt plan",guarded(async()=>{
            const adopted=await post("firmament/adopt",{id:profile.id,revision:profile.revision,job_id:job.id,candidate_index:index});
            remember(adopted);tree=profile.tree;history=[];selected=tree.start;
            status("Plan adopted in the local tracker.");draw();
          })));
        }
        rows.push([index===0?"Highest damage rate":"Option "+(index+1),...metricCells(option),tools]);
      });
      if(rows.length)children.push(table(["Allocation","Damage / second","Damage / SP","Cast SP","Full SP","Next nodes"],rows));
      if(options.length&&!mayAdopt&&!searching)children.push(el("p","Run a new search using the current profile to adopt a plan.","note"));
      children.push(action("Export Firmament archive",()=>location.assign("/api/jobs/"+encodeURIComponent(job.id)+"/export?archive=1")));
    }
    results.replaceChildren(panel("Firmament recommendations",children));
  }

  function draw(){
    if(!root)return;
    const upload=filePicker("Create profile from save",".zip,.txt,.json",file=>importProfile(file));
    const switcher=profile?field("Tracked profile",select(profiles.map(p=>[p.id,p.label]),profile.id,guarded(async id=>{
      await openProfile(id);draw();
    }))):null;
    const actions=row(upload);
    if(profile)actions.append(filePicker("Replace save",".zip,.txt,.json",file=>importProfile(file,true)));
    const header=panel("Firmament profiles",switcher?[switcher,actions]:[
      el("p","Import a character save to track a tree and plan how to spend points.","note"),actions,
    ]);
    results=el("div");
    if(!profile){root.replaceChildren(header,results);return;}
    const layout=el("div",null,"firmament-layout");
    const side=el("div");side.append(pointsEditor(),scenarioEditor());
    layout.append(treeEditor(),side);
    root.replaceChildren(header,layout,results);drawResults();
  }

  function render(){
    root=el("div");draw();return root;
  }
  return {refresh,render,list:()=>profiles,catalog:()=>catalog};
}

export function gearFirmamentInputs(request,profiles,catalog,rulesetHash,selectedId,chooseProfile,change){
  const saved=request.character;
  const hash=saved?.snapshot_hash;
  const projection=request.firmament_projection;
  const matching=profiles.find(p=>p.id===projection?.profile_id)??
    profiles.find(p=>p.character_hash===hash&&p.id===selectedId)??profiles.find(p=>p.character_hash===hash);
  const selectors=el("div");
  const attach=()=>{
    change({...request,firmament_projection:{tree:matching.tree,stars:matching.stars,craft:matching.craft,
      profile_id:matching.id,revision:matching.revision,snapshot_hash:hash,ruleset_hash:rulesetHash,
      catalog_hash:catalog?.content_hash}});
  };
  if(profiles.length){
    selectors.append(field("Firmament profile",select([["","Choose a profile"],...profiles.map(p=>[p.id,p.label])],
      matching?.id??"",id=>{if(id)chooseProfile(id);})));
  }
  if(saved||projection){
    const toggle=el("input");toggle.type="checkbox";toggle.checked=Boolean(projection);
    toggle.disabled=!projection&&(!matching||matching.character_hash!==hash||!matching.tree.start);
    toggle.addEventListener("change",()=>{
      const {firmament_projection,...rest}=request;
      if(!toggle.checked){change(rest);return;}
      attach();
    });
    const label=el("label",null,"firmament-toggle");
    label.append(toggle,el("span","Apply tracked Firmament"));
    selectors.append(label);
    if(projection)selectors.append(el("p",signName(catalog??{nodes:{}},projection.tree)+
      " · "+projection.tree.keys.length+" allocated nodes · profile revision "+projection.revision,"note"));
    else if(toggle.disabled)selectors.append(el("p","Choose a matching profile with a tracked tree.","note"));
  }
  if(projection&&matching&&matching.revision!==projection.revision){
    if(matching.character_hash!==hash){
      selectors.append(action("Use latest profile save",()=>chooseProfile(matching.id)));
    }else if(matching.tree.start){
      selectors.append(action("Use latest tracked tree",attach));
    }
  }
  if(request.save_assumptions&&saved){
    const observations=request.live_observations??{};
    const resourceFields=el("div",null,"firmament-scenario");
    for(const [key,label] of [["current_sp","Current SP (optional)"],...(projection?[]:[["max_sp","Maximum SP (optional)"]])]){
      const input=numberInput(observations[key]?.value??"",0,2**30);input.required=false;
      input.addEventListener("change",()=>{
        if(!input.reportValidity())return;
        const {[key]:previous,...other}=observations;
        const next=input.value===""?other:{...other,[key]:{
          value:Number(input.value),source:"Entered from the character sheet",observed_at_ms:Date.now(),
        }};
        change({...request,live_observations:next});
      });
      resourceFields.append(field(label,input));
    }
    selectors.append(resourceFields);
    const effects=(saved.unknown_mechanics??[]).filter(value=>value.startsWith("active_effect:"))
      .map(value=>value.replace("active_effect:",""));
    const current=request.live_observations?.current_sp?.value??saved.live_observations?.current_sp?.value;
    const max=request.live_observations?.max_sp?.value??saved.live_observations?.max_sp?.value??
      saved.observations?.resources?.maxMagicka;
    if(effects.length)selectors.append(el("p","Unmodeled effects ignored: "+effects.join(", ")+".","warning"));
    const source=current!=null?"Explicit current SP: "+format(current)+".":projection?
      "Starting SP uses the projected maximum with the tracked tree.":max!=null?
        "Starting SP assumes a full pool of "+format(max)+". The saved maximum can include temporary modifiers.":
        "Supply current or maximum SP to score this save.";
    selectors.append(el("p",source,"note"));
  }
  return selectors;
}
