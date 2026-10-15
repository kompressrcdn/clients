import { afterEach, expect, it } from 'vitest';
import { spawn } from 'node:child_process';
import { createServer, type ServerResponse } from 'node:http';
import { fileURLToPath } from 'node:url';

const cleanups: Array<() => Promise<unknown>> = [];
afterEach(async () => { await Promise.all(cleanups.splice(0).map(fn => fn())); });
async function endpoint(handler: Parameters<typeof createServer>[0]) {
  const server = createServer(handler); await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  cleanups.push(() => new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }));
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No address'); return `http://127.0.0.1:${address.port}`;
}
it('stdin EOF cancels an actual CLI download, closes its source connection and prevents a later upload', async () => {
  let started!: () => void, closed!: () => void, sourceResponse!: ServerResponse, uploads = 0;
  const began = new Promise<void>(resolve => { started = resolve; });
  const sourceClosed = new Promise<void>(resolve => { closed = resolve; });
  const source = await endpoint((_request, response) => { sourceResponse = response; response.once('close', closed); response.write('partial-'); started(); });
  const api = await endpoint(async (request, response) => {
    for await (const chunk of request) { void chunk; } uploads++;
    response.end(JSON.stringify({ success: true, data: { asset_id: 42, status: 'pending', deletion_status: 'active', visibility: 'public', original_name: 'fixture.png', original_size: 3, asset_type: 'image' } }));
  });
  const child = spawn(process.execPath, [fileURLToPath(new URL('../../dist/index.js', import.meta.url))], { env: { ...process.env, KOMPRESSR_API_KEY: 'fixture-eof', KOMPRESSR_PROJECT_ID: '660e8400-e29b-41d4-a716-446655440001', KOMPRESSR_API_URL: api, KOMPRESSR_UPLOAD_BASE_URL: api, KOMPRESSR_REMOTE_ALLOWED_HOSTS: '127.0.0.1' }, stdio: ['pipe', 'pipe', 'pipe'] });
  cleanups.push(async () => { if (child.exitCode === null && child.signalCode === null) { child.kill(); await new Promise(resolve => child.once('exit', resolve)); } });
  const exit = new Promise(resolve => child.once('exit', resolve));
  let initialized!: () => void; const ready = new Promise<void>(resolve => { initialized = resolve; });
  let pending = '', output = '';
  child.stdout.on('data', chunk => {
    output += chunk; pending += chunk;
    while (pending.includes('\n')) { const end = pending.indexOf('\n'); const line = pending.slice(0, end); pending = pending.slice(end + 1); const message = JSON.parse(line); if (message.id === 1 && message.result) initialized(); }
  });
  child.stderr.on('data', () => {});
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'eof-test', version: '1.0.0' } } }) + '\n');
  await ready;
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'upload_asset', arguments: { file_url: `${source}/fixture.png` } } }) + '\n');
  await began; child.stdin.end();
  let timer!: ReturnType<typeof setTimeout>;
  const aborted = await Promise.race([sourceClosed.then(() => true), new Promise<boolean>(resolve => { timer = setTimeout(() => resolve(false), 1000); })]);
  clearTimeout(timer); sourceResponse.end('complete'); await exit;
  expect(aborted).toBe(true); expect(uploads).toBe(0); expect(output).not.toContain('fixture-eof');
});
