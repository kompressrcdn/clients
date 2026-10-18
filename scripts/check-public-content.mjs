import assert from 'node:assert/strict';
import { readdirSync, readFileSync, lstatSync } from 'node:fs';
import { join, relative } from 'node:path';
import { execFileSync } from 'node:child_process';
import { isGeneratedDirectory } from './source-paths.mjs';
import { fileURLToPath } from 'node:url';
import { checkPublicFile } from './public-content.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const checked = new Set();
let files = 0;
function walk(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.name === '.git' || isGeneratedDirectory(relative(root, path))) continue;
    assert(!entry.isSymbolicLink(), 'Public source must not link outside the checkout.');
    if (entry.isDirectory()) walk(path);
    else { checkPublicFile(path, root); checked.add(relative(root, path)); files++; }
  }
}
walk(root);
// A generated-path exclusion must never hide a file already tracked by Git.
const tracked = execFileSync('git', ['ls-files', '-z'], { cwd: root, encoding: 'utf8' }).split('\0').filter(Boolean);
for (const path of tracked) {
  if (!checked.has(path)) {
    assert(!lstatSync(join(root, path)).isSymbolicLink(), 'Public source must not link outside the checkout.');
    checkPublicFile(join(root, path), root); files++;
  }
}
const source = JSON.parse(readFileSync(join(root, 'contracts/source.json'), 'utf8'));
assert.deepEqual(Object.keys(source).sort(), ['contractVersion', 'sha256', 'snapshot', 'snapshotId']);
console.log(`Public-content checks passed for ${files} source files.`);
