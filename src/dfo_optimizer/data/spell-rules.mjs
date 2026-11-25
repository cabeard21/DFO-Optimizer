// Mechanical facts from the authored adapter's authenticated upstream dependencies.
import { effectByKey } from "./src/systems/spell/spellEffects.js";
import { updateAllowedButtons, SPINNER_RANGES } from "./src/systems/spell/spellMaker.js";
import { EFFECT_FLAGS } from "./src/systems/spellcast.js";
import { EFFECT_COST_TABLE, TARGET_COST_MULT, CAST_COST_FLOOR, SPELL_COST_SKILL_REFERENCE } from "./src/systems/spellcost.js";
import { FOCUS_CAP, SPELL_CUT_MOST } from "./src/systems/loot/lootPowers.js";
import { CAST_SPEED_PIVOT, CAST_SPEED_SPAN, CAST_RATE_MIN, CAST_RATE_MAX } from "./src/systems/castSpeed.js";
import { RELEASE_FRAME, CAST_FRAME_PERIOD, CAST_RECOVER_S } from "./src/combat/fpsSpellCasting.js";
import { SCHOOL_POTENCY_PER_POINT, SPELL_POWER_FLOOR } from "./src/systems/spell/spellPower.js";

const mask = updateAllowedButtons([{type: 4, subType: 0}]);
const spinners = Object.fromEntries(Object.entries(SPINNER_RANGES).filter(([k]) => k.startsWith("magnitude")));
console.log(JSON.stringify({
  source_sha: "a3eb1605ea1dc391b691fe314377458a7e63e483", mode: "online_snapshot",
  effect: {key: effectByKey("4,0").key, cost: EFFECT_COST_TABLE["4,0"], target_mask: mask.targets,
    element_mask: mask.elements, spinners, flags: EFFECT_FLAGS},
  cost: {floor: CAST_COST_FLOOR, overcap_reference: SPELL_COST_SKILL_REFERENCE,
    target_multipliers: TARGET_COST_MULT, focus_cap: FOCUS_CAP, loot_cut_cap: SPELL_CUT_MOST},
  timing: {pivot: CAST_SPEED_PIVOT, span: CAST_SPEED_SPAN, minimum: CAST_RATE_MIN,
    maximum: CAST_RATE_MAX, release_frame: RELEASE_FRAME,
    frame_period_seconds: CAST_FRAME_PERIOD, recovery_seconds: CAST_RECOVER_S},
  power: {school_potency_per_point: SCHOOL_POTENCY_PER_POINT, floor: SPELL_POWER_FLOOR},
}));
