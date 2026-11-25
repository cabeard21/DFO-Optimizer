import { BsaFile } from "./src/formats/bsaFile.js";
import { ClassFile } from "./src/formats/classFile.js";
import { VANILLA_ENEMY_BASICS } from "./src/characters/enemy/enemyBasics.js";

// Synthetic classic-format bytes allow CI to exercise the upstream readers.
const bytes = new Uint8Array(96);
const view = new DataView(bytes.buffer);
view.setInt16(0, 1, true);
view.setUint16(2, 0x0100, true);
bytes.set([2, 4, 8, 16], 4);
view.setUint16(4 + 62, 63, true);
bytes.set(new TextEncoder().encode("ENEMY000.CFG"), 78);
view.setInt32(92, 74, true);
const archive = new BsaFile(bytes);
const career = new ClassFile();
career.load(archive.getRecordBytes(archive.getRecordIndex("ENEMY000.CFG")));
const c = career.career;
const rat = VANILLA_ENEMY_BASICS[0];
process.stdout.write(JSON.stringify({
  career: {willpower:c.willpower, resistant:c.resistanceFlags, immune:c.immunityFlags,
           low_tolerance:c.lowToleranceFlags, critical_weakness:c.criticalWeaknessFlags},
  rat: {min_hp:rat.minHealth,max_hp:rat.maxHealth,min_damage:rat.minDamage,max_damage:rat.maxDamage,level:rat.level}
}));
