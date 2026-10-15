import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkPublicFile } from './public-content.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const excluded = new Set(['.git', 'node_modules', 'dist']);
let files = 0;
function walk(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (excluded.has(entry.name) || entry.name.startsWith('.local-sdk-install-')) continue;
    const path = join(directory, entry.name);
    assert(!entry.isSymbolicLink(), 'Public source must not link outside the checkout.');
    if (entry.isDirectory()) walk(path);
    else { checkPublicFile(path, root); files++; }
  }
}
walk(root);
const source = JSON.parse(readFileSync(join(root, 'contracts/source.json'), 'utf8'));
assert.deepEqual(Object.keys(source).sort(), ['contractVersion', 'sha256', 'snapshot', 'snapshotId']);
console.log(`Public-content checks passed for ${files} source files.`);
