// This driver runs in an isolated directory containing authenticated upstream Git objects.
import { ChargenFlow } from "./src/ui/chargen.js";
import * as custom from "./src/systems/customClass.js";
import { spellPointMultiplier } from "./src/systems/chargen.js";

const pick = (primary, secondary) => secondary ? {primary, secondary} : {primary};
const material = name => pick("forbiddenMaterial", name);
const stats = Object.fromEntries(["strength","intelligence","willpower","agility","endurance",
  "personality","speed","luck"].map(key => [key,50]));
const baseline = {
  format: custom.CLASS_FILE_FORMAT, version: custom.CLASS_FILE_VERSION,
  name: "Oracle fixture", hitPointsPerLevel: 8,
  skills: {primary: [22,23,24], major: [25,26,27], minor: [0,1,2,3,4,5]}, attributes: stats,
  advantages: [], disadvantages: [], reputations: {},
};
const magic = pick("increasedMagery", "intInSpellPoints3");
const healing = env => pick("rapidHealing", env);
const bothOrders = (primary, a, b) => [[pick(primary,a),pick(primary,b)],[pick(primary,b),pick(primary,a)]];
const [absorbA, absorbB] = bothOrders("spellAbsorption","inLight","inDarkness");
const [regenA, regenB] = bothOrders("regenerateHealth","inDarkness","whileImmersed");
const inputs = {
  baseline: {},
  no_magic_school: {skills: {primary:[0,1,2],major:[3,4,5],minor:[6,7,8,9,10,11]}},
  ...Object.fromEntries(["intInSpellPoints", "intInSpellPoints15", "intInSpellPoints175", "intInSpellPoints2"]
    .map(key => [key, {advantages:[pick("increasedMagery",key)]}])),
  material_floor: {hitPointsPerLevel: 30, advantages: [magic],
    disadvantages: ["steel","elven","dwarven","mithril","silver","adamantium","iron"].map(material)},
  order_light_dark: {advantages: [healing("inLight"),healing("inDarkness")]},
  order_dark_light: {advantages: [healing("inDarkness"),healing("inLight")]},
  absorption_light_dark: {advantages: absorbA}, absorption_dark_light: {advantages: absorbB},
  regeneration_dark_immersed: {advantages: regenA}, regeneration_immersed_dark: {advantages: regenB},
  conflict_skip: {advantages: [pick("immunity","toFire")], disadvantages: [pick("lowTolerance","toFire"),pick("lowTolerance","toFrost")]},
  seven_per_window: {disadvantages: ["iron","steel","silver","elven","ebony","dwarven","daedric","orcish"].map(material)},
  magery_unique: {advantages: [magic, pick("increasedMagery","intInSpellPoints2")]},
  draft_name: {name: " \u0001"}, long_name: {name: " X".repeat(20)},
  missing_skill: {skills: {...baseline.skills, primary: [null,23,24]}},
  duplicate_skill: {skills: {...baseline.skills, primary: [22,23,23]}},
  display_names: {skills: {primary: ["destruction","Hand-to-Hand","Illusion"],major:[25,26,27],minor:[0,1,2,3,4,5]}},
  unbalanced_pool: {attributes: {...stats, speed:51}}, rep_unbalanced: {reputations: {peasants:2}},
  illegal_below_floor: {disadvantages:[pick("criticalWeakness","toFire")]},
  illegal_above_ceiling: {hitPointsPerLevel:30, advantages:[pick("spellAbsorption","general"),magic]},
  unknown_pick: {advantages:[pick("fictional")]}, missing_tag: {format: "wrong"},
};
function evaluate(label, edits) {
  const document = {...baseline, ...edits};
  const flow = new ChargenFlow([], () => 0);
  flow.state = "class";
  flow.classListIndex = 0;
  flow.useClass();
  const parsed = custom.parseCustomClassDoc(document);
  const imported = flow.customImport(document);
  if (!imported.ok) {
    return {label,document,parsed,imported,expected_document:null,create_legal:false,
      difficulty:null,advancement:null,career:null};
  }
  const expected_document = custom.customClassDoc(flow.custom);
  const difficulty = flow.customDifficulty();
  flow.customExit();
  const career = flow.customCareer ?? null;
  return {label,document,parsed,imported,expected_document,create_legal:Boolean(flow.customCareer),
    difficulty,advancement:custom.advancementMultiplier(difficulty),career,
    magicka_multiplier: career ? spellPointMultiplier(career.abilityFlagsAndSpellPointsBitfield) : null,
    starting_spell_set_index: career ? custom.customSpellSetIndex(career) : null};
}
const numeric = [];
for (const hp of [4,7,8,9,30]) {
  for (const [advantage, disadvantage] of [[0,0],[10,-44],[20,-10],[8,-9],[32,-7]]) {
    const difficulty = custom.difficultyPoints(hp,advantage,disadvantage);
    numeric.push({hp,advantage,disadvantage,difficulty,advancement:custom.advancementMultiplier(difficulty)});
  }
}
console.log(JSON.stringify({
  source_sha:"a3eb1605ea1dc391b691fe314377458a7e63e483",
  source: ["src/ui/chargen.js#ChargenFlow.customImport","src/ui/chargen.js#ChargenFlow.customExit",
    "src/systems/customClass.js#customClassDoc","src/systems/customClass.js#difficultyPoints"],
  mode:"online_snapshot", stubs:["Empty standard-career list and deterministic zero RNG. Biography, standard-class affinity and random starting rolls are outside these vectors."],
  cases:Object.entries(inputs).map(([label,edit]) => evaluate(label,edit)), numeric
}));
