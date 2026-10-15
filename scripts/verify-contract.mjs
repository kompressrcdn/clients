import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../contracts/', import.meta.url));
const source = JSON.parse(readFileSync(`${root}source.json`, 'utf8'));
const checksum = file => createHash('sha256').update(readFileSync(file)).digest('hex');
assert.equal(checksum(`${root}${source.snapshot}`), source.sha256, 'Contract snapshot checksum differs from source.json.');
const args = process.argv.slice(2);
if (args.length) {
  assert(args.length === 2 && args[0] === '--source', 'Usage: node scripts/verify-contract.mjs [--source /path/to/contract.yaml]');
  assert.equal(checksum(args[1]), source.sha256, 'Supplied contract differs from the pinned snapshot; review and update contracts.');
}
console.log(`Contract snapshot ${source.snapshotId} matches its recorded SHA-256${args.length ? ' and the supplied contract' : ''}.`);
