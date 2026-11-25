import { FIRM_ADJ, FIRM_NODES, START_KEYS } from './src/net/firmament/firmamentTree.js';
import { CRAFT_RANKS_PER_POINT, FIRM_RENOWN_MAX, STARS_PER_RENOWN } from './src/net/firmament/firmamentLaw.js';
import { ARTIFACTS, OGHMA_BONUS_POOL } from './src/systems/artifactEffects.js';

// Only catalog data passes the offline boundary. Account entitlements are distinct observations.
process.stdout.write(JSON.stringify({
  oghma: {subtype: ARTIFACTS.OghmaInfinium, pool: OGHMA_BONUS_POOL},
  starts: [...START_KEYS].sort(),
  renown_max: FIRM_RENOWN_MAX,
  stars_per_renown: STARS_PER_RENOWN,
  craft_ranks_per_point: CRAFT_RANKS_PER_POINT,
  nodes: Object.fromEntries([...FIRM_NODES].map(([key,node]) =>
    [key, {kind: node.kind, ring: node.ring, stats: node.stats, adjacent: FIRM_ADJ.get(key)}])),
}));
