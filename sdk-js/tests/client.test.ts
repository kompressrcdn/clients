import { afterEach, describe, expect, it, vi } from 'vitest';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { readFileSync } from 'node:fs';
import { KompressrClient, KompressrError, resolveEndpoints, type Fetch } from '../src/index.js';

const fixtures = JSON.parse(readFileSync(new URL('../../contracts/fixtures/file-lifecycle.json', import.meta.url), 'utf8'));
const project = fixtures.projectId;
const userId = '660e8400-e29b-41d4-a716-446655440002';
const keyId = '660e8400-e29b-41d4-a716-446655440003';
const accepted = fixtures.accepted;
const status = fixtures.processed;
const lifecycle = fixtures.deletionAccepted;
const json = (data: unknown, code = 200, headers?: HeadersInit) => new Response(JSON.stringify(data), { status: code, headers });
const envelope = (data: unknown) => json({ success: true, data });
const resources: Array<() => Promise<unknown>> = [];
afterEach(async () => { vi.restoreAllMocks(); await Promise.all(resources.splice(0).map(close => close())); });
async function endpoint(handler: (request: IncomingMessage, response: ServerResponse) => void | Promise<void>) {
  const server = createServer((request, response) => { Promise.resolve(handler(request, response)).catch(() => { response.writeHead(500); response.end('{}'); }); });
  await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  resources.push(() => new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }));
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No server address');
  return `http://127.0.0.1:${address.port}`;
}
function client(fetch: Fetch, extra = {}) { return new KompressrClient({ apiKey: 'fixture-key', projectId: project, fetch, maxReadRetries: 0, ...extra }); }

describe('SDK contract and normal follow-up actions', () => {
  it('sends a real multipart file to the upload origin, then fetches current readiness from the API origin', async () => {
    let order: string[] = [], quality: unknown, visibility: unknown, filename = '', receivedBytes = 0;
    const uploadOrigin = await endpoint(async (request, response) => {
      expect(request.url).toBe('/api/upload'); expect(request.headers.authorization).toBe('Bearer fixture-key');
      const chunks = []; for await (const chunk of request) chunks.push(chunk);
      const body = Buffer.concat(chunks); receivedBytes = body.length;
      const parsed = await new Request('http://fixture', { method: 'POST', headers: { 'Content-Type': request.headers['content-type']! }, body }).formData();
      order = [...parsed.keys()]; quality = parsed.get('kmp-quality'); visibility = parsed.get('visibility'); filename = (parsed.get('file') as File).name;
      response.end(JSON.stringify({ success: true, data: accepted }));
    });
    let polls = 0;
    const apiOrigin = await endpoint((request, response) => {
      expect(request.url).toBe('/api/upload/42/status'); polls++;
      response.end(JSON.stringify({ success: true, data: { ...status, status: polls === 1 ? 'pending' : 'processed' } }));
    });
    const directory = await mkdtemp(join(tmpdir(), 'sdk-file-')); resources.push(() => rm(directory, { recursive: true, force: true }));
    const path = join(directory, 'output.png'); await writeFile(path, Buffer.alloc(4 * 1024 * 1024));
    const files = new KompressrClient({ apiKey: 'fixture-key', apiBaseUrl: apiOrigin, uploadBaseUrl: uploadOrigin });
    const response = await files.uploadFile(path, { visibility: 'public', quality: '1080p', data: { external_id: 'image-123' } });
    expect(response.id).toBe(42); expect(response.status).toBe('processing');
    expect(order).toEqual(['visibility', 'kmp-quality', 'data', 'file']); expect(quality).toBe('1080p'); expect(visibility).toBe('public'); expect(filename).toBe('output.png');
    expect(receivedBytes).toBeGreaterThan(4 * 1024 * 1024);
    const ready = await files.waitUntilReady(response.id, { pollIntervalMs: 1, timeoutMs: 2000 });
    expect(ready.cdn_url).toBe('https://cdn.example/ready.webp'); expect(polls).toBe(2);
  });
  it('waits for private processing then signs a fresh URL without introducing public delivery', async () => {
    const fetch = vi.fn<Fetch>().mockResolvedValueOnce(envelope({ ...accepted, visibility: 'private', cdn_url: undefined, private_url: 'https://cdn.example/p/initial?s=secret' }))
      .mockResolvedValueOnce(envelope({ ...status, visibility: 'private', cdn_url: undefined, can_generate_private_url: true }))
      .mockResolvedValueOnce(envelope({ asset_id: 42, variant: 'webp', private_url: 'https://cdn.example/p/fresh?s=secret', expires_at: '2026-10-13T12:00:00Z', expires_in: 3600 }));
    const files = client(fetch);
    const first = await files.uploadBytes(Buffer.from('fixture'), 'output.png', { visibility: 'private' });
    expect(first.cdn_url).toBeUndefined();
    const ready = await files.waitUntilReady(first.id); expect(ready.visibility).toBe('private');
    const signed = await files.generatePrivateUrl(first.id); expect(signed.private_url).toContain('/fresh');
    expect(fetch.mock.calls[2][0]).toBe('https://kompressr.com/api/upload/42/private-url');
  });
  it('pages through upload-only results and encodes identity/metadata/deletion/status filters', async () => {
    const fetch = vi.fn<Fetch>().mockResolvedValueOnce(json({ success: true, data: [status], page: 1, limit: 1, total: 2 }))
      .mockResolvedValueOnce(json({ success: true, data: [{ ...status, id: 43 }], page: 2, limit: 1, total: 2 }));
    const results = [];
    for await (const row of client(fetch).iterateUploads({ limit: 1, status: 'processed', data: { owner: 'a&b' }, deletionStatus: 'active' })) results.push(row.id);
    expect(results).toEqual([42, 43]);
    const url = new URL(String(fetch.mock.calls[1][0]));
    expect(url.searchParams.get('page')).toBe('2'); expect(url.searchParams.get('project_id')).toBe(project);
    expect(url.searchParams.get('data.owner')).toBe('a&b'); expect(url.searchParams.get('status')).toBe('3');
  });
  it('keeps accepted deletion, later cleanup, and mixed bulk failures distinct', async () => {
    const fetch = vi.fn<Fetch>().mockResolvedValueOnce(json(lifecycle, 202))
      .mockResolvedValueOnce(json({ ...lifecycle, deletion_status: 'deleted', processing_status: 6, storage_credited_mb: 2 }))
      .mockResolvedValueOnce(json({ results: [{ id: 42, accepted: true, status: 200, state: { ...lifecycle, deletion_status: 'deleted' } }, { id: 43, accepted: false, status: 404, code: 'ASSET_NOT_FOUND', error: 'Asset not found.' }], counts: { total: 2, accepted: 1, failed: 1 } }));
    const files = client(fetch);
    expect((await files.deleteAsset(42)).deletion_status).toBe('deleting');
    expect((await files.getAsset(42)).storage_credited_mb).toBe(2);
    const batch = await files.bulkDeleteAssets([42, 42, 43]); expect(batch.counts.failed).toBe(1); expect(batch.results[1].accepted).toBe(false);
    expect(JSON.parse(String(fetch.mock.calls[2][1]?.body))).toEqual({ asset_ids: [42, 42, 43] });
  });
  it('requires a project only for uploads listing and keeps managed-asset listing key-scoped', async () => {
    const fetch = vi.fn<Fetch>().mockResolvedValue(json({ data: [lifecycle], page: 1, limit: 20, total: 1 }));
    const files = client(fetch, { projectId: undefined });
    await expect(files.listUploads()).rejects.toMatchObject({ code: 'INVALID_ARGUMENT' });
    expect((await files.listAssets()).data[0].id).toBe(42); expect(String(fetch.mock.calls[0][0])).not.toContain('project_id');
  });
});

describe('timeouts, authorization, malformed responses and replay safety', () => {
  it.each(['failed', 'unprocessable', 'unknown'])('rejects terminal %s even when a URL exists', async state => {
    const files = client(async () => envelope({ ...status, status: state }));
    await expect(files.waitUntilReady(42)).rejects.toMatchObject({ code: 'PROCESSING_FAILED', assetId: 42 });
  });
  it('rejects deleting assets and malformed private/public or missing readiness fields', async () => {
    await expect(client(async () => envelope({ ...status, deletion_status: 'deleting', cdn_url: undefined })).waitUntilReady(42)).rejects.toMatchObject({ code: 'ASSET_DELETED' });
    await expect(client(async () => envelope({ ...status, visibility: 'private' })).getUploadStatus(42)).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    await expect(client(async () => envelope({ ...status, deletion_status: undefined })).getUploadStatus(42)).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    await expect(client(async () => envelope({ ...status, cdn_url: undefined })).waitUntilReady(42)).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });
  it('times out native response-body reads and preserves the asset ID for resumed waiting', async () => {
    const origin = await endpoint((_request, response) => { response.writeHead(200, { 'Content-Type': 'application/json' }); response.write('{"success":true,"data":'); });
    const files = new KompressrClient({ apiKey: 'fixture-key', apiBaseUrl: origin, maxReadRetries: 0 });
    await expect(files.waitUntilReady(42, { timeoutMs: 50 })).rejects.toMatchObject({ code: 'WAIT_TIMEOUT', assetId: 42 });
  });
  it('cancels pending waits and never reuploads after a wait timeout', async () => {
    const fetch = vi.fn<Fetch>().mockImplementation(async () => envelope({ ...status, status: 'pending' }));
    const files = client(fetch);
    await expect(files.waitUntilReady(42, { timeoutMs: 20, pollIntervalMs: 10 })).rejects.toMatchObject({ code: 'WAIT_TIMEOUT', assetId: 42 });
    expect(fetch.mock.calls.every(x => !x[1]?.method || x[1]?.method === 'GET')).toBe(true);
    const controller = new AbortController(); controller.abort();
    await expect(files.waitUntilReady(42, { signal: controller.signal })).rejects.toMatchObject({ code: 'WAIT_CANCELLED', assetId: 42 });
  });
  it('retries eligible reads but never an ambiguous upload or provisioning write', async () => {
    const fetch = vi.fn<Fetch>().mockResolvedValueOnce(json({ error: 'Temporarily unavailable' }, 503)).mockResolvedValueOnce(envelope(status));
    await expect(client(fetch, { maxReadRetries: 1 }).getUploadStatus(42)).resolves.toHaveProperty('id', 42);
    expect(fetch).toHaveBeenCalledTimes(2);
    fetch.mockReset().mockRejectedValue(new Error('connection lost'));
    await expect(client(fetch).uploadBytes(Buffer.from('fixture'), 'output.png')).rejects.toMatchObject({ code: 'NETWORK_ERROR', mayHaveSucceeded: true }); expect(fetch).toHaveBeenCalledTimes(1);
    await expect(client(fetch).platform.createUser({ customerUserId: 'user-1' })).rejects.toMatchObject({ mayHaveSucceeded: true }); expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('respects a long Retry-After until the finite deadline and preserves a 403 permission error', async () => {
    const fetch = vi.fn<Fetch>().mockResolvedValue(json({ error: 'Rate limited' }, 429, { 'Retry-After': '5' }));
    await expect(client(fetch, { maxReadRetries: 2 }).getUploadStatus(42, { timeoutMs: 40 })).rejects.toMatchObject({ code: 'REQUEST_TIMEOUT' });
    expect(fetch).toHaveBeenCalledTimes(1);
    fetch.mockReset().mockResolvedValue(json({ code: 'FORBIDDEN', error: 'Missing delete scope' }, 403));
    await expect(client(fetch).deleteAsset(42)).rejects.toMatchObject({ code: 'FORBIDDEN', status: 403, mayHaveSucceeded: false });
  });
  it('does not include gateway HTML, credentials or signed URLs in errors', async () => {
    await expect(client(async () => new Response('<html>secret-token</html>', { status: 502 })).getUploadStatus(42)).rejects.toMatchObject({ status: 502 });
    try { await client(async () => json({ error: 'Bearer fixture-key https://cdn.example/p/file?s=signature' }, 403)).getUploadStatus(42); }
    catch (error) { expect(error).toBeInstanceOf(KompressrError); const value = JSON.stringify(error); expect(value).not.toContain('fixture-key'); expect(value).not.toContain('signature'); }
  });
  it('rejects unsafe IDs, huge bulk selections, fractional lifetimes and excess metadata before any request', async () => {
    const fetch = vi.fn<Fetch>(); const files = client(fetch);
    await expect(files.getAsset(Number.MAX_SAFE_INTEGER + 1)).rejects.toMatchObject({ code: 'INVALID_ARGUMENT' });
    await expect(files.bulkDeleteAssets(Array.from({ length: 101 }, (_, i) => i + 1))).rejects.toMatchObject({ code: 'INVALID_ARGUMENT' });
    await expect(files.generatePrivateUrl(42, { expiresIn: 60.5 })).rejects.toMatchObject({ code: 'INVALID_ARGUMENT' });
    await expect(files.uploadBytes(Buffer.from('x'), 'output.png', { data: { a: 1, b: 2, c: 3, d: 4, e: 5, f: 6 } })).rejects.toMatchObject({ code: 'INVALID_ARGUMENT' });
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe('platform administration and endpoint selection', () => {
  it('defaults to production and preserves explicit custom management and upload origins', () => {
    expect(resolveEndpoints()).toEqual({ apiBaseUrl: 'https://kompressr.com', uploadBaseUrl: 'https://uploads.kompressr.com' });
    expect(resolveEndpoints({ apiBaseUrl: 'https://management.example.test', uploadBaseUrl: 'https://uploads.example.test' })).toEqual({ apiBaseUrl: 'https://management.example.test', uploadBaseUrl: 'https://uploads.example.test' });
    expect(resolveEndpoints({ apiBaseUrl: 'http://127.0.0.1:1234' }).uploadBaseUrl).toBe('http://127.0.0.1:1234');
    expect(() => resolveEndpoints({ apiBaseUrl: 'https://user:secret@example.com' })).toThrow(KompressrError);
    expect(() => resolveEndpoints({ environment: 'custom' } as never)).toThrow(KompressrError);
  });
  it('provisions identities and returns one-time keys without adding delete to default scopes', async () => {
    const user = { id: userId, project_id: project, customer_user_id: 'user-1', display_name: 'User 1', status: 'active' };
    const fetch = vi.fn<Fetch>().mockResolvedValueOnce(json({ success: true, created: true, project_user: user }))
      .mockResolvedValueOnce(json({ success: true, id: keyId, key_id: keyId, api_key: 'one-time-key' }))
      .mockResolvedValueOnce(json({ success: true, id: keyId, key_id: keyId, api_key: 'replacement-key' }))
      .mockResolvedValueOnce(json({ success: true, message: 'Revoked' }))
      .mockResolvedValueOnce(json({ success: true, project_user: { ...user, status: 'suspended' } }))
      .mockResolvedValueOnce(json({ success: true, project_user: user }));
    const platform = client(fetch).platform;
    expect((await platform.createUser({ customerUserId: 'user-1' })).created).toBe(true);
    expect((await platform.createUploadKey(userId, { name: 'Runtime' })).api_key).toBe('one-time-key');
    expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual({ name: 'Runtime' });
    expect((await platform.rotateUploadKey(userId, keyId)).api_key).toBe('replacement-key');
    await platform.revokeUploadKey(userId, keyId);
    expect((await platform.suspendUser(userId)).status).toBe('suspended'); expect((await platform.reactivateUser(userId)).status).toBe('active');
    expect(fetch.mock.calls.every(x => String(x[0]).startsWith('https://kompressr.com/api/platform/'))).toBe(true);
  });
});


it('accepts the API identity with an omitted empty display name and validates typed list summaries', async () => {
  const user = { id: userId, project_id: project, customer_user_id: 'user-1', status: 'active' };
  const fetch = vi.fn<Fetch>().mockResolvedValueOnce(json({ success: true, created: true, project_user: user }))
    .mockResolvedValueOnce(json({ success: true, project_users: [user], page: 1, limit: 20, total: 1, project_active_count: 1, org_active_count: 2, usage_period: { start: '2026-10-01', end: '2026-11-01' } }))
    .mockResolvedValueOnce(json({ success: true, project_users: [], page: 1, limit: 20, total: 0, project_active_count: 'wrong', org_active_count: 2 }));
  const platform = client(fetch).platform;
  expect((await platform.createUser({ customerUserId: 'user-1' })).project_user.display_name).toBeUndefined();
  const listed = await platform.listUsers(); expect(listed.org_active_count).toBe(2); expect(listed.usage_period?.start).toBe('2026-10-01');
  await expect(platform.listUsers()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
});
