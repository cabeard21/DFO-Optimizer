// run_adapter authenticates the upstream modules before this script runs.
import fs from 'node:fs';
import {ChargenFlow} from './src/ui/chargen.js';
import {weaponSkillUsed} from './src/characters/weapons.js';
import {effectiveUnitWeightInKg, GOLD_PIECE_WEIGHT_KG} from './src/systems/inventory.js';
import {maxEncumbrance} from './src/combat/formulas.js';
import {ARMOR_MATERIAL} from './src/systems/armorMaterials.js';
import {advancementMultiplier} from './src/systems/customClass.js';
import {spellPointMultiplier} from './src/systems/chargen.js';
import {assignSkillEquipment, assignSkillItems} from './src/systems/roleplayRealismItems/rriKits.js';
import {calculateCastCost} from './src/systems/spellcost.js';

const [progressionFile, templateFile] = process.argv.slice(2);
const emit = console.log.bind(console);
console.log = console.error.bind(console);
globalThis.location = {search: '?online'};
const {creation} = JSON.parse(fs.readFileSync(progressionFile));
const items = {};
const points = kg => {
  const units = Math.round(kg * 400);
  if (Math.abs(kg - units / 400) > 1e-10) throw Error('Unrepresentable item weight');
  return units;
};
for (const row of [...creation.kit_rows.flat(), ...Object.values(creation.common_kit).flat()]) {
  const key = [row.templateIndex, row.material ?? 'none'].join('/');
  const facts = {unit_weight: points(effectiveUnitWeightInKg(row)),
    skill: row.group === 'Weapons' ? weaponSkillUsed(row.templateIndex) ?? null : null};
  if (key in items && JSON.stringify(items[key]) !== JSON.stringify(facts)) throw Error('Ambiguous birth item weight');
  items[key] = facts;
}
const cuirasses = Object.entries(ARMOR_MATERIAL).filter(([,code]) => code >> 8 === 2).sort((a,b)=>a[1]-b[1])
  .map(([name,material])=>({name,material,units:points(effectiveUnitWeightInKg({templateIndex:102,group:'Armor',material}))}));
const templates = JSON.parse(fs.readFileSync(templateFile)).map(row=>{
  const flow = new ChargenFlow([],()=>0);
  flow.state='class'; flow.classListIndex=0; flow.useClass();
  const imported=flow.customImport(row.class);
  const difficulty=flow.customDifficulty(); flow.customExit();
  if (!imported.ok || imported.skipped.length || !flow.customCareer) throw Error('Manual template failed creator');
  return {name:row.class.name,race_id:row.race_id,difficulty,multiplier:advancementMultiplier(difficulty),
          magery:spellPointMultiplier(flow.customCareer.abilityFlagsAndSpellPointsBitfield)};
});

// Fixed low, middle and high tapes exercise the actual kit branches. Unique rows
// store only weight and melee equip inputs, independently of cosmetic RNG metadata.
const kitParts = [], partIndex = new Map(), variants = {};
function kitPart(actor) {
  const weapons = actor.items.filter(i => i.group === 'Weapons' && [28,29,31,32].includes(weaponSkillUsed(i.templateIndex)))
    .map(i=>[i.templateIndex, i.material, weaponSkillUsed(i.templateIndex), i.currentCondition]);
  const part = {units: points(actor.items.reduce((sum,it)=>sum + effectiveUnitWeightInKg(it)*(it.stackCount ?? 1),0)), weapons};
  const id=JSON.stringify(part);
  if (!partIndex.has(id)) { partIndex.set(id,kitParts.length); kitParts.push(part); }
  return partIndex.get(id);
}
for (const decile of [1,5,9]) {
  const rolls=()=>decile/10;
  Math.random = rolls;
  for (const gender of ['male','female']) {
    const common={isPlayer:true,_online:true,gender,items:[],career:{luck:50}};
    assignSkillEquipment(common,{rolls});
    for (const metal of [0,1]) for (const chain of [0,1]) {
      const career = {luck:0, forbiddenMaterialsFlags:metal*creation.iron_mask, weaponArmorShieldsBitfield:chain<<6};
      const rows=Array.from({length:35},(_,i)=>{
        const actor={isPlayer:true,_online:true,gender,career,items:[]};
        assignSkillItems(actor,i,rolls);
        return kitPart(actor);
      });
      variants[[decile,gender,metal,chain].join('/')] = [...rows,kitPart(common)];
    }
  }
}
const starterDamage = {};
for (const [skill, groups] of Object.entries(creation.starting_spells)) {
  for (const [group, ids] of Object.entries(groups)) {
    for (const record of creation.generated_records.filter(r=>ids.includes(r.index))) {
      const real = record.effects.filter(e=>e.type>=0);
      if (record.rangeType===0 || real.length!==1 || real[0].type!==4 || real[0].subType!==0) continue;
      const key=[skill,group].join('/');
      (starterDamage[key]??=[]).push({index:record.index,name:record.name,
        costs:Array.from({length:41},(_,raw)=>{
          const actor={isPlayer:true,_online:true,skills:Array(35).fill(raw),masteredSkills:[]};
          return calculateCastCost(record,actor,{online:true,portMods:false}).sp;
        })});
    }
  }
}
emit(JSON.stringify({items,cuirasses,templates,starter_damage:starterDamage,kit_sensitivity:{variants,parts:kitParts},gold_unit_weight:points(GOLD_PIECE_WEIGHT_KG),
  capacity:Array.from({length:101},(_,str)=>points(maxEncumbrance(str)))}));
