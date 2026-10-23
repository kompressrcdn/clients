import assert from 'node:assert/strict';
import { test } from 'node:test';
import { checkPublicContent, checkPublicPath } from './public-content.mjs';

test('permits public endpoints and synthetic fixture addresses', () => {
  checkPublicContent('https://kompressr.com https://uploads.kompressr.com https://management.example.test http://127.0.0.1:3000', 'fixture');
});
test('rejects undeclared service hostnames without storing private hostnames in tests', () => {
  const address = ['https://', 'example', '.', 'kompressr.com'].join('');
  assert.throws(() => checkPublicContent(address, 'fixture'), /Undeclared/);
});
test('rejects credential-like tokens and private keys', () => {
  assert.throws(() => checkPublicContent('npm_' + 'x'.repeat(36), 'fixture'), /Credential/);
  assert.throws(() => checkPublicContent(['-----BEGIN ', 'PRIVATE KEY-----'].join(''), 'fixture'), /Private key/);
});
test('rejects machine paths and private record/configuration files', () => {
  assert.throws(() => checkPublicContent('/' + ['home', 'example', 'report'].join('/'), 'fixture'), /Machine/);
  for (const name of ['.env', '.npmrc', 'CLIENT_CONTEXT.md', 'docs/reviews/example.md']) {
    assert.throws(() => checkPublicPath(name));
  }
});


// Package build directories are excluded narrowly, without hiding source files.
import { isGeneratedDirectory } from './source-paths.mjs';
test('scopes native build and dependency exclusions to their package', () => {
  for (const path of ['scripts/release/__pycache__', 'sdk-python/.venv', 'sdk-python/src/pkg/__pycache__', 'sdk-python/src/pkg.egg-info', 'sdk-java/target', 'sdk-dotnet/src/Client/obj', 'sdk-php/vendor', 'sdk-ruby/vendor', 'sdk-ruby/.bundle', 'sdk-ruby/pkg', 'sdk-ruby/coverage']) {
    assert.equal(isGeneratedDirectory(path), true, path);
  }
  for (const path of ['scripts/release/release.py', 'scripts/release/test_release.py', 'scripts/other/__pycache__', 'contracts/target', 'sdk-go/bin', 'sdk-python/src', 'sdk-java/src', 'sdk-dotnet/tests', 'sdk-php/src', 'sdk-php/vendor-helper', 'sdk-ruby/lib', 'sdk-ruby/test', 'sdk-ruby/vendor-helper', 'contracts/pkg']) {
    assert.equal(isGeneratedDirectory(path), false, path);
  }
});

import { mkdtempSync, mkdirSync, copyFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync, spawnSync } from 'node:child_process';

test('tracked generated files cannot bypass the source guard', () => {
  const root = mkdtempSync(join(tmpdir(), 'kompressr-public-guard-'));
  try {
    mkdirSync(join(root, 'scripts'));
    mkdirSync(join(root, 'contracts'));
    mkdirSync(join(root, 'sdk-java', 'target'), { recursive: true });
    writeFileSync(join(root, 'package.json'), '{"type":"module"}');
    writeFileSync(join(root, 'contracts', 'source.json'), JSON.stringify({ contractVersion: 'fixture', sha256: 'fixture', snapshot: 'fixture', snapshotId: 'fixture' }));
    for (const file of ['check-public-content.mjs', 'public-content.mjs', 'source-paths.mjs']) {
      copyFileSync(fileURLToPath(new URL(file, import.meta.url)), join(root, 'scripts', file));
    }
    execFileSync('git', ['init', '--quiet'], { cwd: root });
    writeFileSync(join(root, 'sdk-java', 'target', 'fixture.txt'), 'npm_' + 'x'.repeat(36));
    const command = [join(root, 'scripts', 'check-public-content.mjs')];
    assert.equal(spawnSync(process.execPath, command, { cwd: root }).status, 0);
    execFileSync('git', ['add', '--', 'sdk-java/target/fixture.txt'], { cwd: root });
    const result = spawnSync(process.execPath, command, { cwd: root, encoding: 'utf8' });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Credential-like token/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
