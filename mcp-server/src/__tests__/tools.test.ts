import { afterEach, describe, expect, it, vi } from 'vitest';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { createServer } from '../server.js';
import { KompressrClient } from '../client.js';
import { KompressrError } from '@kompressr/sdk';
import { saveConfig } from '../config.js';
vi.mock('../config.js', () => ({ saveConfig: vi.fn(), getConfigPath: () => '/isolated/config.json' }));

const cleanup: Array<() => Promise<unknown>> = [];
afterEach(async () => { await Promise.all(cleanup.splice(0).map(close => close())); vi.restoreAllMocks(); vi.clearAllMocks(); });
async function connected(configured = true) {
  const adapter = new KompressrClient('https://kompressr.com', configured ? 'fixture' : undefined);
  const server = createServer(adapter), client = new Client({ name: 'contract-test', version: '1.0.0' });
  const [a, b] = InMemoryTransport.createLinkedPair();
  await server.connect(a); await client.connect(b);
  cleanup.push(() => client.close(), () => server.close());
  return { adapter, client };
}
const asset = { id: 42, status: 'processed' as const, visibility: 'public' as const, deletion_status: 'active' as const, original_name: 'output.png', original_size: 1024, asset_type: 'image', kompressd_size: 512, savings_percent: 50, can_generate_private_url: false, cdn_url: 'https://cdn.example/ready.webp' };

describe('MCP protocol schemas, annotations and workflow', () => {
  it('advertises the existing six tools and four lifecycle tools, with destructive annotations', async () => {
    const { client } = await connected(); const { tools } = await client.listTools();
    expect(tools.map(x => x.name).sort()).toEqual(['register', 'verify_email', 'upload_asset', 'get_asset_status', 'list_assets', 'generate_private_url', 'wait_for_asset', 'get_asset_deletion_status', 'delete_asset', 'bulk_delete_assets'].sort());
    expect(tools.find(x => x.name === 'delete_asset')?.annotations).toMatchObject({ destructiveHint: true, readOnlyHint: false, idempotentHint: true });
    expect(tools.find(x => x.name === 'get_asset_status')?.annotations?.readOnlyHint).toBe(true);
    expect(client.getServerVersion()?.version).toBe('2.0.3');
  });
  it('returns structured acceptance without marking a pending URL ready, then current processed status', async () => {
    const { adapter, client } = await connected();
    vi.spyOn(adapter, 'uploadFile').mockResolvedValue({ success: true, data: { ...asset, asset_id: 42, status: 'pending', cdn_url: 'https://cdn.example/initial.webp' } });
    vi.spyOn(adapter, 'getStatus').mockResolvedValue({ success: true, data: asset });
    const uploaded = await client.callTool({ name: 'upload_asset', arguments: { file_path: '/fixture/output.png' } });
    expect(uploaded.structuredContent).toMatchObject({ asset_id: 42, ready: false });
    expect(uploaded.content).toEqual(expect.arrayContaining([expect.objectContaining({ text: expect.stringContaining('Save the asset ID') })]));
    const status = await client.callTool({ name: 'get_asset_status', arguments: { asset_id: '42' } });
    expect(status.structuredContent).toMatchObject({ ready: true, cdn_url: asset.cdn_url });
  });
  it('rejects ambiguous file sources and invalid IDs/batches before invoking the adapter', async () => {
    const { adapter, client } = await connected(); const upload = vi.spyOn(adapter, 'uploadFile'); const bulk = vi.spyOn(adapter, 'bulkDeleteAssets');
    expect((await client.callTool({ name: 'upload_asset', arguments: { file_path: '/a', file_url: 'https://example.com/a' } })).isError).toBe(true);
    expect((await client.callTool({ name: 'get_asset_status', arguments: { asset_id: '42tail' } })).isError).toBe(true);
    expect((await client.callTool({ name: 'bulk_delete_assets', arguments: { asset_ids: [] } })).isError).toBe(true);
    expect((await client.callTool({ name: 'generate_private_url', arguments: { asset_id: 42, expires_in: 60.5 } })).isError).toBe(true);
    expect(upload).not.toHaveBeenCalled(); expect(bulk).not.toHaveBeenCalled();
  });
  it('preserves the asset ID on wait timeout and mixed deletion outcomes', async () => {
    const { adapter, client } = await connected();
    vi.spyOn(adapter, 'waitUntilReady').mockRejectedValue(new KompressrError('Resume with the saved ID.', { kind: 'timeout', code: 'WAIT_TIMEOUT', assetId: 42 }));
    const waited = await client.callTool({ name: 'wait_for_asset', arguments: { asset_id: 42, timeout_ms: 10 } });
    expect(waited.isError).toBe(true); expect(waited.structuredContent).toMatchObject({ code: 'WAIT_TIMEOUT', assetId: 42 });
    vi.spyOn(adapter, 'bulkDeleteAssets').mockResolvedValue({ results: [{ id: 42, status: 403, accepted: false, error: 'Permission denied.' }], counts: { total: 1, accepted: 0, failed: 1 } });
    expect((await client.callTool({ name: 'bulk_delete_assets', arguments: { asset_ids: [42] } })).structuredContent).toMatchObject({ counts: { failed: 1 } });
  });
  it('returns pagination and private signing in structured results', async () => {
    const { adapter, client } = await connected();
    vi.spyOn(adapter, 'listAssets').mockResolvedValue({ success: true, data: [asset], total: 2, page: 1, limit: 1 });
    expect((await client.callTool({ name: 'list_assets', arguments: { limit: 1 } })).structuredContent).toMatchObject({ next_page: 2 });
    vi.spyOn(adapter, 'generatePrivateUrl').mockResolvedValue({ success: true, data: { asset_id: 42, private_url: 'https://cdn.example/private?s=fixture', variant: 'webp', expires_at: '2026-10-13T12:00:00Z', expires_in: 3600 } });
    expect((await client.callTool({ name: 'generate_private_url', arguments: { asset_id: 42 } })).structuredContent).toHaveProperty('private_url');
  });
  it('blocks setup tools from replacing a configured runtime and explains paid access without credentials', async () => {
    const { adapter, client } = await connected(); const register = vi.spyOn(adapter, 'register'); const verify = vi.spyOn(adapter, 'verifyEmail');
    expect((await client.callTool({ name: 'register', arguments: { email: 'user@example.com', password: 'long-password' } })).isError).toBe(true);
    expect((await client.callTool({ name: 'verify_email', arguments: { token: 'fixture' } })).isError).toBe(true);
    expect(register).not.toHaveBeenCalled(); expect(verify).not.toHaveBeenCalled();
    const fresh = await connected(false);
    const response = await fresh.client.callTool({ name: 'upload_asset', arguments: { file_path: '/fixture' } });
    expect(response.isError).toBe(true); expect(JSON.stringify(response)).toContain('100 image uploads');
  });
  it('does not expose an arbitrary thrown credential or private URL', async () => {
    const { adapter, client } = await connected(); vi.spyOn(adapter, 'getStatus').mockRejectedValue(new Error('secret-key https://private.example?s=secret'));
    const response = await client.callTool({ name: 'get_asset_status', arguments: { asset_id: 42 } });
    expect(response.isError).toBe(true); expect(JSON.stringify(response)).not.toContain('secret-key');
  });
});


it('stops SDK waiting when the MCP client cancels its request', async () => {
  const { adapter, client } = await connected();
  let signal: AbortSignal | undefined;
  let begin!: () => void, stop!: () => void;
  const started = new Promise<void>(resolve => { begin = resolve; });
  const stopped = new Promise<void>(resolve => { stop = resolve; });
  vi.spyOn(adapter, 'waitUntilReady').mockImplementation(async (_id, _timeout, requestSignal) => {
    signal = requestSignal; begin();
    return new Promise((_resolve, reject) => {
      signal?.addEventListener('abort', () => { stop(); reject(new KompressrError('Waiting cancelled.', { kind: 'cancelled', code: 'WAIT_CANCELLED', assetId: 42 })); }, { once: true });
    });
  });
  const controller = new AbortController();
  const call = client.callTool({ name: 'wait_for_asset', arguments: { asset_id: 42 } }, undefined, { signal: controller.signal });
  await started; expect(signal).toBeInstanceOf(AbortSignal); controller.abort();
  await expect(call).rejects.toThrow(); await stopped;
});


it('saves a newly verified credential without exposing the key and explains the shared trial', async () => {
  const { adapter, client } = await connected(false);
  vi.spyOn(adapter, 'verifyEmail').mockResolvedValue({ success: true, api_key: 'one-time-secret', project_id: '660e8400-e29b-41d4-a716-446655440001' });
  const response = await client.callTool({ name: 'verify_email', arguments: { token: 'fixture-token' } });
  expect(response.structuredContent).toMatchObject({ configured: true, verified: true });
  expect(saveConfig).toHaveBeenCalledWith(expect.objectContaining({ api_key: 'one-time-secret', upload_url: 'https://uploads.kompressr.com' }));
  expect(adapter.isConfigured()).toBe(true);
  expect(JSON.stringify(response)).toContain('100 image uploads'); expect(JSON.stringify(response)).not.toContain('one-time-secret');
});
it('allows only one in-flight verification to configure a runtime', async () => {
  const { adapter, client } = await connected(false);
  let begin!: () => void, finish!: (value: { success: boolean; api_key: string; project_id: string }) => void;
  const started = new Promise<void>(resolve => { begin = resolve; });
  const verify = vi.spyOn(adapter, 'verifyEmail').mockImplementation(() => { begin(); return new Promise(resolve => { finish = resolve; }); });
  const first = client.callTool({ name: 'verify_email', arguments: { token: 'first-token' } });
  await started;
  const second = await client.callTool({ name: 'verify_email', arguments: { token: 'second-token' } });
  expect(second.isError).toBe(true); expect(verify).toHaveBeenCalledTimes(1);
  finish({ success: true, api_key: 'fixture-issued', project_id: '660e8400-e29b-41d4-a716-446655440001' });
  expect((await first).structuredContent).toHaveProperty('configured', true); expect(saveConfig).toHaveBeenCalledTimes(1);
});
