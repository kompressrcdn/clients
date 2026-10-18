import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

// Inspect the extracted bundle through stdio. No API calls or publishing occur.
const [directory, ...extra] = process.argv.slice(2);
assert(directory && extra.length === 0, 'Usage: node smithery/verify.mjs extracted-bundle-directory');
const root = resolve(directory);
const read = path => JSON.parse(readFileSync(path, 'utf8'));
const manifest = read(join(root, 'manifest.json'));
const pkg = read(join(root, 'package.json'));
const payload = read(new URL('./release-payload.json', import.meta.url));
const require = createRequire(join(root, 'package.json'));
const { Client } = await import(pathToFileURL(require.resolve('@modelcontextprotocol/sdk/client/index.js')).href);
const { StdioClientTransport } = await import(pathToFileURL(require.resolve('@modelcontextprotocol/sdk/client/stdio.js')).href);
assert.equal(pkg.name, '@kompressr/mcp-server');
assert.equal(manifest.version, pkg.version);
assert.equal(manifest.server.entry_point, 'dist/index.js');
assert.equal(payload.type, 'stdio');
assert.equal(payload.runtime, 'node');
const config = Object.fromEntries(Object.entries(manifest.user_config).map(([name, value]) => [name, {
  type: value.type, title: value.title, description: value.description,
  ...(value.sensitive ? { writeOnly: true } : {}),
  ...(value.default !== undefined ? { default: value.default } : {}),
}]));
assert.deepEqual(payload.configSchema, {
  type: 'object', properties: config,
  required: Object.entries(manifest.user_config).filter(([, value]) => value.required).map(([name]) => name),
});
const client = new Client({ name: 'kompressr-bundle-verifier', version: '1.0.0' });
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [join(root, manifest.server.entry_point)],
  cwd: root,
  env: {
    KOMPRESSR_API_KEY: 'fixture-bundle-inspection', KOMPRESSR_PROJECT_ID: '',
    KOMPRESSR_API_URL: 'https://kompressr.com',
    KOMPRESSR_UPLOAD_BASE_URL: 'https://uploads.kompressr.com',
  },
  stderr: 'pipe',
});
// Drain diagnostics without forwarding user configuration or environment data.
transport.stderr?.on('data', () => {});
const deadline = setTimeout(() => {
  console.error('Bundle inspection exceeded its 15-second deadline.');
  void transport.close().finally(() => process.exit(1));
}, 15_000);
try {
  await client.connect(transport);
  assert.deepEqual(client.getServerVersion(), payload.serverCard.serverInfo);
  const { tools, nextCursor } = await client.listTools();
  assert.equal(nextCursor, undefined);
  assert.equal(tools.length, 10);
  assert.deepEqual(tools, payload.serverCard.tools);
  assert.deepEqual(tools.map(({ name, description }) => ({ name, description })), manifest.tools);
  console.log(`Verified Kompressr ${pkg.version}: stdio handshake, ten tool schemas and bundle configuration.`);
} finally {
  clearTimeout(deadline);
  await client.close();
}
