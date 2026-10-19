import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkPackedFiles, checkPublicContent, checkPublicPath } from './public-content.mjs';
import { mcpReleaseTag, verifyMcpMetadata, verifyMcpbReleaseUrl } from './verify-mcp-metadata.mjs';

const [destination, ...extra] = process.argv.slice(2);
assert(destination && extra.length === 0, 'Usage: node scripts/build-mcp-release.mjs empty-output-directory');
const root = realpathSync(fileURLToPath(new URL('../', import.meta.url)));
mkdirSync(resolve(destination), { recursive: true });
const output = realpathSync(resolve(destination));
const outputRelative = relative(root, output);
assert(isAbsolute(outputRelative) || outputRelative === '..' || outputRelative.startsWith('../'), 'Use an output directory outside the checkout.');
assert.equal(readdirSync(output).length, 0, 'The output directory must be empty; existing release files are never overwritten.');
const { pkg, server, manifest } = verifyMcpMetadata();
const work = mkdtempSync(join(tmpdir(), 'kompressr-mcp-build-'));
const run = (command, args, cwd = root) => execFileSync(command, args, { cwd, stdio: 'inherit' });
const hash = path => createHash('sha256').update(readFileSync(path)).digest('hex');
const write = (name, content) => writeFileSync(join(output, name), content, { flag: 'wx' });

try {
  const mcp = join(root, 'mcp-server');
  run('npm', ['run', 'build'], mcp);
  const [pack] = JSON.parse(execFileSync('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', output], { cwd: mcp, encoding: 'utf8' }));
  checkPackedFiles(pack.files, mcp, root);
  assert.equal(pack.version, pkg.version);
  const bundle = join(work, 'bundle');
  mkdirSync(bundle);
  run('tar', ['-xzf', join(output, pack.filename), '-C', bundle, '--strip-components=1']);
  assert.deepEqual(JSON.parse(readFileSync(join(bundle, 'package.json'), 'utf8')), pkg);
  copyFileSync(join(mcp, 'package-lock.json'), join(bundle, 'package-lock.json'));
  run('npm', ['ci', '--omit=dev', '--ignore-scripts', '--no-fund'], bundle);
  for (const name of ['manifest.json', '.mcpbignore']) copyFileSync(join(root, 'smithery', name), join(bundle, name));
  const filename = `kompressr-${pkg.version}.mcpb`;
  run('npx', ['--yes', '@anthropic-ai/mcpb@2.1.2', 'validate', join(bundle, 'manifest.json')]);
  run('npx', ['--yes', '@anthropic-ai/mcpb@2.1.2', 'pack', bundle, join(output, filename)]);
  const inspect = join(work, 'inspect');
  run('unzip', ['-q', join(output, filename), '-d', inspect]);
  function scan(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      const label = relative(inspect, path);
      assert(!entry.isSymbolicLink(), `Unexpected symbolic link: ${label}`);
      checkPublicPath(label);
      if (entry.isDirectory()) scan(path);
      else {
        const content = readFileSync(path);
        assert.deepEqual(content, readFileSync(join(bundle, label)), `Bundle changed installed content: ${label}`);
        // Third-party documentation may contain example machine paths. Preserve
        // those files byte-for-byte from npm's integrity-checked installation.
        if (!label.startsWith('node_modules/') || label.startsWith('node_modules/@kompressr/')) {
          checkPublicContent(content.toString('utf8'), label);
        }
      }
    }
  }
  scan(inspect);
  run(process.execPath, ['smithery/verify.mjs', inspect]);
  const tag = mcpReleaseTag(pkg.version);
  const identifier = `${server.repository.url}/releases/download/${encodeURIComponent(tag)}/${filename}`;
  verifyMcpbReleaseUrl(identifier);
  server.packages.push({
    registryType: 'mcpb',
    identifier,
    fileSha256: hash(join(output, filename)),
    transport: { type: 'stdio' },
  });
  write('server.json', `${JSON.stringify(server, null, 2)}\n`);
  write('RELEASE_NOTES.md', `# Kompressr MCP ${pkg.version}\n\n${readFileSync(join(mcp, 'CHANGELOG.md'), 'utf8').split(`## ${pkg.version}\n`)[1].split('\n## ')[0].trim()}\n\nDownload \`${filename}\` for an MCPB-compatible desktop client, or configure a stdio client to run \`npx -y ${pkg.name}@${pkg.version}\`. Requires Node.js ${manifest.compatibility.runtimes.node}.\n\n[Setup and tools](${server.repository.url}/blob/${encodeURIComponent(tag)}/mcp-server/README.md) · [Desktop installation](${server.repository.url}/blob/${encodeURIComponent(tag)}/smithery/README.md)\n`);
  const files = [pack.filename, filename, 'server.json', 'RELEASE_NOTES.md'];
  write('SHA256SUMS', files.map(name => `${hash(join(output, name))}  ${name}\n`).join(''));
  console.log(`Built and verified ${pkg.name}@${pkg.version} release files in ${output}`);
} finally {
  rmSync(work, { recursive: true, force: true });
}
