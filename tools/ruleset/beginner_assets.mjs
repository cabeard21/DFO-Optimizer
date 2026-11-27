import { templateByIndex, mintCondition } from './src/systems/item/itemTemplates.js';
import { effectiveUnitWeightInKg } from './src/systems/inventory.js';
import { allowedTargetsOf, allowedElementsOf, buildCustomSpell, spinnerRange } from './src/systems/spell/spellMaker.js';
import { calculateCastCost } from './src/systems/spellcost.js';

const emit = console.log.bind(console);
console.log = console.error.bind(console);
const run = n => Array.from({ length: n }, (_, i) => i);
const items = {};
for (const [group, indices] of [
  ['Armor', run(11).map(i => i + 102)],
  ['Weapons', run(16).map(i => i + 113)]
]) {
  for (const index of indices) {
    const materials = group === 'Weapons' ? run(10)
      : index >= 109 ? [0, ...run(10).map(i => 512 + i)] : [0, 256, ...run(10).map(i => 512 + i)];
    for (const material of materials) {
      const item = mintCondition({ group, templateIndex: index, material });
      if (!templateByIndex(index) || item.maxCondition <= 0) throw Error('Invalid item template');
      const units = effectiveUnitWeightInKg(item) * 400;
      if (Math.abs(units - Math.round(units)) > 1e-8) throw Error('Inexact game weight');
      items[[index, material].join('/')] = [item.maxCondition, Math.round(units)];
    }
  }
}

const defense = [];
const actor = { isPlayer: true, _online: true, skills: Array(35).fill(50), masteredSkills: [] };
for (const [name, type, subType, duration] of [['Heal', 10, 8, false], ['Regenerate', 18, 255, true], ['Shield', 35, 255, true]]) {
  for (const [base, plus, rounds] of [[3, 1, 2], [8, 2, 3], [12, 3, 4], [18, 5, 5]]) {
    const settings = { magnitudeBaseLow: base, magnitudeBaseHigh: base,
      magnitudeLevelBase: plus, magnitudeLevelHigh: plus, magnitudePerLevel: 2,
      ...(duration ? {durationBase: rounds, durationMod: 1, durationPerLevel: 4} : {}) };
    const key = `${type},${subType}`;
    if (!(allowedTargetsOf(type, subType) & 1) || !(allowedElementsOf(type, subType) & 16)) throw Error('Illegal self spell');
    for (const [field, value] of Object.entries(settings)) {
      const [min, max] = spinnerRange(field, key);
      if (value < min || value > max) throw Error('Illegal defensive slider ' + field);
    }
    const spell = buildCustomSpell({slots: [{type, subType, settings}], index: -910002});
    defense.push({name: `${name} ${base}`, effect: {effect_id: key, base_low: base, base_high: base,
      plus_low: plus, plus_high: plus, per_level: 2,
      ...(duration ? {duration_base: rounds, duration_increment: 1, duration_per_level: 4} : {})},
      ...calculateCastCost(spell, actor, { online: true, portMods: false })});
  }
}
emit(JSON.stringify({items, defense}));
