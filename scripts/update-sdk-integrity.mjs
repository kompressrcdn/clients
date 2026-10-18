import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const directory = mkdtempSync(join(tmpdir(), 'kompressr-sdk-integrity-'));
try {
  // npm 10 includes lifecycle output in --json stdout. Build separately so
  // packing returns only metadata while still verifying fresh build output.
  execFileSync('npm', ['run', 'build'], { cwd: join(root, 'sdk-js'), stdio: 'inherit' });
  const [packed] = JSON.parse(execFileSync('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', directory], { cwd: join(root, 'sdk-js'), encoding: 'utf8' }));
  const manifest = JSON.parse(readFileSync(join(root, 'mcp-server/package.json'), 'utf8'));
  assert.equal(packed.name, '@kompressr/sdk');
  assert.equal(packed.version, manifest.dependencies['@kompressr/sdk']);
  const target = join(root, 'mcp-server/package-lock.json');
  const lock = JSON.parse(readFileSync(target, 'utf8'));
  const entry = lock.packages['node_modules/@kompressr/sdk'];
  assert.equal(entry.version, packed.version);
  assert.equal(entry.resolved, `https://registry.npmjs.org/@kompressr/sdk/-/sdk-${packed.version}.tgz`);
  entry.integrity = packed.integrity;
  writeFileSync(target, `${JSON.stringify(lock, null, 2)}\n`);
  console.log(`Recorded registry SDK ${packed.version} integrity: ${packed.integrity}`);
} finally {
  rmSync(directory, { recursive: true, force: true });
}
