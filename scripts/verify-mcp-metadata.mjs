import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join } from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));

export function verifyMcpMetadata() {
  const read = path => JSON.parse(readFileSync(join(root, path), 'utf8'));
  const pkg = read('mcp-server/package.json');
  const lock = read('mcp-server/package-lock.json');
  const server = read('mcp-server/server.json');
  const manifest = read('smithery/manifest.json');
  const payload = read('smithery/release-payload.json');
  assert.match(pkg.version, /^\d+\.\d+\.\d+$/);
  assert.equal(pkg.mcpName, 'com.kompressr/kompressr');
  assert.equal(server.name, pkg.mcpName);
  for (const version of [lock.version, lock.packages[''].version, server.version,
    manifest.version, payload.serverCard.serverInfo.version]) {
    assert.equal(version, pkg.version, 'MCP package, bundle and registry versions must match.');
  }
  assert.deepEqual(lock.packages[''].dependencies, pkg.dependencies);
  assert.equal(manifest.compatibility.runtimes.node, pkg.engines.node);
  assert.equal(server.repository.url, 'https://github.com/kompressrcdn/clients');
  assert.equal(server.repository.subfolder, 'mcp-server');
  assert.equal(server.packages.length, 1, 'Source metadata describes npm; the builder adds the hashed bundle.');
  const npm = server.packages[0];
  assert.equal(npm.registryType, 'npm');
  assert.equal(npm.identifier, pkg.name);
  assert.equal(npm.version, pkg.version);
  assert.equal(npm.transport.type, 'stdio');
  assert(!server.remotes, 'This server is distributed for local stdio use.');
  for (const [setting, variable] of [['api_key', 'KOMPRESSR_API_KEY'], ['project_id', 'KOMPRESSR_PROJECT_ID']]) {
    const config = manifest.user_config[setting];
    const env = npm.environmentVariables.find(item => item.name === variable);
    assert(env, `Missing registry configuration: ${variable}`);
    assert.equal(env.description, config.description);
    assert.equal(env.format, config.type);
    assert.equal(Boolean(env.isRequired), Boolean(config.required));
    assert.equal(Boolean(env.isSecret), Boolean(config.sensitive));
    assert(!Object.hasOwn(env, 'value') && !Object.hasOwn(env, 'default'), 'Users supply credentials and project IDs.');
  }
  console.log(`Verified MCP ${pkg.version} package, registry and bundle metadata.`);
  return { pkg, server, manifest };
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) verifyMcpMetadata();
