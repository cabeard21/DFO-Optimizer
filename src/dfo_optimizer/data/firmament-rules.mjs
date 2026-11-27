import { FIRM_ADJ, FIRM_EDGES, FIRM_NODES, START_KEYS } from './src/net/firmament/firmamentTree.js';
import {
  CRAFT_RANK_MAX, CRAFT_RANKS_PER_POINT, FIRM_RENOWN_MAX, STARS_PER_RENOWN,
  castCostPct, pointsLeft, statDef, treeFault, treeStats,
} from './src/net/firmament/firmamentLaw.js';
import { RENOWN_MP_PER_LEVEL } from './src/net/renown.js';

const subjects = process.argv[2] ? JSON.parse(process.argv[2]) : null;
if (subjects) {
  const { defineLiveMaxMagicka } = await import('./src/systems/chargen.js');
  const { computeEntityMods } = await import('./src/systems/entityMods.js');
  const { setRenownLayer } = await import('./src/systems/renownLayer.js');
  const { SKILLS, skillValue } = await import('./src/systems/skills.js');
  const { castRate } = await import('./src/systems/castSpeed.js');
  const { setFirmamentTree, setFirmamentOnline } = await import('./src/systems/firmamentLive.js');
  const { firmamentLayer, firmamentCastCost, firmamentSpellPierce, firmamentSpellPower } =
    await import('./src/systems/firmamentPowers.js');
  globalThis.location = {search: '?online'};
  setFirmamentOnline(true);
  process.stdout.write(JSON.stringify(subjects.map(({tree, stars, craft, speed, intelligence, destruction}) => {
    const stats = treeStats(tree);
    const player = {
      isPlayer: true, level: 10, stats: {intelligence, speed}, skills: Array(35).fill(destruction),
      career: {abilityFlagsAndSpellPointsBitfield: 0}, items: [], activeEffects: [], maxMagicka: 0,
    };
    defineLiveMaxMagicka(player);
    setRenownLayer(player, Math.floor(stars / STARS_PER_RENOWN) + 1);
    setFirmamentTree(tree);
    computeEntityMods(player);
    firmamentLayer(player);
    return { fault: treeFault(tree, stars, craft), left: pointsLeft(tree.keys, stars, craft),
      stats, destructionCost: castCostPct(stats, ['Destruction']), magicka: player.maxMagicka,
      speedRate: castRate(player), skill: skillValue(player, SKILLS.Destruction),
      spellPower: firmamentSpellPower(player), spellPierce: firmamentSpellPierce(player),
      castCost: Math.round(firmamentCastCost(player, 35, {effects: [{type: 4, subType: 0}]})) };
  })));
} else {
  const channels = new Set();
  const nodes = Object.fromEntries([...FIRM_NODES].map(([key, node]) => {
    for (const channel of Object.keys(node.stats)) channels.add(channel);
    const {kind, ring, name, text, stats, x, y} = node;
    return [key, {kind, ring, name, ...(text ? {description: text} : {}), stats,
      x, y, adjacent: FIRM_ADJ.get(key)}];
  }));
  process.stdout.write(JSON.stringify({
    stars_max: (FIRM_RENOWN_MAX - 1) * STARS_PER_RENOWN,
    craft_max: 10 * CRAFT_RANK_MAX / CRAFT_RANKS_PER_POINT,
    stars_per_renown: STARS_PER_RENOWN, renown_sp: RENOWN_MP_PER_LEVEL,
    starts: [...START_KEYS].sort(), edges: FIRM_EDGES, nodes,
    channels: Object.fromEntries([...channels].sort().map(key => {
      const {kind, min, max} = statDef(key);
      return [key, {kind, min, max}];
    })),
  }));
}
