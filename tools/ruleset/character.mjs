// Only the storage backing and character observations are synthetic.
import {snapshotPlayer} from './src/systems/save/save.js';
import {saveSlot} from './src/systems/save/saveSlots.js';
import {exportSavesZip} from './src/systems/save/saveTransfer.js';
import {buildCustomSpell} from './src/systems/spell/spellMaker.js';

const records = new Map();
const storage = {
  get length() { return records.size; },
  key: i => [...records.keys()][i],
  getItem: key => records.get(key) ?? null,
  setItem: (key, value) => records.set(key, String(value)),
  removeItem: key => records.delete(key),
};
const spell = buildCustomSpell({
  name: 'Ember', rangeType: 1, element: 0, index: -500,
  slots: [{type: 4, subType: 0, settings: {magnitudeBaseLow: 4, magnitudeBaseHigh: 6}}],
});
for (const [n, name] of ['Arden', 'Rhea'].entries()) {
  const caster = {
    characterId: 'synthetic-caster-' + n, name, raceId: 1, gender: 'female', level: 5 + n,
    health: 25, maxHealth: 35, magicka: 42, maxMagicka: 70, goldPieces: 92,
    career: {name: 'Caster', hitPointsPerLevel: 8}, chargenDone: true,
    stats: {strength: 50, intelligence: 60, willpower: 55, agility: 45, endurance: 50,
            personality: 45, speed: 65, luck: 50},
    skills: Array(35).fill(52), masteredSkills: [], spells: [{index: 18}, spell],
    items: [{group: 'Jewellery', templateIndex: 135, equipSlot: 4, currentCondition: 75,
             maxCondition: 75, uid: '0000000000000001'},
            {group: 'Jewellery', templateIndex: 135, name: 'Ring of Practice', rarity: 'magic',
             uid: '0000000000000002', currentCondition: 75, maxCondition: 75,
             affixes: [{id:'skill',param:34,value:8}, {id:'castSpeed',value:6}]},
            {group: 'MiscItems', templateIndex: 132}],
    otherItems: [{group: 'Weapons', templateIndex: 129, material: 0, currentCondition: 0}],
    wagonItems: [{group: 'Weapons', templateIndex: 113, material: 0}],
  };
  const snap = snapshotPlayer(caster, {classicMinutes: 1800 + n});
  const result = saveSlot(name, 'Fixture', snap, {storage, now: 1780000000000 + n});
  if (!result.ok) throw new Error('Game source could not write its fixture slot');
}
console.log(JSON.stringify({zip: Buffer.from(exportSavesZip(storage)).toString('base64')}));
