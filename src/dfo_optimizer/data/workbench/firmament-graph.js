import {action,el,field,format,pretty} from "./view.js";

const svgNS="http://www.w3.org/2000/svg";

function svg(tag,attributes={}){
  const node=document.createElementNS(svgNS,tag);
  for(const [key,value] of Object.entries(attributes))node.setAttribute(key,String(value));
  return node;
}

export function pointBalance(catalog,tree,stars,craft){
  const life=tree.keys.filter(key=>catalog.nodes[key]?.ring==="life").length;
  const craftSpent=Math.min(life,craft);
  return {stars:stars-tree.keys.length+craftSpent,craft:craft-craftSpent};
}

// Mirrors pathTo in the pinned Firmament law. The service validates every saved tree.
function connectingPath(catalog,tree,target){
  if(!tree.start||catalog.starts.includes(target)||tree.keys.includes(target))return [];
  const held=new Set([tree.start,...tree.keys]);
  const queue=[...held].filter(key=>catalog.nodes[key]?.kind!=="keystone");
  const parent=new Map(queue.map(key=>[key,null]));
  for(const key of queue){
    for(const next of catalog.nodes[key]?.adjacent??[]){
      if(parent.has(next)||held.has(next)||catalog.starts.includes(next))continue;
      parent.set(next,key);
      if(next===target){
        const path=[];
        for(let at=target;!held.has(at);at=parent.get(at))path.push(at);
        return path.reverse();
      }
      if(catalog.nodes[next].kind!=="keystone")queue.push(next);
    }
  }
  return [];
}

function withoutBranch(catalog,tree,target){
  const remaining=new Set(tree.keys.filter(key=>key!==target));
  const reached=new Set([tree.start]);
  for(const key of reached){
    if(catalog.nodes[key]?.kind==="keystone")continue;
    for(const next of catalog.nodes[key]?.adjacent??[])if(remaining.has(next))reached.add(next);
  }
  return {...tree,keys:tree.keys.filter(key=>reached.has(key))};
}

function describeNode(catalog,profile,tree,key,update){
  const node=catalog.nodes[key],children=[el("h3",node.name||key)];
  if(node.description)children.push(el("p",node.description,"note"));
  const mods=el("ul",null,"firmament-effects");
  for(const [stat,value] of Object.entries(node.stats??{})){
    mods.append(el("li",(value>0?"+":"")+format(value)+" "+pretty(stat)));
  }
  if(mods.childElementCount)children.push(mods);
  const path=connectingPath(catalog,tree,key);
  if(node.kind==="start"&&!tree.start){
    children.push(el("p","Starting signs are free.","note"),action("Choose sign",()=>update({start:key,keys:[]},key)));
  }else if(key===tree.start){
    children.push(el("p","Selected starting sign","note"),action("Clear draft tree",()=>update({start:null,keys:[]},key)));
  }else if(tree.keys.includes(key)){
    const next=withoutBranch(catalog,tree,key),removed=tree.keys.length-next.keys.length;
    children.push(el("p",removed===1?"Allocated":"Removing this node also removes "+(removed-1)+" dependent nodes.","note"),
      action(removed===1?"Remove node":"Remove branch",()=>update(next,key)));
  }else if(path.length){
    const next={...tree,keys:[...tree.keys,...path]};
    const before=pointBalance(catalog,tree,profile.stars,profile.craft);
    const after=pointBalance(catalog,next,profile.stars,profile.craft);
    const cost=(before.stars-after.stars)+" Stars, "+(before.craft-after.craft)+" Craft";
    const add=action(path.length===1?"Allocate node":"Allocate path",()=>update(next,key));
    add.disabled=after.stars<0||after.craft<0;
    children.push(el("p",cost+(add.disabled?" · Insufficient points":""),"note"));
    if(path.length>1)children.push(el("p",path.map(id=>catalog.nodes[id].name||id).join(" → "),"firmament-route"));
    children.push(add);
  }else{
    children.push(el("p",tree.start?"Unavailable from this starting sign.":"Choose a starting sign first.","note"));
  }
  return {children,path};
}

export function firmamentGraph(catalog,profile,tree,selected,update,{focused,zoom,onZoom}){
  const keys=Object.keys(catalog.nodes),root=el("div",null,"firmament-tree");
  if(!keys.length)return root;
  const items=new Map();
  const held=new Set([tree.start,...tree.keys]);
  const coords=keys.map(key=>catalog.nodes[key]);
  const left=Math.min(...coords.map(n=>n.x))-75,top=Math.min(...coords.map(n=>n.y))-75;
  const width=Math.max(...coords.map(n=>n.x))-left+75,height=Math.max(...coords.map(n=>n.y))-top+75;
  const frame=el("div",null,"firmament-scroll");
  const map=svg("svg",{viewBox:[left,top,width,height].join(" "),class:"firmament-chart",role:"group",
    "aria-label":"Firmament tree. Use the arrow keys to move and Enter to inspect a node."});
  map.style.width=(zoom*100)+"%";
  const details=el("aside",null,"firmament-node-detail");
  const links=[];
  for(const key of keys){
    const n=catalog.nodes[key];
    for(const next of n.adjacent){
      if(key>=next||!catalog.nodes[next])continue;
      const to=catalog.nodes[next];
      const line=svg("line",{x1:n.x,y1:n.y,x2:to.x,y2:to.y});
      links.push({line,key,next});
      map.append(line);
    }
  }
  let active=selected&&catalog.nodes[selected]?selected:tree.start||catalog.starts[0];
  function show(key,focus=false){
    items.get(active)?.setAttribute("tabindex","-1");
    active=key;
    const {children,path}=describeNode(catalog,profile,tree,key,update);
    const preview=new Set(path);
    for(const [id,button] of items){
      button.dataset.preview=String(preview.has(id));
      button.dataset.active=String(id===key);
    }
    for(const {line,key:from,next} of links){
      line.classList.toggle("held",held.has(from)&&held.has(next));
      line.classList.toggle("preview",(preview.has(from)||preview.has(next))&&
        (preview.has(from)||held.has(from))&&(preview.has(next)||held.has(next)));
    }
    items.get(key).setAttribute("tabindex","0");
    if(focus)items.get(key).focus();
    details.replaceChildren(...children);
    focused(key);
  }
  function move(key,dx,dy){
    const here=catalog.nodes[key];
    let nearest=null,best=Infinity;
    for(const other of keys){
      const node=catalog.nodes[other],x=node.x-here.x,y=node.y-here.y;
      const forward=dx*x+dy*y;
      if(forward<=0)continue;
      const square=x*x+y*y,rank=square/forward;
      if(rank<best){nearest=other;best=rank;}
    }
    if(nearest)show(nearest,true);
  }
  const arrows={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
  for(const key of keys){
    const n=catalog.nodes[key],name=n.name||key;
    const node=svg("g",{class:"firmament-dot","data-node":key,"data-ring":n.ring,"data-kind":n.kind,
      "data-held":String(held.has(key)),role:"button",tabindex:"-1",
      "aria-label":name+(held.has(key)?", allocated":"")});
    const r=n.kind==="start"?22:n.kind==="keystone"?15:n.kind==="notable"?12:8;
    node.append(svg("circle",{cx:n.x,cy:n.y,r:Math.max(16,r),class:"hit"}),
      svg("circle",{cx:n.x,cy:n.y,r,class:"star"}));
    const title=svg("title");title.textContent=name;node.append(title);
    node.addEventListener("click",()=>show(key,true));
    node.addEventListener("keydown",event=>{
      if(arrows[event.key]){event.preventDefault();move(key,...arrows[event.key]);}
      if(event.key==="Enter"||event.key===" "){event.preventDefault();show(key);}
    });
    map.append(node);items.set(key,node);
  }
  const level=el("input");level.type="range";level.min="1";level.max="3";level.step=".25";level.value=zoom;
  level.addEventListener("input",()=>{
    const before=frame.scrollWidth,current=frame.scrollLeft+frame.clientWidth/2;
    const oldHeight=frame.scrollHeight,center=frame.scrollTop+frame.clientHeight/2;
    const scale=Number(level.value);map.style.width=(scale*100)+"%";onZoom(scale);
    frame.scrollLeft=current*frame.scrollWidth/before-frame.clientWidth/2;
    frame.scrollTop=center*frame.scrollHeight/oldHeight-frame.clientHeight/2;
  });
  const legend=el("div",null,"firmament-legend");
  for(const key of ["Combat","Life","Allocated","Path preview"])legend.append(el("span",key,key.toLowerCase().split(" ")[0]));
  const tools=el("div",null,"firmament-tools");tools.append(legend,field("Zoom",level));
  frame.append(map);
  root.append(tools,frame,details);
  show(active);
  return root;
}
