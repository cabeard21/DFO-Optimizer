// Online page and fixed random draws take the place of the browser and its RNG.
// All tally, settling, training, birth and specialization outputs come from game exports.
import {rollStats, rollSkills, spendPoolLowest, applyCharacter, defineLiveMaxMagicka, defineLiveMaxHealth} from './src/systems/chargen.js';
import {buildCustomCareer} from './src/systems/customClass.js';
import {STAT_KEYS_ORDER} from './src/systems/statMods.js';
import {assignSkillSpellbook, assignSkillEquipment, RRI_SPELLS} from './src/systems/roleplayRealismItems/rriKits.js';
import {calculateCastCost, castSchool} from './src/systems/spellcost.js';
import {setRenownLayer} from './src/systems/renownLayer.js';
import {goldStack, takeOneInto} from './src/systems/inventory.js';
import {levelUpSkillSum, tallySkill} from './src/systems/skills.js';
import {skillUsesForAdvancement, SKILL_ADVANCEMENT_MULTIPLIER, raiseSkills, checkForLevelUp,
        applyLevelUp, bonusPoolFor, raisePriceLevel} from './src/systems/advancement.js';
import {effectiveSkill, noteSkillChallenge, overcapTallyWeight} from './src/systems/skillSoftcap.js';
import {onlineLevelFor, birthSkillOk} from './src/systems/levelClimb.js';
import {masterSkill} from './src/systems/masterSkills.js';
import {pathChoices, choosePath} from './src/systems/arcanePaths.js';
import {signatureOffers} from './src/systems/signatureSpells.js';
import {resetSpec} from './src/systems/specReset.js';
import {trainSkill, tooSkilledToTrain, trainingTooSoon} from './src/systems/guild/guildServiceActions.js';
import {nightDue, topUpRest} from './src/systems/rest/restAct.js';
globalThis.location = {search:'?online'};
const emit=console.log.bind(console);
console.log=console.error.bind(console);
Math.random=()=>.5;
const career = buildCustomCareer({name:'Source fixture',hp:8,skills:[22,23,24,25,26,27,0,1,2,3,4,5],
  stats:Object.fromEntries(STAT_KEYS_ORDER.map(k=>[k,50]))});
let seed=42;
const stream = () => { seed=(Math.imul(1664525,seed)+1013904223)>>>0; return seed / 4294967296; };
const draws=[];
const roll=()=>{const x=stream(); draws.push(x); return x;};
const sr=rollStats(career,roll), sk=rollSkills(career,roll);
const rolls={attribute_bonus:draws.slice(0,8).map(x=>Math.floor(x*11)),attribute_pool:sr.bonusPool,
             misc_bonus:draws.slice(9,44).map(x=>Math.floor(x*4)),career_bonus:draws.slice(44).map(x=>Math.floor(x*4))};
spendPoolLowest(sr.stats,STAT_KEYS_ORDER,sr.bonusPool);
for(const key of ['primary','major','minor']) spendPoolLowest(sk.skills,career[key+'Skills'],sk.groupPools[key]);
const actor={isPlayer:true,_online:true,reflexes:2,items:[],gender:'male'};
applyCharacter(actor,career,-1,{stats:sr.stats,skills:sk.skills,rolls:()=>.5});
const book=assignSkillSpellbook(career,{get:index=>({index})});
assignSkillEquipment(actor,{rolls:()=>.5});
const birth={rolls,skills:[...actor.skills],attributes:STAT_KEYS_ORDER.map(k=>actor.stats[k]),
  hp:actor.health,sp:actor.magicka,fatigue:actor.fatigue,gold:actor.goldPieces,
  known:book.map(s=>s.index).sort((a,b)=>a-b),has_spellbook:actor.items.some(it=>it.templateIndex===132),
  inventory:actor.items.map(({uid,foundAt,createdAt,...row})=>row),
  starting_sum:actor.startingLevelUpSkillSum,current_sum:actor.currentLevelUpSkillSum,
  last_check:actor.lastSkillCheckTime,legal_birth:birthSkillOk(actor)};
const events=[];
const add=(kind,input,output)=>events.push({kind,input,output});
for(const skill of [0,22,27,34]) for(const raw of [1,50,99,100,125,150,199]) {
  const level=raw<100?7:35, m=SKILL_ADVANCEMENT_MULTIPLIER[skill];
  add('price',{skill,raw,level,advancement_multiplier:.3},skillUsesForAdvancement(raw,m,.3,level));
}
for(const raw of [99,100,101,124,125,149,150,174,175,199,200]) add('effective',{raw},effectiveSkill(raw));
for(const anchor of [144,154,169]) for(const held of [anchor,anchor+2,600,799,800,840]) add('online_level',{anchor,held},onlineLevelFor(anchor,held));
const clone=()=>({...actor,career:{...career},stats:{...actor.stats},skills:[...actor.skills],skillUses:Array(35).fill(0),masteredSkills:[]});
for(const [delay,uses] of [[360,300],[361,300],[361,32767],[361,32768],[361,65536],[361,65538]]) {
  const e=clone(); e.skillUses[22]=uses; const at=e.lastSkillCheckTime+delay;
  raiseSkills(e,at,()=>.5,()=>{});
  add('check',{delay,skill:22,uses},{raw:e.skills[22],uses:e.skillUses[22],last_check:e.lastSkillCheckTime});
}
const e=clone();e.skills[22]=99;e.skills[23]=100;e.skillUses[22]=10000; e.lastSkillCheckTime=100;
raiseSkills(e,461,()=>.5,()=>{});
add('cross_100',{},e.skills[22]);
e.skillUses[22]=150;
add('master',{skill:22},{ok:masterSkill(e,22).ok,uses:e.skillUses[22]});
masterSkill(e,23);
const p=pathChoices(e)[0];
add('choose',{id:p.id},{ok:choosePath(e,p.id).ok,offered:signatureOffers(e).map(sp=>sp.index),owned:(e.spells??[]).length});
e.goldPieces=200000;
add('reset',{id:p.id},{ok:resetSpec(e,'arcane').ok,balance:e.goldPieces,path:e.arcanePath});
const trainee=clone();
for(const value of [49,50,51]) {trainee.skills[22]=value;add('trainer_cap',{value},tooSkilledToTrain(trainee,null,22));}
for(const t of [719,720]) add('trainer_gate',{t},trainingTooSoon({timeOfLastSkillTraining:0},t));
add('training',{skill:22,roll:.5},trainSkill(trainee,22,850,()=>.5));
for(const elapsed of [119,120]) add('night_due',{elapsed},nightDue({restNightAt:100},100+elapsed));
for(const skill of [22,29,0]) for(const foe of [null,8,15,40]) {
  const target=clone(); target.skills[skill]=150;
  if(foe!==null) noteSkillChallenge(target,{level:foe},100);
  const times=[100,200,6101,60100];
  add('real_use',{skill,foe,raw:150,amount:15,times},times.map(t=>overcapTallyWeight(target,skill,15,150,t)));
}
const advanced=clone();advanced.skills[22]=150; advanced.masteredSkills=[22];advanced.skillProgress=Array(35).fill(0);advanced.skillUses[22]=60000;
for(const t of [361,722]) {
  raiseSkills(advanced,actor.lastSkillCheckTime+t,()=>.5,()=>{});
  add('bank',{t},{raw:advanced.skills[22],uses:advanced.skillUses[22],progress:advanced.skillProgress[22],price_level:raisePriceLevel(advanced)});
}
const capped=clone();capped.level=44;capped.skills=Array(35).fill(100);
capped.masteredSkills=[22,23,24,25,26,0];
for(const id of capped.masteredSkills.slice(0,5)) capped.skills[id]=200;
capped.currentLevelUpSkillSum=levelUpSkillSum(capped);
const owed=checkForLevelUp(capped),pool=bonusPoolFor(capped,()=>.999,{online:true});
applyLevelUp(capped,(a,n)=>{a.intelligence+=n;},()=>.5,pool);
capped.skillUses[0]=100000;
raiseSkills(capped,actor.lastSkillCheckTime+361,()=>.5,()=>{});
add('post_cap',{},{owed,pool,level:capped.level,minor:capped.skills[0],ready:capped.readyToLevelUp});
for (const id of [991,995,993,992,997,998]) {
  const spell=Object.values(RRI_SPELLS).find(s=>s.index===id);
  for (const raw of [1,35,100,150,200]) {
    const e=clone(), school=castSchool(e,spell,spell.effects[0]);
    e.skills[school]=raw;
    if (raw>=100) e.masteredSkills=[school];
    add('school_release',{id,raw,school},calculateCastCost(spell,e,{online:true,portMods:false}).sp);
  }
}
for (const rollSeed of [0,42,0xffffffff]) {
  const vitals=clone();
  vitals.career.hitPointsPerLevel=30;
  vitals.career.abilityFlagsAndSpellPointsBitfield=0;
  Object.assign(vitals,{level:1,maxHealth:55,health:37,magicka:12});
  vitals.stats.endurance=48;
  vitals.stats.intelligence=65;
  defineLiveMaxHealth(vitals);
  defineLiveMaxMagicka(vitals);
  setRenownLayer(vitals,1);
  let value=rollSeed;
  for (let level=2;level<=5;level++) {
    vitals.readyToLevelUp=true;
    const input={level,hp_roll_state:value};
    applyLevelUp(vitals,(stats,n)=>{stats.endurance+=2; stats.intelligence+=n-2;},()=>{
      value=(Math.imul(1664525,value)+1013904223)>>>0; return value / 4294967296;
    },5);
    add('level_vitals',{rollSeed,...input},{raw_max_hp:vitals.rawMaxHealth,max_hp:vitals.maxHealth,
      hp:vitals.health,max_sp:vitals.maxMagicka,sp:vitals.magicka,hp_roll_state:value});
  }
  topUpRest(vitals,'bed',null);
  add('full_bed',{rollSeed},{hp:vitals.health,sp:vitals.magicka});
}
const collector={goldPieces:18,items:[]}, coins=goldStack(321), container=[coins];
takeOneInto(collector,container,coins);
const repeated=takeOneInto(collector,container,coins);
add('collect_gold',{gold:18,amount:321},{gold:collector.goldPieces,remaining:container.length,
  repeated:repeated!==null,pack_items:collector.items.length});
emit(JSON.stringify({source_sha:'a3eb1605ea1dc391b691fe314377458a7e63e483',birth,events}));

