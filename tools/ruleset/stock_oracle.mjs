import {readSpellsStd, spellsByIndexMap} from './src/formats/spellsStd.js';

const bytes = Buffer.from(process.argv[2], 'hex');
console.log(JSON.stringify(Object.fromEntries(spellsByIndexMap(readSpellsStd(bytes)))));
