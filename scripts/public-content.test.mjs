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
