// Replay complete recipes against installed source save/skill/effect and price views.
import * as maker from "./src/systems/spell/spellMaker.js";
import {applySpell} from "./src/systems/effects.js";
import {chapterPriced} from "./src/net/npcChapterLaw.js";
import * as power from "./src/systems/spell/spellPower.js";
import {castRate} from "./src/systems/castSpeed.js";


globalThis.location = {search: "?online"};
const upstream = "a3eb1605ea1dc391b691fe314377458a7e63e483";
const d = (chance, spell = 1) => ({effect_id:"5,255", chance_base:chance,
                                  chance_increment:spell, chance_per_level:12});
const h = (a, b=a) => ({effect_id:"4,0", base_low:a, base_high:b, plus_low:2,
                        plus_high:2, per_level:7});
const examples = [
  ["pair", [h(3),h(9)], {}],
  ["slope", [d(14)], {}],
  ["challenging_full", [h(8),d(100)], {target_hp:6}],
  ["gold_frontier", [d(100), h(8)], {target_hp:6}],
  ["magicka", [h(3,4),d(20),h(9)], {target_hp:18, level:12}],
  ["pierce", [h(4),d(60)], {pierce:20, resist_mods:[0,0,0,0,10]}],
  ["immune", [d(55),h(9)], {immune:2}],
  ["native_hazard", [d(60),d(100)], {immune:0, willpower:90}],
  ["toll", [h(2),h(2),h(1)], {live_skill:179, price_factor:.85}],
];

function slots(recs) {
  return recs.map(x => x.effect_id === "4,0" ? {type:4,subType:0,
    settings:{magnitudeBaseLow:x.base_low, magnitudeBaseHigh:x.base_high, magnitudeLevelBase:x.plus_low,
      magnitudeLevelHigh:x.plus_high, magnitudePerLevel:x.per_level}} : {type:5,subType:255,
    settings:{chanceBase:x.chance_base, chanceMod:x.chance_increment, chancePerLevel:x.chance_per_level}});
}
function measure(id, offers, mod) {
  const context = {level:10, live_skill:85, climb:35, speed:70, available_sp:20000,
    target_hp:25, willpower:50, price_factor:1, ...mod};
  const shapes = cells => maker.buildCustomSpell({slots:slots(cells), name:"Oracle", rangeType:2, element:4, index:-42000});
  const selected = shapes(offers);
  const census = maker.updateAllowedButtons(slots(offers));
  const player = {isPlayer:true,_online:true, isMentoring:false, level:context.level, stats:{speed:context.speed},
    skills:Array(35).fill(0), skillOverrides:{22:context.live_skill}, masteredSkills:[],
    magicka:context.available_sp, maxMagicka:context.available_sp, skillUses:Array(35).fill(0),
    activeEffects:[], career:{}, items:[{type:0,group:"MiscItems",templateIndex:maker.SPELLBOOK_TEMPLATE_INDEX}], spells:[], goldPieces:0};
  player.skills[22] = context.climb;
  power.registerSpellPierceMod("frozen-range", () => context.pierce ?? 0);
  const quotes = maker.spellMakerCost(selected, player);
  const price = chapterPriced(quotes.gold, context.price_factor);
  player.goldPieces = price;
  const market = maker.validateSpellPurchase({entity:player, slots:slots(offers), goldCost:price, name:"Native"});
  maker.purchaseSpell(player, selected, price);
  function access(agent, input, data, keys) {
    let at = 0;
    const resistances = ["fire","frost","poison","shock","magic"].map((e,j) => [e,(context.resist_mods ?? [])[j] ?? 0]);
    const target = {health:input, isPlayer:false, stats:{willpower:context.willpower},
      _mods:{resist:Object.fromEntries(resistances)}, career:{immunityFlags:context.immune ?? 0}, activeEffects:[]};
    const lost = [];
    const roll = () => {
      if (at >= keys.length) throw new Error("Discrepancy in the exact spell path tape");
      return keys[at++];
    };
    const hit = applySpell(data, context.level, target, {hurt:(n) => {
      lost.push(n); target.health = Math.max(0,target.health - n);
    }}, roll, {entity:agent});
    return {dam:hit.damage, h:target.health, plan:lost};
  }
  // For each cast, select output IDs by replaying the actual in-game source routes against
  // a condensed matrix of all possible remaining-health totals. Timing/price is a
  // complete ordered spell record; the scenario's scripted input is a black-box cast.
  let recent = new Map([[context.target_hp, 1]]), damage=0, trace=0;
  for (const bundle of offers) {
    const strong = bundle.effect_id === "4,0";
    const spine = shapes([bundle]);
    const rows = Array.from({length:strong ? bundle.base_high-bundle.base_low+1 : 100}, (_,j)=>j);
    let newSpace = new Map();
    for(const [s,weight] of recent) {
      const charge = weight/(100*rows.length);
      for (const x of rows) for(let reach=0;reach<100;reach++) {
        const next = (x+.5)/rows.length, y = (reach+.5)/100;
        const pool = strong ? [next, 0.5, y] : [next,y];
        const observed = access(player,s,spine,pool);
        newSpace.set(observed.h, (newSpace.get(observed.h) ?? 0)+charge);
        damage += observed.dam*charge;
        trace++;
      }
    }
    recent=newSpace;
  }
  const profile = new Array(24).fill(.16);
  const goldInput = [0.02, .99, .81, .13, .91, .88, .27, .34, .86, .28, .98, .12];
  const view = [access(player,context.target_hp,selected,profile),
                access(player,context.target_hp,selected,goldInput)];
  const hp = [...recent].reduce((s,[value, paths])=>s+(context.target_hp-value)*paths,0);
  return {id, context, spell:{element:4,range_type:2,effects:offers}, estimate:{expected_health_loss:hp,
    expected_damage:damage, kill_probability:recent.get(0)??0, dps: hp/(.7/castRate(player)),
    cost_sp:quotes.sp,purchase_gold:price},specific:{available:market.ok,after:player.goldPieces,
      trajectory_count:trace, price:quotes.gold,sp:quotes.sp,masks:census,ordered_stages:view}};
}
console.log(JSON.stringify({source_sha:upstream, mode:"online_snapshot",
  observed:"Game-owned spell cost, magnitude, target and retained effect-path replay",paths:["systems/spell/spellMaker.js#validateSpellPurchase,spellMakerCost",
    "systems/effects.js#applySpell", "systems/spellcast.js#savingChance,savingThrow"],
  examples:examples.map(r => measure(...r))}));
