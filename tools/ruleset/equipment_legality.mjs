// Test-only. Read data records from the calling verifier's temporary JSON.
import {readFileSync} from 'node:fs';
import {itemFindings} from './src/systems/item/itemLaw.js';
const items = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const failures = [];
for (const {instance_id, item} of items) {
  const issues = itemFindings(item);
  if (issues.length) failures.push({instance_id, issues});
}
console.log(JSON.stringify({count:items.length, failures}));
