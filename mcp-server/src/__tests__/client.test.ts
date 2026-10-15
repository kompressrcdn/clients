import { afterEach, describe, expect, it, vi } from 'vitest';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { readFileSync } from 'node:fs';
import { KompressrClient } from '../client.js';

const fixtures = JSON.parse(readFileSync(new URL('../../../contracts/fixtures/file-lifecycle.json', import.meta.url), 'utf8'));
const project = fixtures.projectId;
const accepted = fixtures.accepted;
const ready = fixtures.processed;
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
afterEach(() => vi.unstubAllGlobals());

describe('MCP adapter consumes the SDK HTTP contract', () => {
  it('uploads a file with options first to uploads and checks readiness on the application host', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'mcp-file-')); const file = join(directory, 'output.png'); await writeFile(file, 'abc');
    const fetch = vi.fn().mockResolvedValueOnce(json({ success: true, data: accepted })).mockResolvedValueOnce(json({ success: true, data: ready }));
    vi.stubGlobal('fetch', fetch);
    try {
      const client = new KompressrClient('https://management.example.test', 'fixture-key', undefined, 'https://uploads.example.test');
      expect((await client.uploadFile(file, { quality: '1080p', visibility: 'public' })).data?.asset_id).toBe(42);
      expect(fetch.mock.calls[0][0]).toBe('https://uploads.example.test/api/upload');
      const form = fetch.mock.calls[0][1].body as FormData;
      expect([...form.keys()]).toEqual(['visibility', 'kmp-quality', 'file']);
      expect((await client.waitUntilReady('42')).data?.cdn_url).toContain('/ready');
      expect(fetch.mock.calls[1][0]).toBe('https://management.example.test/api/upload/42/status');
    } finally { await rm(directory, { recursive: true, force: true }); }
  });
  it('only upload listing requires a project UUID and forwards all page filters', async () => {
    const fetch = vi.fn().mockResolvedValue(json({ success: true, data: [ready], page: 2, limit: 1, total: 2 })); vi.stubGlobal('fetch', fetch);
    const client = new KompressrClient('https://kompressr.com', 'fixture');
    await expect(client.listAssets()).rejects.toMatchObject({ code: 'PROJECT_ID_REQUIRED' }); expect(fetch).not.toHaveBeenCalled();
    client.setCredentials('fixture', project);
    expect((await client.listAssets(1, { page: 2, status: 'processed', data: { owner: 'a&b' } })).page).toBe(2);
    const url = new URL(fetch.mock.calls[0][0]); expect(url.searchParams.get('data.owner')).toBe('a&b'); expect(url.searchParams.get('page')).toBe('2'); expect(url.searchParams.get('status')).toBe('3');
  });
  it('preserves deletion acceptance and mixed per-item failure', async () => {
    const state = fixtures.deletionAccepted;
    const fetch = vi.fn().mockResolvedValueOnce(json(state, 202)).mockResolvedValueOnce(json(fixtures.bulkDeletion)); vi.stubGlobal('fetch', fetch);
    const client = new KompressrClient('https://kompressr.com', 'fixture');
    expect((await client.deleteAsset('42')).deletion_status).toBe('deleting'); expect((await client.bulkDeleteAssets([42, 43])).results[1].accepted).toBe(false);
    expect(fetch.mock.calls[0][1].method).toBe('DELETE');
  });
  it('rejects invalid IDs without HTTP and supports key-only status operations', async () => {
    const fetch = vi.fn().mockResolvedValue(json({ success: true, data: ready })); vi.stubGlobal('fetch', fetch);
    const client = new KompressrClient('https://kompressr.com', 'fixture');
    await expect(client.getStatus('42tail')).rejects.toMatchObject({ code: 'INVALID_ARGUMENT' }); expect(fetch).not.toHaveBeenCalled();
    expect((await client.getStatus(42)).success).toBe(true);
  });
  it('keeps account setup separate and rejects non-JSON gateways without leaking bodies', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json({ success: true })).mockResolvedValueOnce(new Response('<html>secret</html>', { status: 502 })); vi.stubGlobal('fetch', fetch);
    const client = new KompressrClient('https://management.example.test');
    expect((await client.register('person@example.com', 'long-password')).success).toBe(true);
    expect(fetch.mock.calls[0][0]).toBe('https://management.example.test/api/v1/signup');
    await expect(client.verifyEmail('token')).rejects.toMatchObject({ code: 'INVALID_RESPONSE', status: 502 });
  });
});
