// The adapter runs against authenticated public game blobs at the shipped revision.
import {SKILL_ADVANCEMENT_MULTIPLIER, SKILL_RAISE_CHECK_INTERVAL} from './src/systems/advancement.js';
import {LEVEL_SUM_TOP, ONLINE_LEVEL_CAP} from './src/systems/levelClimb.js';
import {MASTERY_SLOTS} from './src/systems/masterSkills.js';
import {ONLINE_BONUS_POOL} from './src/systems/levelEven.js';
import {PATHS, SPEC_RESET_GOLD} from './src/systems/arcanePaths.js';
import {MARTIAL_PATHS} from './src/systems/martialPaths.js';
import {TRAINING_SKILLS, TEMPLE_TRAINING_SKILLS, trainingMax} from './src/systems/guild/guildServices.js';
import {TRAINING_COOLDOWN_MINUTES, TRAINING_FATIGUE_LOSS, TRAINING_HOURS} from './src/systems/guild/guildServiceActions.js';
import {SKILL_SOFT_CAP, SKILL_HARD_CAP, SOFTCAP_TIERS, SKILL_MILESTONES,
        SPAM_FREE_BURST, SPAM_HALF_LIFE_MS, CHALLENGE_TTL_MS} from './src/systems/skillSoftcap.js';
import {CLASSIC_GAME_START_TIME} from './src/systems/gameDate.js';
import {STAT_KEYS_ORDER, FATIGUE_MULTIPLIER} from './src/systems/statMods.js';
import {assignSkillEquipment, assignSkillItems, assignSkillSpells, RRI_SPELLS} from './src/systems/roleplayRealismItems/rriKits.js';
import {SKILLS} from './src/systems/skills.js';
import {MATERIAL_BITS} from './src/systems/specialAdvantages.js';
import {REALM_EMPIRE_ACCOUNT} from './src/net/realm/realmGoldLaw.js';
import {stacksWith} from './src/systems/inventory.js';

globalThis.location = {search:'?online'};
const emit = console.log.bind(console);
console.log = console.error.bind(console); // engine diagnostics belong on stderr
Math.random = () => 0.5; // fix incidental variation in generated item metadata
// A declared median variate for every optional kit appearance and condition roll.
// Source handles game item fields. Physical IDs are assigned to the frozen copies.
const equipRoll = () => 0.5;
const stackTypes = [];
const copyFields = rows => rows.map(it => {
  const doc = Object.fromEntries(Object.entries(it).filter(([k]) => !['uid','foundAt','createdAt'].includes(k)));
  if (stacksWith(it, {...it})) {
    let index = stackTypes.findIndex(row => stacksWith(row,it));
    if (index < 0) {index=stackTypes.length; stackTypes.push(it);}
    doc.stack_family = index;
  }
  return doc;
});
const commonKit = {}, skillKits = {}, kitRows = [];
const uniqueKits = new Map();
for (const gender of ['male','female']) {
  const actor = {gender,career:{luck:50},items:[],isPlayer:true,_online:true};
  assignSkillEquipment(actor,{rolls:equipRoll});
  commonKit[gender] = copyFields(actor.items);
  for (let metal=0;metal<=1;metal++) for (let chain=0;chain<=1;chain++) {
    const key = [gender,metal,chain].join('/');
    const flags = {luck:50, forbiddenMaterialsFlags:metal*MATERIAL_BITS.iron,
                   weaponArmorShieldsBitfield:chain<<6};
    skillKits[key] = Array.from({length:35},(_,i) => {
      const sample = {isPlayer:true,gender,career:flags,items:[],_online:true};
      assignSkillItems(sample,i,equipRoll);
      const rows = copyFields(sample.items), id = JSON.stringify(rows);
      if (!uniqueKits.has(id)) {uniqueKits.set(id,kitRows.length);kitRows.push(rows);}
      return uniqueKits.get(id);
    });
  }
}
const stockIndices = {get: index => ({index})};
const startingSpells = {};
for (let skill = 0; skill < 35; skill++) {
  const byGroup = {};
  for (const group of ['primary', 'major']) {
    const spells = [];
    assignSkillSpells(spells, skill, group === 'primary', stockIndices);
    byGroup[group] = spells.map(spell => spell.index);
  }
  if (byGroup.primary.length || byGroup.major.length) startingSpells[skill] = byGroup;
}
emit(JSON.stringify({
  skill_multipliers: SKILL_ADVANCEMENT_MULTIPLIER,
  paths: [...PATHS.map(p => ({id:p.id, family:'arcane', skills:p.schools, signature:p.spell.index})),
          ...MARTIAL_PATHS.map(p => ({id:p.id, family:'martial', skills:p.skills}))],
  training_skills: TRAINING_SKILLS, temple_training_skills: TEMPLE_TRAINING_SKILLS,
  limits: {mastery_slots:MASTERY_SLOTS, level_cap:ONLINE_LEVEL_CAP, level_sum_top:LEVEL_SUM_TOP,
           training_cap:trainingMax(), training_minutes:TRAINING_HOURS * 60,
           training_cooldown:TRAINING_COOLDOWN_MINUTES, training_fatigue:TRAINING_FATIGUE_LOSS,
           skill_check_minutes:SKILL_RAISE_CHECK_INTERVAL, attribute_pool:ONLINE_BONUS_POOL,
           reset_gold:SPEC_RESET_GOLD, skill_soft_cap:SKILL_SOFT_CAP, skill_hard_cap:SKILL_HARD_CAP,
           spam_burst:SPAM_FREE_BURST, spam_half_life_ms:SPAM_HALF_LIFE_MS, challenge_ttl_ms:CHALLENGE_TTL_MS},
  softcap_tiers:SOFTCAP_TIERS, skill_milestones:SKILL_MILESTONES,
  creation:{start_minutes:CLASSIC_GAME_START_TIME,attributes:STAT_KEYS_ORDER,
            fatigue_multiplier:FATIGUE_MULTIPLIER,mercantile:SKILLS.Mercantile,
            starting_spells:startingSpells,generated_records:Object.values(RRI_SPELLS),common_kit:commonKit,
            skill_kits:skillKits,kit_rows:kitRows,iron_mask:MATERIAL_BITS.iron,steel_mask:MATERIAL_BITS.steel},
  empire_account: REALM_EMPIRE_ACCOUNT,
}));

