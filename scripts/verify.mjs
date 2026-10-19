import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const run = (command, args) => execFileSync(command, args, { cwd: root, stdio: 'inherit' });
run(process.execPath, ['--test', 'scripts/public-content.test.mjs', 'scripts/mcp-release-metadata.test.mjs']);
run(process.execPath, ['scripts/check-public-content.mjs']);
run(process.execPath, ['scripts/verify-contract.mjs']);
run('npm', ['--prefix', 'sdk-js', 'run', 'verify']);
run('npm', ['--prefix', 'mcp-server', 'run', 'install:local-sdk']);
run('npm', ['--prefix', 'mcp-server', 'run', 'verify']);
