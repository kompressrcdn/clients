import { describe, expect, it, vi } from 'vitest';
import { KompressrClient, type Fetch } from '../src/index.js';
import { createServer } from 'node:http';

const project = '660e8400-e29b-41d4-a716-446655440001';
const user = '660e8400-e29b-41d4-a716-446655440002';
const key = '660e8400-e29b-41d4-a716-446655440003';
const accepted = { asset_id: 42, status: 'pending', visibility: 'public', deletion_status: 'active', original_name: 'fixture.png', original_size: 3, asset_type: 'image' };
const unnamed = { id: 42, status: 'processed', visibility: 'public', deletion_status: 'active', original_size: 3, asset_type: 'image', cdn_url: 'https://cdn.example/ready.webp', kompressd_size: 2, savings_percent: 33, can_generate_private_url: false };
const envelope = (data: unknown) => Response.json({ success: true, data });
const make = (fetch: Fetch) => new KompressrClient({ apiKey: 'fixture', projectId: project, fetch, maxReadRetries: 0 });

const mutations = [
  { name: 'upload', run: (c: KompressrClient) => c.uploadBytes(Buffer.from('abc'), 'fixture.png') },
  { name: 'sign', assetId: 42, run: (c: KompressrClient) => c.generatePrivateUrl(42) },
  { name: 'delete', assetId: 42, run: (c: KompressrClient) => c.deleteAsset(42) },
  { name: 'bulk delete', run: (c: KompressrClient) => c.bulkDeleteAssets([42, 43]) },
  { name: 'create user', run: (c: KompressrClient) => c.platform.createUser({ customerUserId: 'customer' }) },
  { name: 'update user', run: (c: KompressrClient) => c.platform.updateUser(user, { displayName: 'Customer' }) },
  { name: 'suspend user', run: (c: KompressrClient) => c.platform.suspendUser(user) },
  { name: 'reactivate user', run: (c: KompressrClient) => c.platform.reactivateUser(user) },
  { name: 'create key', run: (c: KompressrClient) => c.platform.createUploadKey(user, { name: 'Runtime' }) },
  { name: 'rotate key', run: (c: KompressrClient) => c.platform.rotateUploadKey(user, key) },
  { name: 'revoke key', run: (c: KompressrClient) => c.platform.revokeUploadKey(user, key) },
];

describe('review: sent writes remain uncertain when the successful response is invalid', () => {
  for (const operation of mutations) {
    it.each(['broken JSON', 'incomplete object'])(`${operation.name}: %s`, async variant => {
      const body = operation.name === 'revoke key' ? {} : { success: true, data: { asset_id: 42 } };
      const fetch = vi.fn<Fetch>().mockResolvedValue(variant === 'broken JSON' ? new Response('{broken', { status: 200 }) : Response.json(body));
      await expect(operation.run(make(fetch))).rejects.toMatchObject({ code: 'INVALID_RESPONSE', kind: 'invalid_response', status: 200, mayHaveSucceeded: true,
        ...(operation.assetId ? { assetId: operation.assetId } : operation.name === 'upload' && variant === 'incomplete object' ? { assetId: 42 } : {}),
      });
      expect(fetch).toHaveBeenCalledTimes(1);
    });
  }
  it.each([0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, '42'])('does not manufacture an upload ID from invalid field %s', async asset_id => {
    const fetch = vi.fn<Fetch>().mockResolvedValue(envelope({ asset_id }));
    await expect(make(fetch).uploadBytes(Buffer.from('abc'), 'fixture.png')).rejects.toMatchObject({ code: 'INVALID_RESPONSE', mayHaveSucceeded: true, assetId: undefined });
  });
  it('retains the requested deletion ID when the returned record names another asset', async () => {
    const fetch = vi.fn<Fetch>().mockResolvedValue(Response.json({ id: 43, project_id: project, kind: 1, source: 'upload', processing_status: 3, deletion_status: 'deleting', storage_credited_mb: 0 }));
    await expect(make(fetch).deleteAsset(42)).rejects.toMatchObject({ code: 'INVALID_RESPONSE', assetId: 42, mayHaveSucceeded: true });
  });
  it('keeps read errors and validation before a write distinct from ambiguous writes', async () => {
    const fetch = vi.fn<Fetch>().mockResolvedValue(new Response('{broken', { status: 200 }));
    await expect(make(fetch).getUploadStatus(42)).rejects.toMatchObject({ code: 'INVALID_RESPONSE', mayHaveSucceeded: false });
    fetch.mockClear();
    await expect(make(fetch).bulkDeleteAssets([])).rejects.toMatchObject({ code: 'INVALID_ARGUMENT', mayHaveSucceeded: false });
    expect(fetch).not.toHaveBeenCalled();
  });
  it('does not mark a pre-cancelled upload as dispatched or call fetch', async () => {
    const fetch = vi.fn<Fetch>(); const controller = new AbortController(); controller.abort();
    await expect(make(fetch).uploadBytes(Buffer.from('abc'), 'fixture.png', { signal: controller.signal })).rejects.toMatchObject({ code: 'REQUEST_CANCELLED', mayHaveSucceeded: false });
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe('review: names are optional on existing upload records', () => {
  it.each([undefined, ''])('reads, waits for and lists a record with original_name=%s', async original_name => {
    const fetch = vi.fn<Fetch>().mockImplementation(async input => String(input).includes('/api/uploads?') ? Response.json({ success: true, data: [{ ...unnamed, original_name }, { ...unnamed, id: 43, original_name: 'named.png' }], page: 1, limit: 20, total: 2 }) : envelope({ ...unnamed, original_name }));
    const client = make(fetch);
    expect((await client.getUploadStatus(42)).id).toBe(42);
    expect((await client.waitUntilReady(42)).cdn_url).toBe(unnamed.cdn_url);
    expect((await client.listUploads()).data.map(x => x.id)).toEqual([42, 43]);
  });
});

describe('review: uploadBytes snapshots only the selected bytes', () => {
  it.each(['Buffer', 'Uint8Array', 'shared', 'resizable'])('preserves %s view boundaries and snapshot semantics', async kind => {
    const backing = kind === 'shared' ? new SharedArrayBuffer(8) : kind === 'resizable' ? new ArrayBuffer(8, { maxByteLength: 16 }) : new ArrayBuffer(8);
    const bytes = kind === 'Buffer' ? Buffer.from(backing) : new Uint8Array(backing);
    bytes.set([99, 98, 1, 2, 3, 97, 96, 95]); const view = bytes.subarray(2, 5);
    let file!: Blob;
    const fetch = vi.fn<Fetch>().mockImplementation(async (_input, init) => { file = (init!.body as FormData).get('file') as Blob; return envelope(accepted); });
    const promise = make(fetch).uploadBytes(view, 'fixture.png'); view.fill(9);
    if (kind === 'resizable') (backing as ArrayBuffer).resize(16);
    await promise; expect(file.size).toBe(3); expect([...new Uint8Array(await file.arrayBuffer())]).toEqual([1, 2, 3]);
  });
});


it.each(['{broken', '{"success":true,"data":{"asset_id":42}}'])('preserves ambiguity after a real HTTP upload receives %s', async body => {
  let writes = 0;
  const server = createServer(async (request, response) => {
    for await (const chunk of request) { void chunk; }
    writes++; response.end(body);
  });
  await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  try {
    const address = server.address(); if (!address || typeof address === 'string') throw new Error('No address');
    const client = new KompressrClient({ apiKey: 'fixture', apiBaseUrl: `http://127.0.0.1:${address.port}` });
    await expect(client.uploadBytes(Buffer.from('abc'), 'fixture.png')).rejects.toMatchObject({ code: 'INVALID_RESPONSE', status: 200, mayHaveSucceeded: true, assetId: body.startsWith('{broken') ? undefined : 42 });
    expect(writes).toBe(1);
  } finally {
    server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve()));
  }
});
