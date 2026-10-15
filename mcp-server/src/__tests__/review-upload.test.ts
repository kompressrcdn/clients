import { afterEach, expect, it, vi } from 'vitest';
import { createServer as httpServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { access, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { KompressrClient as SDK } from '@kompressr/sdk';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { KompressrClient } from '../client.js';
import { createServer } from '../server.js';
import * as downloads from '../download.js';

const tracked = vi.hoisted(() => ({ directories: [] as string[] }));
vi.mock('node:fs/promises', async importOriginal => {
  const real = await importOriginal<typeof import('node:fs/promises')>();
  return { ...real, mkdtemp: async (...args: Parameters<typeof real.mkdtemp>) => {
    const result = await real.mkdtemp(...args);
    if (typeof result === 'string') tracked.directories.push(result);
    return result;
  } };
});
const cleanups: Array<() => Promise<unknown>> = [];
afterEach(async () => { vi.restoreAllMocks(); vi.unstubAllEnvs(); await Promise.all(cleanups.splice(0).map(fn => fn())); tracked.directories.length = 0; });
function deferred<T = void>() { let resolve!: (value: T) => void; return { promise: new Promise<T>(done => { resolve = done; }), resolve }; }
async function endpoint(handler: (request: IncomingMessage, response: ServerResponse) => void | Promise<void>) {
  const server = httpServer((request, response) => { Promise.resolve(handler(request, response)).catch(() => { response.destroy(); }); });
  await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  cleanups.push(() => new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }));
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No address');
  return `http://127.0.0.1:${address.port}`;
}
async function connected(origin: string) {
  const adapter = new KompressrClient(origin, 'fixture');
  const server = createServer(adapter), client = new Client({ name: 'review-test', version: '1.0.0' });
  const [a, b] = InMemoryTransport.createLinkedPair(); await server.connect(a); await client.connect(b);
  cleanups.push(() => client.close(), () => server.close()); return { adapter, client };
}
const accepted = { id: 42, status: 'pending' as const, visibility: 'public' as const, deletion_status: 'active' as const, original_name: 'fixture.png', original_size: 3, asset_type: 'image' };

it.each(['cancel', 'disconnect'])('does not upload after MCP %s during a pending remote download and cleans temporary files', async mode => {
  vi.stubEnv('KOMPRESSR_REMOTE_ALLOWED_HOSTS', '127.0.0.1');
  const began = deferred(), finished = deferred(); let sourceResponse!: ServerResponse; let uploads = 0;
  const source = await endpoint((_request, response) => { sourceResponse = response; response.write('partial-'); began.resolve(); });
  const api = await endpoint(async (request, response) => { for await (const chunk of request) { void chunk; } uploads++; response.end(JSON.stringify({ success: true, data: { ...accepted, asset_id: 42, id: undefined } })); });
  const { adapter, client } = await connected(api); const real = adapter.uploadFromUrl.bind(adapter);
  vi.spyOn(adapter, 'uploadFromUrl').mockImplementation(async (...args) => { try { return await real(...args); } finally { finished.resolve(); } });
  const controller = new AbortController();
  const call = client.callTool({ name: 'upload_asset', arguments: { file_url: `${source}/fixture.png` } }, undefined, { signal: controller.signal }).then(value => ({ value }), error => ({ error }));
  await began.promise;
  if (mode === 'cancel') controller.abort(); else await client.close();
  expect(await call).toHaveProperty('error'); sourceResponse.end('complete'); await finished.promise;
  expect(uploads).toBe(0);
  expect(tracked.directories.length).toBeGreaterThan(0);
  for (const directory of tracked.directories) await expect(access(directory)).rejects.toThrow();
});

it('checks cancellation at the completed-download handoff even if a source helper finishes after cancellation', async () => {
  const gate = deferred<{ path: string; cleanup: () => Promise<void> }>(), began = deferred(), finished = deferred();
  const cleanup = vi.fn().mockResolvedValue(undefined);
  vi.spyOn(downloads, 'downloadForUpload').mockImplementation(async () => { began.resolve(); return gate.promise; });
  const upload = vi.spyOn(SDK.prototype, 'uploadFile').mockResolvedValue(accepted);
  const { adapter, client } = await connected('https://kompressr.com'); const real = adapter.uploadFromUrl.bind(adapter);
  vi.spyOn(adapter, 'uploadFromUrl').mockImplementation(async (...args) => { try { return await real(...args); } finally { finished.resolve(); } });
  const controller = new AbortController();
  const call = client.callTool({ name: 'upload_asset', arguments: { file_url: 'https://source.example/fixture.png' } }, undefined, { signal: controller.signal }).catch(error => error);
  await began.promise; controller.abort(); await call;
  gate.resolve({ path: '/fixture/finished.png', cleanup }); await finished.promise;
  expect(upload).not.toHaveBeenCalled(); expect(cleanup).toHaveBeenCalledTimes(1);
});

it('displays a missing/blank upload filename without inventing server metadata', async () => {
  const { adapter, client } = await connected('https://kompressr.com');
  const { original_name: _name, ...fields } = accepted;
  vi.spyOn(adapter, 'listAssets').mockResolvedValue({ success: true, data: [{ ...fields, id: 42, status: 'processed', kompressd_size: 2, savings_percent: 33, can_generate_private_url: false }], page: 1, limit: 20, total: 1 });
  const response = await client.callTool({ name: 'list_assets', arguments: {} });
  expect(response.isError).toBeUndefined(); expect(JSON.stringify(response.content)).toContain('Unnamed file');
  expect((response.structuredContent?.data as Array<{ original_name?: string }>)[0].original_name).toBeUndefined();
});


it.each(['local', 'remote'])('MCP cancellation reaches an already-dispatched %s upload and preserves ambiguity', async kind => {
  vi.stubEnv('KOMPRESSR_REMOTE_ALLOWED_HOSTS', '127.0.0.1');
  const began = deferred(), finished = deferred(); let uploads = 0; let failure: unknown;
  const api = await endpoint(async (request, _response) => { for await (const chunk of request) { void chunk; } uploads++; began.resolve(); });
  const source = await endpoint((_request, response) => { response.end('fixture'); });
  const directory = await mkdtemp(join(tmpdir(), 'mcp-upload-fixture-')); const path = join(directory, 'fixture.png'); await writeFile(path, 'fixture');
  cleanups.push(() => rm(directory, { recursive: true, force: true }));
  const { adapter, client } = await connected(api);
  const method = kind === 'local' ? 'uploadFile' : 'uploadFromUrl'; const real = adapter[method].bind(adapter);
  vi.spyOn(adapter, method).mockImplementation(async (...args) => {
    try { return await real(...args); } catch (error) { failure = error; throw error; } finally { finished.resolve(); }
  });
  const controller = new AbortController();
  const call = client.callTool({ name: 'upload_asset', arguments: kind === 'local' ? { file_path: path } : { file_url: `${source}/fixture.png` } }, undefined, { signal: controller.signal }).catch(error => error);
  await began.promise; controller.abort(); await call; await finished.promise;
  expect(uploads).toBe(1); expect(failure).toMatchObject({ code: 'REQUEST_CANCELLED', mayHaveSucceeded: true });
  for (const candidate of tracked.directories.filter(value => value.includes('kompressr-download-'))) await expect(access(candidate)).rejects.toThrow();
});
