// Run only after ruleset.run_adapter authenticates the imported modules.
import {GROUP_TEMPLATE_INDICES, templateByIndex} from './src/systems/item/itemTemplates.js';
import {getEquipSlot, equipTableOf, isForbiddenEquip, isBrokenItem, weaponProficiencyFlag, EQUIP_SLOTS} from './src/systems/equip.js';
import {getItemHands, ITEM_HANDS} from './src/characters/equipTable.js';
import {ARMOR_MATERIAL} from './src/systems/armorMaterials.js';
import {RRI_TEMPLATES, rriNativeMaterialValue} from './src/systems/roleplayRealismItems/rriItems.js';
import {ENCHANTMENT_TYPES} from './src/formats/magicDef.js';
import {AFFIX_RANGES, AFFIX_KINDS, AFFIX_COUNTS, setGem, gemLine, ALL_GEM_IDS, socketCap,
  kindParams, rollLootRarity, affixFold, LEGENDARY_POWERS, allLegendaries, legendariesFor, RARE_FLAVOURS} from './src/systems/loot/lootRarity.js';
import {FOCUS_CAP, POTENCY_CAP, CAST_SPEED_CAP, lootCastCost, lootCastSpeed, lootSpellPower} from './src/systems/loot/lootPowers.js';
import {ENHANCE_SKILL_MOD} from './src/systems/enchantments.js';
import {setPref} from './src/systems/uiPrefs.js';
import {SKILLS} from './src/systems/skills.js';
import {createRandomJewellery, createRandomArmor, createRandomWeapon} from './src/systems/loot/loot.js';

setPref('lootRarity', true);
const slots = Object.fromEntries(Object.entries(EQUIP_SLOTS).filter(([, n]) => n >= 0 && n < 27));
const groups = ['Jewellery', 'Weapons', 'Armor', 'Gems', 'MensClothing', 'WomensClothing'];
const reviewedRriArmor = [520, 522, 525];
const templates = {};
for (const group of groups) {
  const indices = GROUP_TEMPLATE_INDICES[group];
  for (const index of group === 'Armor' ? [...indices, ...reviewedRriArmor] : indices) {
    const item = {group, templateIndex: index};
    const entity = {};
    const first = getEquipSlot(entity, item);
    const choices = first === -1 ? [] : [first];
    if (first !== -1) {
      equipTableOf(entity)[first] = item;
      const second = getEquipSlot(entity, item);
      if (second !== first && second !== -1) choices.push(second);
    }
    const rri = reviewedRriArmor.includes(index);
    const base = rri ? RRI_TEMPLATES.find(row => row.index === index) : templateByIndex(index);
    templates[index] = {name: base.name, group, slots: choices, hands: getItemHands(item, {bowLeftHand: false}),
      switch_hands: getItemHands(item, {bowLeftHand: true}), weapon_mask: group === 'Weapons' ? weaponProficiencyFlag(item) : 0,
      socket_max: socketCap({...item, rarity:'rare'}), weight_kg: base.baseWeight};
    if (rri) {
      templates[index].native_armor_families = Object.fromEntries(Object.values(ARMOR_MATERIAL).map(material =>
        [material, rriNativeMaterialValue({...item, material}) >> 8]));
    }
  }
}
const affixes = Object.fromEntries(Object.entries(AFFIX_KINDS).map(([id, kind]) => [id, {
  groups: kind.groups, params: kind.params ?? null, proc: !!kind.proc, technique: !!kind.technique,
  range: AFFIX_RANGES[id], garment_params: kindParams(id, {group:'MensClothing',templateIndex:141}),
}]));

// Keep witnessed draws for each base template and caster-facing line.
// Each candidate is minted by the actual loot entry point. Counters are draw seeds,
// not probabilities. No generated copy is recorded as owned or currently for sale.
const minted = [];
const bases = new Map();
for (const factory of [r => createRandomJewellery(r), r => createRandomArmor(45, r), r => createRandomWeapon(45, r)]) {
  for (let j = 0; j < 512; j++) {
    const sample = factory(() => (j + 0.5) / 512);
    if (!bases.has(sample.templateIndex)) bases.set(sample.templateIndex, {
      group:sample.group, templateIndex:sample.templateIndex,
      ...(Number.isInteger(sample.material) ? {material:sample.material} : {}),
    });
  }
}
for (const base of bases.values()) {
  if (!templates[base.templateIndex]?.slots.length || reviewedRriArmor.includes(base.templateIndex)) continue;
  const found = new Map();
  const best = new Map();
  for (let seed = 1; seed <= 3000; seed++) {
    let state = Math.imul(seed, 2654435761) >>> 0;
    const rolls = () => ((state = (Math.imul(state, 1664525) + 1013904223) >>> 0) / 4294967296);
    const item = {...base};
    rollLootRarity([item], {kind:'pile',tier:6,boss:false}, {rolls, luck:50, find:1, level:45});
    if (item.rarity !== 'magic' || item.cursed || item.imprint || item.sigil || item.enchantments?.length || item.sockets?.length) continue;
    for (const a of item.affixes) {
      const key = a.id === 'skill' && a.param === SKILLS.Destruction ? 'destruction'
        : a.id === 'stat' && a.param === 'speed' ? 'speed' : a.id;
      if (!['potency','castSpeed','focus','speed','destruction'].includes(key)) continue;
      const record = {item:{...base,rarity:item.rarity,name:item.name,affixes:item.affixes}, seed};
      if (!found.has(key)) found.set(key, record);
      if (!best.has(key) || best.get(key).value < a.value) best.set(key, {...record,value:a.value});
    }
  }
  const used = new Set();
  for (const [kind, choices] of [['witness',found],['hypothetical',best]]) {
    for (const [line, {item,seed}] of choices) {
      if (!used.has(seed)) minted.push({kind, line, seed, item});
      used.add(seed);
    }
  }
}
const catalog = {slots, templates, affixes, hands:ITEM_HANDS, armor_materials:ARMOR_MATERIAL,
  enchantment_types:ENCHANTMENT_TYPES, enhance_skill_value:ENHANCE_SKILL_MOD, destruction_id:SKILLS.Destruction,
  caps:{cost_pct:FOCUS_CAP, cast_speed_pct:CAST_SPEED_CAP, power_pct:POTENCY_CAP}, affix_counts:AFFIX_COUNTS,
  gem_lines:Object.fromEntries(['Weapons','other'].map(group=>[group,Object.fromEntries(ALL_GEM_IDS.map(id=>[id,gemLine({group},id)]))])),
  rare_flavours:Object.fromEntries(Object.entries(RARE_FLAVOURS).map(([g,ls])=>[g,ls.filter(x=>!x.retired).map(({type,param})=>({type,param}))])),
  legendary:Object.fromEntries(allLegendaries().map(r=>[r.id, {group:r.group, templates:Object.keys(templates).map(Number).filter(i=>legendariesFor({templateIndex:i,group:templates[i].group}).some(x=>x.id===r.id)),
    affixes:r.affixes,enchantment:r.enchantment??null,power_kind:(LEGENDARY_POWERS[r.id]??r.power)?.kind??null,
    pierce:(LEGENDARY_POWERS[r.id]??r.power)?.points??0}])),
  minted
};

function eligibility(index, material, career, condition=1) {
  const item = {group:templates[index].group,templateIndex:index,material,currentCondition:condition};
  return {item,career,can_equip:!isForbiddenEquip(career,item)&&!isBrokenItem(item)&&getEquipSlot({},item)!==-1};
}
function modifierCase(item) {
  const entity = {isPlayer:true,items:[item]};
  equipTableOf(entity)[getEquipSlot(entity,item)] = item;
  const m = affixFold(entity);
  return {item,expected:{destruction:m.skills[SKILLS.Destruction]??0, intelligence:m.stats.intelligence??0,
    speed:m.stats.speed??0, cost_pct:100-lootCastCost(entity,100), cast_speed_pct:lootCastSpeed(entity),
    power_pct:lootSpellPower(entity,{isPlayer:false})}};
}
const socketed = {group:'Jewellery',templateIndex:135,rarity:'rare',
  affixes:[{id:'stat',param:'speed',value:6},{id:'skill',param:22,value:13},{id:'weight',value:25}],
  enchantments:[{type:ENCHANTMENT_TYPES.GoodRepWith,param:1}],sockets:['empty']};
setGem(socketed,'malachite');
const oracle = {eligibility:[],modifiers:[
  modifierCase(socketed), ...minted.filter(x=>x.item.templateIndex===135).map(x=>modifierCase(x.item)),
  modifierCase({group:'Armor',templateIndex:520,material:0,rarity:'magic',
    affixes:[{id:'skill',param:SKILLS.Destruction,value:5},{id:'skill',param:SKILLS.Mysticism,value:7}]}),
  modifierCase({group:'Armor',templateIndex:525,material:0,rarity:'magic',affixes:[{id:'armor',value:5}]}),
]};
for (const index of [102,109,112,113,115,128,130,135,140,...reviewedRriArmor])
 for (const material of (templates[index].group === 'Armor' ? [0,256,259,512,513,521] :
   templates[index].group === 'Weapons' ? [0,1,9] : [0]))
  for (const career of [{},{weaponArmorShieldsBitfield:1},{weaponArmorShieldsBitfield:8191},{forbiddenMaterialsFlags:2},
    ...(reviewedRriArmor.includes(index) ? [6,7,8].map(bit => ({weaponArmorShieldsBitfield:1 << bit})) : [])])
   oracle.eligibility.push(eligibility(index,material,career));
console.log(JSON.stringify(process.argv[2]==='oracle'?oracle:catalog));
