// The Python launcher stages only checked Git blobs, then runs this test driver.
import * as maker from "./src/systems/spell/spellMaker.js";
import * as power from "./src/systems/spell/spellPower.js";
import * as speed from "./src/systems/castSpeed.js";
import * as animation from "./src/combat/fpsSpellCasting.js";
import { applySpell } from "./src/systems/effects.js";
import { EFFECT_FLAGS, savingChance, elementFlag } from "./src/systems/spellcast.js";
import { SKILLS } from "./src/systems/skills.js";
import { equipItem } from "./src/systems/equip.js";
import { lootCastCost } from "./src/systems/loot/lootPowers.js";
import { chapterPriced } from "./src/net/npcChapterLaw.js";
import { createPlayerMagic } from "./src/scenes/hostMagic.js";

const sourceSha = "a3eb1605ea1dc391b691fe314377458a7e63e483";
globalThis.location = {search: "?online"};
const destruction = SKILLS.Destruction;
const zeroes = [0, 0, 0, 0, 0];
const elementNames = ["fire", "frost", "poison", "shock", "magic"];
const baseline = {
  caster: {level: 12, speed: 50, destruction_live: 55, destruction_trained: 55,
    destruction_mastered: false, current_sp: 450, max_sp: 500, gold: 6000, has_spellbook: true},
  target: {id: "synthetic_foe", hp: 55, willpower: 50},
  spell: {effect_id: "4,0", range_type: 2, element: 0, base_low: 7, base_high: 9,
    plus_low: 1, plus_high: 2, per_level: 4},
};

function makeRequest({caster, target, spell, price_factor = 1}) {
  return {schema_version: 1, caster: {...baseline.caster, ...caster},
    target: {...baseline.target, ...target}, spell: {...baseline.spell, ...spell}, price_factor};
}

function spellSlot(s) {
  return {type: 4, subType: 0, settings: {magnitudeBaseLow: s.base_low, magnitudeBaseHigh: s.base_high,
    magnitudeLevelBase: s.plus_low, magnitudeLevelHigh: s.plus_high, magnitudePerLevel: s.per_level}};
}

function gameSpell(s) {
  return maker.buildCustomSpell({slots: [spellSlot(s)], name: "Audit", index: -45001,
    rangeType: s.range_type, element: s.element});
}

function gamePlayer(c) {
  const entity = {
    isPlayer: true, _online: true, level: c.level, health: 100, maxHealth: 100,
    stats: {speed: c.speed, willpower: 50}, skills: Array(35).fill(0),
    skillUses: Array(35).fill(0), skillOverrides: {[destruction]: c.destruction_live},
    masteredSkills: c.destruction_mastered ? [destruction] : [], career: {},
    activeEffects: [], items: c.has_spellbook ? [{group: "MiscItems", templateIndex: maker.SPELLBOOK_TEMPLATE_INDEX}] : [],
    magicka: c.current_sp, maxMagicka: c.max_sp, goldPieces: c.gold,
  };
  entity.skills[destruction] = c.destruction_trained;
  for (let remaining = c.focus_pct ?? 0; remaining > 0; remaining -= 6) {
    const ring = {group: "Jewellery", templateIndex: 135, name: "Fixture ring", rarity: "rare",
      affixes: [{id: "focus", value: Math.min(6, remaining)}], currentCondition: 10, maxCondition: 10};
    entity.items.push(ring);
    equipItem(entity, ring);
  }
  return entity;
}

function gameTarget(t) {
  return {isPlayer: false, health: t.hp, stats: {willpower: t.willpower}, career: {
    resistanceFlags: t.resistant ?? 0, immunityFlags: t.immune ?? 0,
    lowToleranceFlags: t.low_tolerance ?? 0, criticalWeaknessFlags: t.critical_weakness ?? 0,
  }, _mods: {resist: Object.fromEntries(elementNames.map((name, i) => [name, (t.resist_mods ?? zeroes)[i]]))},
  activeEffects: (t.elemental_resists ?? zeroes).flatMap((chance, element) =>
    chance ? [{kind: "elementalResistance", chance, element, roundsRemaining: 2}] : [])};
}

function sequence(draws) {
  let index = 0;
  return () => {
    if (index === draws.length) throw new Error("Unexpected additional source RNG draw");
    return draws[index++];
  };
}

function distribution(request, spell, player) {
  const {target, spell: s} = request;
  const active = (target.elemental_resists ?? zeroes)[s.element] > 0;
  const baseCount = s.base_high - s.base_low + 1;
  const plusCount = s.plus_high - s.plus_low + 1;
  let damage = 0, healthLoss = 0, lethal = 0, trials = 0;
  for (let base = 0; base < baseCount; base++) {
    for (let plus = 0; plus < plusCount; plus++) {
      for (let resist = 0; resist < (active ? 100 : 1); resist++) {
        for (let save = 0; save < 100; save++) {
          const draws = [(base + 0.5) / baseCount, (plus + 0.5) / plusCount];
          if (active) draws.push((resist + 0.5) / 100);
          draws.push((save + 0.5) / 100);
          const foe = gameTarget(target);
          let hurt = 0;
          applySpell(spell, player.level, foe, {hurt: n => { hurt += n; }},
            sequence(draws), {entity: player});
          damage += hurt;
          healthLoss += Math.min(target.hp, hurt);
          lethal += Number(hurt >= target.hp);
          trials++;
        }
      }
    }
  }
  return {damage, healthLoss, lethal, trials};
}

function evaluate(id, definition) {
  const request = makeRequest(definition);
  const c = request.caster;
  // The named source hooks separate the frozen upstream aggregate from item eligibility.
  power.registerSpellPowerMod("test-input", () => c.power_pct ?? 0);
  power.registerSpellPierceMod("test-input", () => c.pierce ?? 0);
  speed.registerCastSpeedMod("test-input", () => c.cast_speed_pct ?? 0);
  const player = gamePlayer(c), foe = gameTarget(request.target), spell = gameSpell(request.spell);
  if (lootCastCost(player, 100, spell) !== 100 - (c.focus_pct ?? 0))
    throw new Error("The source did not equip the requested Focus total");
  const {gold, sp} = maker.spellMakerCost(spell, player);
  const quote = chapterPriced(gold, request.price_factor);
  const chance = savingChance(spell.element, elementFlag(spell.element), foe, 0, power.spellPierce(player, foe));
  const {damage, healthLoss, lethal, trials} = distribution(request, spell, player);
  const rate = speed.castRate(player);
  const clock = new animation.SpellCastAnim();
  if (!clock.playOneShot(spell.element, null, {rate})) throw new Error("Spell animation refused");
  const recovery = clock._recover; // actual scheduler delay, measured before the first tick
  const host = hostFor(player, [{entity: foe, ai: {feet: [0, 0, 1], height: 1.8}}]);
  const affordable = host.readySpell(spell);
  const before = player.magicka;
  const cast = host.castInput([0, .9, 0], [0, 0, 1]);
  if (cast !== affordable) throw new Error("Ordinary fixture failed its confirmed-hit cast");
  const spent = before - player.magicka;
  const expected = {
    gold, cost_sp: sp, purchase_gold: quote, affordable, actual_sp_charged: spent,
    expected_damage: damage / trials, expected_health_loss: healthLoss / trials,
    kill_probability: lethal / trials, damage_per_sp: spent ? healthLoss / trials / spent : null,
    damage_per_sp_if_cast: healthLoss / trials / sp,
    dps: healthLoss / trials / recovery, cast_rate: rate, potency: power.spellPowerMult(player, foe),
    release_seconds: animation.castReleaseS(rate), recovery_seconds: recovery,
    immune: chance.immune, save_chance: chance.chance,
  };
  return {id, request, expected, trials, editor_cost: maker.editedEffectCost(spellSlot(request.spell), player)};
}

const point = {base_low: 2, base_high: 2, plus_low: 1, plus_high: 1, per_level: 20};
const expensive = {range_type: 3, element: 1, base_low: 97, base_high: 100,
  plus_low: 95, plus_high: 97, per_level: 1};
const definitions = {
  ordinary: {},
  touch_floor: {caster: {level: 1, destruction_live: 100}, spell: {...point, range_type: 1, element: 4}},
  online_99: {caster: {destruction_live: 99}, spell: expensive},
  online_100: {caster: {destruction_live: 100}, spell: expensive},
  online_101: {caster: {destruction_live: 101}, spell: expensive},
  scaled_roll: {caster: {level: 7, speed: 80}, spell: {per_level: 8}},
  mastery_step: {caster: {level: 8, destruction_trained: 125, destruction_live: 116,
    destruction_mastered: true, power_pct: 9}, spell: {per_level: 8, element: 2}},
  mastery_cap: {caster: {level: 45, destruction_trained: 200, destruction_live: 155,
    destruction_mastered: true, speed: 100, cast_speed_pct: 20}, spell: {range_type: 4}, target: {hp: 12}},
  unmastered: {caster: {destruction_trained: 190, destruction_live: 103}},
  immune_before_pierce: {caster: {pierce: 15}, target: {immune: EFFECT_FLAGS.Fire}},
  tolerance_order: {target: {immune: EFFECT_FLAGS.Shock, resistant: EFFECT_FLAGS.Shock},
    spell: {range_type: 4, element: 3}},
  weak: {target: {willpower: 1, critical_weakness: EFFECT_FLAGS.Poison},
    caster: {pierce: 15}, spell: {element: 2}},
  low_tolerance: {target: {low_tolerance: EFFECT_FLAGS.Magic, resist_mods: [0, 0, 0, 0, 13]},
    caster: {pierce: 4}, spell: {element: 4}},
  absolute_resist: {spell: point, target: {elemental_resists: [37, 0, 0, 0, 0]}},
  focus_floor: {caster: {focus_pct: 12, destruction_live: 140}, spell: point, price_factor: 0.85},
  charged_range: {caster: {focus_pct: 12}, spell: {range_type: 4}, price_factor: 1.15},
  rate_ceiling: {caster: {speed: 100, cast_speed_pct: 100}, spell: point},
  rate_floor: {caster: {speed: 0, cast_speed_pct: -60, power_pct: -80}, spell: point},
  insufficient_sp: {caster: {current_sp: 4}, spell: point},
};
const casts = Object.entries(definitions).map(([id, row]) => evaluate(id, row));
speed.registerCastSpeedMod("test-input", null);
power.registerSpellPowerMod("test-input", null);
power.registerSpellPierceMod("test-input", null);

function hostFor(me, foes = []) {
  return createPlayerMagic({playerEntity: me, playerSinks: {}, foeSinks: () => ({}),
    foes: () => foes, collider: {raycast: () => Infinity}, say() {}, surfacePlayer() {},
    audio: {}, renderer: {}, absorbCtx: () => ({inside: true, day: false}), rolls: () => .99,
    // Stop after the successful cast click and SP payment, when the game queues release.
    startCastAnim: () => true});
}

function hostCase(id, {free = false, touch = false, low = false, editSkill = false, drain = false}) {
  const request = makeRequest({spell: {range_type: touch ? 1 : 2}});
  const me = gamePlayer(request.caster), spell = gameSpell(request.spell);
  const host = hostFor(me);
  if (low) me.magicka = 1;
  const ready = host.readySpell(spell, {free});
  const ready_cost = host.readiedCost();
  if (editSkill) me.skillOverrides[destruction] = 100;
  if (drain) me.magicka = 2;
  const before = me.magicka;
  const cast = host.castInput([0, .9, 0], [0, 0, 1]);
  return {id, ready, ready_cost, cast, charged: before - me.magicka,
    before_cast_sp: before, after_cast_sp: me.magicka};
}

function hostImpact() {
  const request = makeRequest({target: {hp: 3}});
  const player = gamePlayer(request.caster), entity = gameTarget(request.target);
  const host = hostFor(player), spell = gameSpell(request.spell);
  let hurt = 0, taken = null;
  power.registerSpellLandedListener("test-observer", info => { taken = info.took; });
  const hit = host.applySpellToFoe(spell, player.level, {entity}, {entity: player, cast: {cost: maker.spellMakerCost(spell, player).sp}},
    undefined, {hurt: n => { hurt += n; entity.health = Math.max(0, entity.health - n); }});
  power.registerSpellLandedListener("test-observer", null);
  return {initial_hp: request.target.hp, hurt, taken, landed_damage: hit.damage};
}

const oracle = {
  source_sha: sourceSha, mode: "online_snapshot", casts,
  host_impact: hostImpact(),
  host: Object.entries({normal: {}, changed_skill: {editSkill: true}, free: {free: true},
    drained_after_ready: {drain: true}, insufficient: {low: true}, touch_miss: {touch: true}})
    .map(([id, fields]) => hostCase(id, fields)),
  sources: ["src/systems/spell/spellMaker.js#buildCustomSpell,spellMakerCost",
    "src/systems/spellcost.js#calculateCastCost", "src/systems/effects.js#applySpell",
    "src/systems/spell/spellPower.js#spellPowerMult", "src/systems/spellcast.js#savingChance",
    "src/combat/fpsSpellCasting.js#SpellCastAnim", "src/scenes/hostMagic.js#createPlayerMagic",
    "src/net/npcChapterLaw.js#chapterPriced"],
  stubs: ["Online page query, own player, ordinary stationary NPC and no other encounter conditions.",
    "RNG exhausts inclusive magnitude and save rolls. Expected health loss clips one hit to supplied target HP.",
    "Source skill override provides observed live school value. Earned mastery reads permanent skills separately.",
    "Named source hooks receive explicit aggregate power, penetration and speed. Focus uses two equipped fixture rings.",
    "Cast host uses an empty scene, inert rendering/audio and a parked animation release to observe magicka payment."],
};
console.log(JSON.stringify(oracle));
