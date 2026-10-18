import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkPublicContent, checkPublicPath } from './public-content.mjs';

const archives = process.argv.slice(2);
assert(archives.length > 0, 'Usage: node scripts/check-distribution.mjs ARCHIVE [ARCHIVE ...]');
const reader = fileURLToPath(new URL('./read-distribution.py', import.meta.url));
for (const archive of archives) {
  const files = JSON.parse(execFileSync(process.env.KOMPRESSR_PYTHON || 'python3', [reader, archive], {
    encoding: 'utf8', maxBuffer: 128 * 1024 * 1024,
  }));
  for (const file of files) {
    const label = `${basename(archive)}:${file.path}`;
    checkPublicPath(file.path);
    const bytes = Buffer.from(file.data, 'base64');
    checkPublicContent(bytes.toString('utf8'), label);
    // Managed binaries may encode embedded strings as UTF-16 instead of UTF-8.
    if (/\.(?:dll|pdb)$/i.test(file.path)) checkPublicContent(bytes.toString('utf16le'), label);
  }
  console.log(`${basename(archive)}: public-content checks passed for ${files.length} distribution members.`);
}
