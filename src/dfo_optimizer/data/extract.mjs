// Runs only beside the nine verified pinned source blobs materialized by ruleset.py.
import * as custom from "./src/systems/customClass.js";
import * as special from "./src/systems/specialAdvantages.js";
import { SKILL_NAMES, MAGIC_SKILLS } from "./src/systems/skills.js";
import { RACE_TEMPLATES } from "./src/systems/races.js";

const statKeys = ["strength", "intelligence", "willpower", "agility", "endurance", "personality", "speed", "luck"];
const stats = Object.fromEntries(statKeys.map(key => [key, custom.STAT_DEFAULT]));
const base = custom.buildCustomCareer({name: "Oracle", hp: custom.HP_DEFAULT, skills: [], stats});
const fields = Object.keys(base).filter(key => !statKeys.includes(key) &&
  typeof base[key] === "number" && !["advancementMultiplier", "hitPointsPerLevel"].includes(key));
const defaults = Object.fromEntries(fields.map(key => [key, base[key]]));

// Every pinned career write is an OR, masked assignment, or whole-field assignment.
// Applying it to the extreme bit patterns recovers (old & ~clear) | set.
function careerWrites(pick) {
  const zeros = Object.fromEntries(fields.map(key => [key, 0]));
  const ones = Object.fromEntries(fields.map(key => [key, 0xffffffff]));
  special.parseCareerData(zeros, [pick]);
  special.parseCareerData(ones, [pick]);
  const changes = {};
  for (const key of fields) {
    const clear = (~ones[key]) >>> 0;
    const set = zeros[key] >>> 0;
    if (clear || set) changes[key] = {clear, set};
  }
  return changes;
}

const traits = [];
for (const [side, keys] of [["advantage", special.ADVANTAGE_KEYS], ["disadvantage", special.DISADVANTAGE_KEYS]]) {
  for (const primary of keys) {
    for (const secondary of special.secondaryListFor(primary) ?? [""]) {
      const pick = {primary, secondary};
      traits.push({id: traits.length, side, ...pick, cost: special.advDisAdjustment(primary, secondary),
        only_one: special.ONLY_ONE_KEYS.includes(primary), writes: careerWrites(pick)});
    }
  }
}
const conflicts = (left, right) => special.cannotAdd(left, [right]) ||
  (left.only_one && right.primary === left.primary && right.side === left.side);
const races = RACE_TEMPLATES.map(race => ({
  id: race.id, name: race.name, key: race.key, flags: Object.fromEntries(
    ["resistanceFlags","immunityFlags","criticalWeaknessFlags","lowToleranceFlags","specialAbilities"]
      .map(key => [key, race[key]]))
}));

console.log(JSON.stringify({
  traits: traits.map(row => ({...row, conflicts: traits.filter(other => conflicts(row, other)).map(other => other.id)})),
  skills: SKILL_NAMES.map((name, id) => ({id, name, magic: MAGIC_SKILLS.includes(id)})),
  races, career_defaults: defaults, limits: {
    hp_min: custom.HP_MIN, hp_max: custom.HP_MAX, stat_min: custom.FREE_EDIT_MIN, stat_max: custom.FREE_EDIT_MAX,
    stat_total: custom.STAT_DEFAULT * statKeys.length, max_picks: special.MAX_ITEMS, difficulty_min: custom.DIFFICULTY_MIN,
    difficulty_max: custom.DIFFICULTY_MAX, rep_max: custom.REP_MAX
  }
}));
