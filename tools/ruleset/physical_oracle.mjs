// Use the ordinary online defaults of PCAAO and RRI's balanced weapon tables.
import { rriWeaponMinDamage, rriWeaponMaxDamage } from './src/systems/roleplayRealismItems/rriRealism.js';
import { rriAnimTimeOverride } from './src/systems/roleplayRealismItems/rriKits.js';
import { conditionMultipliersByMaterial, registerWeaponDamageOverride, weaponSkillUsed } from './src/characters/weapons.js';
import { weaponTypeForItem } from './src/combat/fpsWeapon.js';
import { swingHandling, blowSchedule } from './src/characters/weaponStates.js';
import { ARMOR_MATERIAL } from './src/systems/armorMaterials.js';
import { enemyEntityGroup } from './src/combat/enemyGroups.js';
import { MELEE_DISTANCE } from './src/characters/enemy/enemyMotor.js';
import { armorBodyParts, equipTableOf, EQUIP_SLOTS, weaponProficiencyFlag } from './src/systems/equip.js';
import { pcaaoAttackDamage, pcaaoProficiencyModifiers, pcaaoRacialModifiers,
         pcaaoArmorMaterialIdentifier, PCAAO_REDUCTION_ROWS, pcaaoModules } from './src/combat/pcaao.js';
import { ITEM_TEMPLATES, registerTemplateOverrides, templateByIndex } from './src/systems/item/itemTemplates.js';
import { RRI_TEMPLATE_PATCHES } from './src/systems/roleplayRealismItems/rriItems.js';
import { repoolWeapon } from './src/systems/conditionRepair.js';
import { onlineModSetting } from './src/systems/modSettings.js';
import { getItemHands, ITEM_HANDS } from './src/characters/equipTable.js';
import { SKILLS } from './src/systems/skills.js';

const names = ['strength','intelligence','willpower','agility','endurance','personality','speed','luck'];
const types = [-1, ...Array.from({length:16}, (_, i) => i+113)];
const item = (id, material=1, condition=100) => ({templateIndex:id, material,
  group:id>=113?'Weapons':'Armor',currentCondition:condition,maxCondition:100});
const online=(vendor,key)=>onlineModSetting(vendor,key,'?online');
const modules=pcaaoModules(key=>online('pcaao',key),online);
if (!online('roleplay-realism-items','Enabled') || !online('roleplay-realism-items','weaponBalance')
    || !modules.enabled || !modules.armorHitFormulaRedone || modules.equipmentDamageEnhanced
    || online('roleplay-realism','equipDamage'))
  throw Error('Unexpected ordinary online physical combat or weapon balance settings');
// These are the installRoleplayRealismItems registrations used by this lane.
registerTemplateOverrides(RRI_TEMPLATE_PATCHES);
registerWeaponDamageOverride({min:rriWeaponMinDamage,max:rriWeaponMaxDamage});
// These two source functions are sums of independent, integer-divided stats.
// Extract their per-attribute step breakpoints, checking every integer 0..100.
function terms(fn) {
  const evaluate = (i=-1, v=0) => fn(Object.fromEntries(names.map((k,j)=>[k,j===i?v:0])));
  const base = evaluate();
  const components = {};
  for (const field of ['damageMod','toHitMod']) {
    const divs = names.map((_,i) => {
      const values = Array.from({length:101}, (_, v)=>evaluate(i,v)[field]-base[field]);
      const first = values.findIndex(d=>d>0);
      if(values.some((n,v)=>n!==(first<0?0:Math.floor(v/first)))) throw Error('non-additive upstream term');
      return first;
    });
    components[field]=[base[field],...divs];
  }
  return components;
}
const weapons={}, modifiers={};
for (const id of types) {
  const w = id<0?null:item(id);
  const skill=w?weaponSkillUsed(id):SKILLS.HandToHand;
  const both=w?getItemHands(w)===ITEM_HANDS.Both:false;
  const mask=w?weaponProficiencyFlag(w):4;
  weapons[id]={skill,mask,span:w?[rriWeaponMinDamage(id),rriWeaponMaxDamage(id)]:[],
      weight:w?templateByIndex(id).baseWeight:0,both,handling:swingHandling(weaponTypeForItem(w),both,skill===SKILLS.ShortBlade)};
  if (w) {
    const rows=[ITEM_TEMPLATES[id]?.hitPoints, templateByIndex(id)?.hitPoints,
      ...RRI_TEMPLATE_PATCHES.filter(p=>p.index===id).map(p=>p.hitPoints)].filter(Number.isFinite);
    weapons[id].repool=conditionMultipliersByMaterial.map((multiplier,metal)=>{
      const conversions={};
      for(const base of rows){
        const oldMax=Math.trunc(base*multiplier/4);
        const copy={...item(id,metal),currentCondition:oldMax,maxCondition:oldMax};
        if(repoolWeapon(copy)) conversions[oldMax]=copy.maxCondition;
      }
      return conversions;
    });
  }
  if (!modifiers[skill]) {
    modifiers[skill]={expert:terms(stats=>pcaaoProficiencyModifiers({stats,career:{weaponArmorShieldsBitfield:mask<<16}},w))};
    for(let race=1;race<=8;race++)
      modifiers[skill][race]=terms(stats=>pcaaoRacialModifiers({stats,raceId:race},w,{raceId:race}));
  }
}
const materials={};
for(const m of Object.values(ARMOR_MATERIAL).filter(m=>m>=0)){
  materials[m]=[pcaaoArmorMaterialIdentifier(item(102,m)),pcaaoArmorMaterialIdentifier(item(109,m))];
}
const law={modules,weapons,modifiers,rows:PCAAO_REDUCTION_ROWS,materials,enemy_reach_mm:Math.round(MELEE_DISTANCE*1000),
    armor_parts:Object.fromEntries(Array.from({length:11},(_,i)=>[i+102,armorBodyParts(item(i+102))])),
    class_groups:Array.from({length:19},(_,i)=>enemyEntityGroup(i))};
const rows=[];
for (const weapon of [null,item(113,0),item(115,1),item(120,0,5)]) for (const incoming of [false,true])
  for (const roll of [0.01,0.4,0.95]) for (const protection of [null,item(102,513),item(112,0)]) {
    const make=(isPlayer)=>({isPlayer,isClass:!isPlayer,careerIndex:1,level:1,
       stats:Object.fromEntries(names.map(k=>[k,50])),skills:Array(35).fill(50),
       raceId:2,career:{},health:50,maxHealth:50});
    const attacker=make(!incoming),target=make(incoming);
    if(protection){
      const it={...protection};
      equipTableOf(target)[it.templateIndex===112?EQUIP_SLOTS.LeftHand:EQUIP_SLOTS.ChestArmor]=it;
    }
    let cursor=0, part=-1;
    const held=weapon?{...weapon}:null;
    const notes={};
    const damage=pcaaoAttackDamage(attacker,target,{weapon:held,rolls:()=>{cursor++;return roll;},
       notes,modules,onStruck:n=>{part=n;}});
    rows.push({weapon,protection,incoming,roll,damage,part,cursor,hit:!!notes.hit,condition:held?.currentCondition??0});
  }
// Sample independently allocated characters and mutable item condition across
// four actual consecutive blows. Each case records its initial input, draw
// count and every intermediate result, including after a piece breaks.
const varied=[];
for (let j=0;j<64;j++) {
  const attrs=names.map((_,k)=>15+(13*k+j*11)%86);
  const targetAttrs=names.map((_,k)=>10+(17*k+j*7)%91);
  const levels=[1+j%45,1+(j*3)%45], skills=[7+(j*7)%94,12+(j*9)%89];
  const race=1+j%8, careerIndex=j%19, incoming=j%3===1;
  const expert=0x3f0000, flags=[0,4,64,255][j%4];
  const c={weaponArmorShieldsBitfield:expert,attackModifierFlags:flags,abilityFlagsAndSpellPointsBitfield:4};
  const make=(s,st,lv,sk)=>({isPlayer:s,isClass:!s,careerIndex:s?-1:careerIndex,
     level:lv,stats:Object.fromEntries(names.map((k,i)=>[k,st[i]])),skills:Array(35).fill(sk),
     raceId:race,career:c,health:10,maxHealth:100,minMetalToHit:s?-1:j%10});
  const a=make(!incoming,attrs,levels[0],skills[0]);
  const t=make(incoming,targetAttrs,levels[1],skills[1]);
  const rawW=j%5===0?null:item(113+j%16,j%10,j%4===0?1:1+j%99);
  let weapon=rawW?{...rawW}:null;
  const coverings=[item(102,512+j%10,2+j%76),item(109+j%4,[0,256,513,515][j%4],1+j%77)];
  const worn=coverings.map(v=>({...v}));
  equipTableOf(t)[EQUIP_SLOTS.ChestArmor]=worn[0];equipTableOf(t)[EQUIP_SLOTS.LeftHand]=worn[1];
  let cursor=0,seed=1234+j*77;
  const rng=()=>{cursor++;seed^=seed<<13;seed^=seed>>>17;seed^=seed<<5;return (seed>>>0)/4294967296;};
  const outputs=[];
  for(let k=0;k<4;k++){
    const notes={}; let part=-1;
    const d=pcaaoAttackDamage(a,t,{weapon,rolls:rng,notes,
       modules,onStruck:n=>{part=n;}});
    outputs.push([d,!!notes.hit,part,cursor,weapon?.currentCondition??0,...worn.map(w=>w.currentCondition)]);
    if(weapon && weapon.currentCondition<=0)weapon=null;
  }
  varied.push({attrs,targetAttrs,levels,skills,race,careerIndex,incoming,career:c,rawW,coverings,metal:j%10,seed:1234+j*77,outputs});
}
const timing=[];
for(const id of types) for(const speed of [30,50,75,100]){
  const held=id<0?null:item(id),entity={stats:{strength:47,speed}};
  equipTableOf(entity)[EQUIP_SLOTS.RightHand]=held;
  const tick=rriAnimTimeOverride(speed,{entity,weaponType:weaponTypeForItem(held),usingRightHand:true});
  const schedule=blowSchedule({tick,frame:0,state:'StrikeLeft',isUnarmed:id<0},speed,null,.016667);
  timing.push({id,speed,hit:Math.round(schedule.hitAt*1e6),ready:Math.round(schedule.seconds*1e6)});
}
console.log(JSON.stringify({law,rows,timing,varied}));
