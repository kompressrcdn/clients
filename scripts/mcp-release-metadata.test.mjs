import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mcpReleaseTag, verifyMcpbReleaseUrl } from './verify-mcp-metadata.mjs';

const prefix = 'https://github.com/kompressrcdn/clients/releases/download/';

test('generated MCPB URL satisfies the registry decoded-path contract', () => {
  const tag = mcpReleaseTag('2.0.2');
  const identifier = `${prefix}${encodeURIComponent(tag)}/kompressr-2.0.2.mcpb`;
  verifyMcpbReleaseUrl(identifier);
  assert.equal(decodeURIComponent(new URL(identifier).pathname).split('/').filter(Boolean).length, 6);
});

for (const tag of ['mcp-server/v2.0.2', 'mcp-server%2Fv2.0.2']) {
  test(`rejects the unsupported multi-segment release tag ${tag}`, () => {
    assert.throws(() => verifyMcpbReleaseUrl(`${prefix}${tag}/kompressr-2.0.2.mcpb`), /tag without slashes/);
  });
}

test('a release tag requires a stable package version', () => {
  for (const version of ['2.0.2/other', '../2.0.2', '2.0.2-rc.1', '']) {
    assert.throws(() => mcpReleaseTag(version));
  }
});
