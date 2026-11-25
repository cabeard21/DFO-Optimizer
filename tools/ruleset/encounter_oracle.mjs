// Runs in a temporary tree containing only authenticated objects from the pinned game.
import {applySpell, tickActiveEffects} from "./src/systems/effects.js";
import {calculateCastCost} from "./src/systems/spellcost.js";
import {sweepFoes, sphereOverlapsCapsule, EXPLOSION_RADIUS, PLAYER_BODY_RADIUS} from "./src/systems/spellcast.js";
import {PATHS, PATH_NUMBERS, pathCastSchool} from "./src/systems/arcanePaths.js";
import * as powers from "./src/systems/arcanePowers.js";
import {setPlayerDoor} from "./src/systems/playerDoor.js";
import {_resetPlayerHealForTests} from "./src/systems/playerHeal.js";
import {lootKill, WELLSPRING_CAP} from "./src/systems/loot/lootPowers.js";
import {setPref} from "./src/systems/uiPrefs.js";
import {createPlayerMagic} from "./src/scenes/hostMagic.js";
import {MARTIAL_PATHS} from "./src/systems/martialPaths.js";
import * as martial from "./src/systems/martialPowers.js";
import {hurtPlayer} from "./src/characters/playerEntity.js";
import {remarkPlayerBlow} from "./src/systems/sigil/sigilSetPowers.js";
import {treeStats, treeFault, pointsLeft} from "./src/net/firmament/firmamentLaw.js";

globalThis.location = {search: "?online"};
setPref("lootRarity", true);
powers.setArcanePowersVoice({say: () => {}});
let clock = 0;
powers._setArcanePowersClockForTests(() => clock);
const player = (path=null) => ({
  isPlayer:true, _online:true, level:10, stats:{speed:50,willpower:50},
  skills:Array(35).fill(60), masteredSkills:path?.schools ?? [],
  arcanePath:path?.id ?? null, activeEffects:[], items:[], career:{},
  health:50,maxHealth:100,magicka:0,maxMagicka:200,
});
const standard = {
  magnitudeBaseLow:3, magnitudeBaseHigh:9, magnitudeLevelBase:1, magnitudeLevelHigh:3,
  magnitudePerLevel:5, durationBase:2, durationMod:1,durationPerLevel:12,
  chanceBase:20, chanceMod:1, chancePerLevel:5,
};
const spell = (type, subType, self) => ({
  name:"oracle", rangeType:self ? 0 : 2, element:4, effects:[{type,subType,...standard}],
});
const timeline = (values) => {
  let count = 0;
  const next = () => {
    if (count >= values.length) throw new Error("The source consumed extra draws");
    return values[count++];
  };
  return {next, count:()=>count};
};
function observe(type, sub, self, values) {
  const me = player();
  const target = self ? me : {health:30, maxHealth:30, stats:{willpower:50}, activeEffects:[], career:{}};
  const s = spell(type,sub,self);
  const draws = timeline(values);
  const sinks = {
    hurt:n=>{target.health=Math.max(0,target.health-n);},
    heal:n=>{target.health=Math.min(target.maxHealth,target.health+n);},
  };
  const before=target.health;
  const result=applySpell(s,10,target,sinks,draws.next,{entity:me});
  return {effect_id:type+","+sub, tape:values, draws:draws.count(), before, after:target.health,
    damage:result.damage, healed:result.healed, cast_sp:calculateCastCost(s,me).sp,
    active:target.activeEffects.filter(x=>["shield","regenerate"].includes(x.kind))
      .map(x=>({kind:x.kind,rounds:x.roundsRemaining,pool:x.shieldRemaining ?? null}))};
}
function shieldRenewal() {
  const me = player(), fresh=spell(35,255,true);
  const apply = () => applySpell(fresh,10,me,{},()=>.4,{entity:me});
  apply();
  const shield = me.activeEffects.find(x=>x.kind==="shield");
  const starting=shield.startingShield;
  shield.shieldRemaining=1;
  tickActiveEffects(me,{},()=>.4);
  apply();
  return {starting,after_recast:shield.shieldRemaining,remaining_rounds:shield.roundsRemaining};
}
function regenRenewal() {
  const me = player(), s=spell(18,255,true), clocked=[];
  const heal={heal:n=>{me.health=Math.min(me.maxHealth,me.health+n);}};
  const record=()=>clocked.push([me.health,me.activeEffects.find(x=>x.kind==="regenerate")?.roundsRemaining ?? -1]);
  const cast=()=>{applySpell(s,10,me,heal,()=>.1,{entity:me});record();};
  const tick=()=>{tickActiveEffects(me,heal,()=>.1);record();};
  cast(); cast(); tick(); tick(); cast(); tick(); tick(); tick();
  return clocked;
}
const sinksFor = (entity) => ({hurt:n=>{entity.health=Math.max(0,entity.health-n);},
                                heal:n=>{entity.health=Math.min(entity.maxHealth,entity.health+n);}});

function hostileDelivery() {
  const states=[];
  for (const flavor of ["reflect","resist","absorb","room","self"]) {
    const me=player(), target={health:60,maxHealth:60,magicka:0,maxMagicka:200,skills:Array(35).fill(60),
      career:{},activeEffects:[],stats:{willpower:50}};
    const foe={entity:target};
    const sequence=timeline(Array(40).fill(.99));
    const host=createPlayerMagic({playerEntity:me, playerSinks:sinksFor(me),foeSinks:()=>sinksFor(target),
      foes:()=>[foe],collider:{raycast:()=>Infinity},say(){},surfacePlayer(){},audio:{},renderer:{},
      absorbCtx:()=>({}),rolls:sequence.next});
    const bolt=spell(4,0,false);
    bolt.effects=[bolt.effects[0],{...bolt.effects[0]}];
    me.health=50; me.magicka=7;
    if (flavor==="reflect") target.activeEffects=[{kind:"spellReflection",chance:100}];
    if (flavor==="resist") target.activeEffects=[{kind:"spellResistance",chance:100}];
    if (["absorb","room","self"].includes(flavor)) target.career.spellAbsorptionFlags=4;
    if (flavor==="room") target.magicka=199;
    if (flavor==="self") me.career.spellAbsorptionFlags=4;
    const r=flavor==="self"
      ? host.applySpellToPlayer(bolt,10,{entity:me,cast:{cost:7}},{selfCastCost:7})
      : host.applySpellToFoe(bolt,10,foe,{entity:me,cast:{cost:7}});
    states.push({flavor,hp:me.health,sp:me.magicka,foe_hp:target.health,foe_sp:target.magicka,
      draws:sequence.count(),absorbed:r.absorbed ?? 0,resisted:r.resisted ?? 0,reflected:r.reflected ?? 0});
  }
  return states;
}

function signatureCast(id) {
  const definition=PATHS.find(p=>p.id===id);
  const caster=player(definition);
  const target={health:100,maxHealth:100,stats:{willpower:50},activeEffects:[],career:{}};
  const tape=timeline(Array(32).fill(.05));
  const recipe={path:id,index:definition.spell.index,name:definition.spell.nameEn,
    element:definition.spell.element,rangeType:definition.spell.rangeType,
    effects:definition.spell.slots.map(s=>({type:s.type,subType:s.subType,...standard,...s.settings}))};
  const host=createPlayerMagic({playerEntity:caster,playerSinks:sinksFor(caster),foeSinks:()=>sinksFor(target),
    foes:()=>[{entity:target}],collider:{raycast:()=>Infinity},say(){},surfacePlayer(){},audio:{},renderer:{},
    absorbCtx:()=>({}),rolls:tape.next});
  setPlayerDoor({player:()=>caster,castOnPlayer:(sp,opts)=>
    host.applySpellToPlayer(sp,10,null,{bypassSavingThrows:true,bypassChance:true,powerCast:opts.power})});
  const results=[];
  // Fixed draws below the save's floor would hide both riders. Give the hostile
  // target a critical-weakness career and use an explicit high save-roll tape.
  target.career.criticalWeaknessFlags=2|32;
  for(let i=0;i<2;++i) {
    const paid=calculateCastCost(recipe,caster).sp;
    const impact=host.applySpellToFoe(recipe,10,{entity:target},{entity:caster,cast:{cost:paid}});
    results.push({paid,damage:impact.damage,foe_hp:target.health,hp:caster.health,sp:caster.magicka,
      draws:tape.count(),shield:caster.activeEffects.find(x=>x.kind==="shield")?.shieldRemaining ?? 0,
      silence:target.activeEffects.find(x=>x.kind==="silenced")?.roundsRemaining ?? -1});
  }
  setPlayerDoor(null);
  return {id,results};
}

function martialCases() {
  martial._resetMartialPowersForTests();
  martial.setMartialPowersVoice({say:()=>{}});
  martial._setMartialPowersClockForTests(()=>0);
  _resetPlayerHealForTests();
  const make=(id,arcane=null)=>{
    const p=MARTIAL_PATHS.find(x=>x.id===id);
    const ent=player(arcane);
    ent.martialPath=id;
    ent.masteredSkills=[...p.skills,...(arcane?.schools ?? [])];
    return ent;
  };
  const hit=(actor,dmg)=>{
    const before=actor.health;
    remarkPlayerBlow({attacker:{isPlayer:false}});
    hurtPlayer(actor,dmg);
    return before-actor.health;
  };
  const guard=make("vanguard");
  const hits=[0,1,2,3].map(()=>hit(guard,7));
  const juggernaut=make("juggernaut");
  juggernaut.health=29;
  martial.martialHurt(juggernaut,{before:60,after:29});
  const bloodletter=make("bloodletter");
  setPlayerDoor({player:()=>bloodletter});
  martial.martialKill({isPlayer:false});
  const brawler=make("brawler");
  martial.martialRound(brawler);
  const evade=[];
  martial._setMartialPowersRandForTests(()=>{evade.push("martial");return .099;});
  powers._setArcanePowersRandForTests(()=>{evade.push("arcane");return .126;});
  const dancer=make("bladedancer",PATHS.find(x=>x.id==="seer"));
  const lost=hit(dancer,9);
  setPlayerDoor(null);
  return {paths:MARTIAL_PATHS.map(p=>({id:p.id,skills:p.skills,passive:p.passive.name,
      technique:p.technique.name})),guard:hits,juggernaut:juggernaut.health,kill_hp:bloodletter.health,
      round_hp:brawler.health,windborne:martial.martialFold(make("windrunner")).stats.speed,
      evasion:{order:evade,lost}};
}
const paths=PATHS.map(p=>{
  const me=player(p), foe={health:25,affinity:"Human",activeEffects:[]};
  me.health=20;
  me.activeEffects=[{kind:"shield",shieldRemaining:1}];
  const signature={path:p.id,index:p.spell.index};
  return {id:p.id, schools:p.schools, name:p.spell.nameEn, index:p.spell.index,
    range_type:p.spell.rangeType,element:p.spell.element,slots:p.spell.slots,
    damage_school:pathCastSchool(me,signature,22),awake:powers.awakePathId(me),
    low_hp_shielded_power:powers.pathSpellPower(me,foe),
    pierce:powers.pathSpellPierce(me,foe),cast_speed:powers.pathCastSpeed(me),
    shield_cost:powers.pathCastCost(me,100,spell(35,255,true))};
});
const of=id=>player(PATHS.find(p=>p.id===id));
function listeners() {
  _resetPlayerHealForTests();
  const mage=of("elementalist"),foe={health:20,careerIndex:0,activeEffects:[]};
  const a={},b={};
  const power=()=>powers.pathSpellPower(mage,foe);
  const land=cast=>powers.pathLanded({caster:mage,target:foe,cast,took:1,r:{damage:1}});
  clock=0;
  const conflux=[power()];
  land(a);conflux.push(power());
  land(a);conflux.push(power());
  land(b);conflux.push(power());
  clock=10;conflux.push(power());
  const necro=of("necromancer");
  setPlayerDoor({player:()=>necro});
  powers.pathKill(foe);
  const kill=[necro.health,necro.magicka];
  const results=[];
  for (const id of ["necromancer","spellbreaker","soulbinder"]) {
    _resetPlayerHealForTests();
    const actor=of(id);
    const record=PATHS.find(p=>p.id===id).spell;
    for(let i=0;i<2;++i)
      powers.pathLanded({caster:actor,target:foe,spell:{path:id,index:record.index},r:{damage:99},took:5,cast:{cost:11}});
    results.push({id,hp:actor.health,sp:actor.magicka});
  }
  _resetPlayerHealForTests();
  const healed=of("hierophant");
  healed.health=29; powers.pathHurt(healed,{before:80,after:29});
  const threshold=[healed.health];
  healed.health=29; powers.pathHurt(healed,{before:70,after:29}); threshold.push(healed.health);
  const worn=player();
  worn.maxMagicka=55;
  worn.equip={slots:[{group:"Jewellery",templateIndex:137,affixes:[{id:"wellspring",value:6}]},
                     {group:"Jewellery",templateIndex:137,affixes:[{id:"wellspring",value:6}]}]};
  setPlayerDoor({player:()=>worn});
  const refund=[];
  for (const target of [foe, {team:"PlayerAlly"},foe]) {lootKill(target); refund.push(worn.magicka);}
  setPlayerDoor(null);
  return {conflux,kill,signature:results,hurt:threshold,wellspring:refund,wellspring_cap:WELLSPRING_CAP};
}
const pos=[0,1,0];
const targets=[[2,0,0],[4.45,0,0],[4.451,0,0],[0,0,0]].map((feet,i)=>({
  id:i,ai:{feet,height:1.8,radius:.45},dead:i===3}));
const mageTree={start:"mg.start",keys:["mg.s1","mg.s2","mg.g","mg.r1","mg.c2.0","mg.c2.1"]};
console.log(JSON.stringify({source_sha:"a3eb1605ea1dc391b691fe314377458a7e63e483",
  effects:[observe(4,0,false,[0,.99,.85]),observe(5,255,false,[.01,.99]),
    observe(10,8,true,[0,.99]),observe(35,255,true,[0,.99]),observe(18,255,true,[0,.99])],
  shield:shieldRenewal(),regen:regenRenewal(),paths,numbers:PATH_NUMBERS,listeners:listeners(),
  defenses:hostileDelivery(),signature_casts:["battlemage","spellbreaker","necromancer"].map(signatureCast),
  martial:martialCases(),
  permanent:{tree:mageTree,stats:treeStats(mageTree),points:pointsLeft(mageTree.keys,8,0),fault:treeFault(mageTree,8,0)},
  area:{radius:EXPLOSION_RADIUS,hits:sweepFoes(pos,EXPLOSION_RADIUS,targets).map(x=>x.id),
    self_at_rim:sphereOverlapsCapsule(pos,EXPLOSION_RADIUS,[4.35,0,0],1.8,PLAYER_BODY_RADIUS)}}));
