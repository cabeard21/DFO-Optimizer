// The server hashes JSON numbers before rendering them. Inputs such as 1.0
// and 9007199254740993 must survive a form edit even though Number alone
// cannot reproduce their original spelling.
const numbers=new WeakMap();
const parsed=new WeakSet();

function remember(parent,key,lexeme){
  let tokens=numbers.get(parent);
  if(!tokens){tokens=new Map();numbers.set(parent,tokens);}
  tokens.set(key,lexeme);
}
const container=value=>value!==null&&typeof value==="object";

export function parseDocument(text){
  let needsSource=false;
  const value=JSON.parse(text,function(key,item,context){
    if(container(item))parsed.add(item);
    if(typeof item==="number"){
      if(!context?.source)needsSource=true;
      else if(context.source!==String(item))remember(this,key,context.source);
    }
    return item;
  });
  if(needsSource){
    // In older browsers the reviver receives no context. Parse a parallel
    // tree with numeric literals quoted; quoted JSON strings stay untouched.
    const tokens=/"(?:\\[\s\S]|[^"\\])*"|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/g;
    const spellings=JSON.parse(text.replace(tokens,token=>token[0]==='"'?token:JSON.stringify(token)));
    function collect(parent,source){
      for(const [key,item] of Object.entries(parent)){
        if(container(item))collect(item,source[key]);
        else if(typeof item==="number"&&source[key]!==String(item))remember(parent,key,source[key]);
      }
    }
    if(container(value))collect(value,spellings);
  }
  return value;
}

// Form controls copy the edited container (and sometimes its arrays). Retain
// exact numeric siblings at unchanged paths. A newly parsed raw editor or a
// library character already owns its own authoritative spellings.
export function retainNumbers(before,after){
  if(before===after||!container(before)||!container(after)||parsed.has(after))return after;
  for(const [key,item] of Object.entries(after)){
    if(!Object.hasOwn(before,key))continue;
    if(container(item))retainNumbers(before[key],item);
    else if(typeof item==="number"&&Object.is(before[key],item)){
      const token=numbers.get(before)?.get(key);
      if(token!==undefined)remember(after,key,token);
    }
  }
  return after;
}

export function stringifyDocument(value,space=0,sorted=false){
  function encode(item,parent,key,indent){
    if(!container(item)){
      const token=typeof item==="number"&&parent?numbers.get(parent)?.get(key):undefined;
      return token!==undefined&&Object.is(Number(token),item)?token:JSON.stringify(item);
    }
    const array=Array.isArray(item),open=array?"[":"{",close=array?"]":"}";
    const inner=space?indent+" ".repeat(space):"",entries=[];
    const names=Object.keys(item);
    if(sorted&&!array)names.sort();
    for(const name of names){
      const child=item[name];
      const encoded=encode(child,item,name,inner);
      if(encoded===undefined&&!array)continue;
      const prefix=array?"":JSON.stringify(name)+(space?": ":":");
      entries.push(prefix+(encoded??"null"));
    }
    if(!entries.length||!space)return open+entries.join(",")+close;
    return open+"\n"+inner+entries.join(",\n"+inner)+"\n"+indent+close;
  }
  return encode(value,null,"","");
}
