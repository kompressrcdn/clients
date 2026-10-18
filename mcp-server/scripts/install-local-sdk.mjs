import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, writeFileSync, mkdirSync, renameSync, rmSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const sdk = resolve(process.argv[2] ?? fileURLToPath(new URL('../../sdk-js', import.meta.url)));
const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'));
const source = JSON.parse(readFileSync(join(sdk, 'package.json'), 'utf8'));
if (source.name !== '@kompressr/sdk' || source.version !== manifest.dependencies['@kompressr/sdk']) {
  throw new Error('The local SDK name/version must match the MCP dependency.');
}
// An isolated temporary lock substitutes only the unpublished SDK artifact.
// npm ci preserves every other locked version and never edits checked-in metadata.
const directory = mkdtempSync(join(root, '.local-sdk-install-'));
try {
  // Keep lifecycle output out of npm 10's JSON metadata.
  execFileSync('npm', ['run', 'build'], { cwd: sdk, stdio: 'inherit' });
  const output = execFileSync('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', directory], { cwd: sdk, encoding: 'utf8' });
  const [packed] = JSON.parse(output);
  const artifact = `file:${join(directory, packed.filename)}`;
  manifest.dependencies['@kompressr/sdk'] = artifact;
  lock.packages[''].dependencies['@kompressr/sdk'] = artifact;
  lock.packages['node_modules/@kompressr/sdk'].resolved = artifact;
  lock.packages['node_modules/@kompressr/sdk'].integrity = packed.integrity;
  const install = join(directory, 'consumer'); mkdirSync(install);
  writeFileSync(join(install, 'package.json'), JSON.stringify(manifest));
  writeFileSync(join(install, 'package-lock.json'), JSON.stringify(lock));
  execFileSync('npm', ['ci', '--ignore-scripts', '--no-audit', '--no-fund'], { cwd: install, stdio: 'inherit' });
  const current = join(root, 'node_modules'), previous = join(directory, 'previous-node_modules');
  if (existsSync(current)) renameSync(current, previous);
  try { renameSync(join(install, 'node_modules'), current); }
  catch (error) { if (existsSync(previous)) renameSync(previous, current); throw error; }
  console.log(`Installed local SDK ${source.version} with locked MCP dependencies; package metadata and lockfile are unchanged.`);
} finally {
  rmSync(directory, { recursive: true, force: true });
}
