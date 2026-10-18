import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.KOMPRESSR_PYTHON || 'python3';
const packages = {
  node: { tools: [['npm', '--version']], command: [process.execPath, 'scripts/verify.mjs'], directory: '.' },
  python: { tools: [[python, '--version']], command: [python, 'scripts/verify.py'], directory: 'sdk-python', output: 'dist', pattern: /\.(whl|tar\.gz)$/ },
  go: { tools: [['go', 'version']], command: ['go', 'run', './scripts/verify.go'], directory: 'sdk-go', pattern: /\.zip$/ },
  java: { tools: [['mvn', '--version']], command: ['sh', 'scripts/verify.sh'], directory: 'sdk-java', output: 'target', pattern: /\.jar$/ },
  dotnet: { tools: [['dotnet', '--version']], command: ['sh', 'scripts/verify.sh'], directory: 'sdk-dotnet', output: 'artifacts', pattern: /\.(nupkg|snupkg)$/ },
  php: { tools: [['php', '--version'], ['composer', '--version']], command: ['php', 'scripts/verify.php'], directory: 'sdk-php', output: 'dist', pattern: /\.(zip|tar|tar\.gz)$/ },
  ruby: { tools: [['ruby', '--version'], ['gem', '--version']], command: ['ruby', 'scripts/verify.rb'], directory: 'sdk-ruby', output: 'pkg', pattern: /\.gem$/ },
};
const requested = process.argv.slice(2);
if (requested.includes('--help')) {
  console.log('Usage: node scripts/verify-all.mjs [node python go java dotnet php ruby]');
  console.log('Defaults to all packages. Install native toolchains and package development dependencies first; see CONTRIBUTING.md.');
  process.exit(0);
}
const selected = requested.length ? [...new Set(requested)] : Object.keys(packages);
for (const name of selected) assert(Object.hasOwn(packages, name), `Unknown package: ${name}`);
const run = ([command, ...args], cwd = root, env = process.env) => execFileSync(command, args, { cwd, env, stdio: 'inherit' });
// Check every selected tool before a lengthy verification. Missing runtimes are
// errors, never a reason to silently skip a package.
run([python, '--version']);
for (const name of selected) for (const tool of packages[name].tools) run(tool);
run([process.execPath, '--test', 'scripts/public-content.test.mjs', 'scripts/distribution.test.mjs']);
run([process.execPath, 'scripts/check-public-content.mjs']);
run([process.execPath, 'scripts/verify-contract.mjs']);

for (const name of selected) {
  const pkg = packages[name];
  console.log(`Verifying ${name} package and installed consumer...`);
  const temporary = name === 'go' ? mkdtempSync(join(tmpdir(), 'kompressr-go-distribution-')) : undefined;
  try {
    run(pkg.command, join(root, pkg.directory), temporary ? { ...process.env, KOMPRESSR_VERIFY_ARTIFACT_DIR: temporary } : process.env);
    if (pkg.pattern) {
      const output = temporary || join(root, pkg.directory, pkg.output);
      const archives = readdirSync(output).filter(name => pkg.pattern.test(name)).map(name => join(output, name));
      assert(archives.length > 0, `${name}: verification did not produce a distribution`);
      run([process.execPath, 'scripts/check-distribution.mjs', ...archives]);
    }
  } finally {
    if (temporary) rmSync(temporary, { recursive: true, force: true });
  }
}
console.log(`Verified: ${selected.join(', ')}. These checks use local fixtures, not a live account.`);
