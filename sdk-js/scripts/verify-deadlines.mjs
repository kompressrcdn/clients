import assert from 'node:assert/strict';
import { getEventListeners } from 'node:events';
import { createServer } from 'node:http';
import { KompressrClient } from '@kompressr/sdk';

assert.equal(typeof global.gc, 'function', 'Run this consumer with --expose-gc.');
const requests = [];
const server = createServer((request, response) => {
  requests.push(`${request.method} ${request.url}`);
  if (request.url === '/api/upload/44/status') {
    response.end(JSON.stringify({ success: true, data: { id: 44, status: 'processed', deletion_status: 'active', visibility: 'public', original_size: 3, asset_type: 'image', kompressd_size: 2, savings_percent: 33, can_generate_private_url: false, cdn_url: 'https://cdn.example/ready.webp' } }));
    return;
  }
  if (request.url === '/api/upload/43/status') return; // Stall before headers.
  response.writeHead(request.method === 'DELETE' ? 202 : 200, { 'Content-Type': 'application/json' });
  response.write('{"success":true,"data":'); // Stall after headers.
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const files = new KompressrClient({ apiKey: 'fixture-deadline', apiBaseUrl: origin, maxReadRetries: 0 });
const parent = new AbortController();
const gc = setInterval(() => global.gc(), 10);
async function rejectsWithinDeadline(operation, expected) {
  let watchdog;
  try {
    await assert.rejects(Promise.race([
      operation,
      new Promise((_, reject) => { watchdog = setTimeout(() => reject(new Error('SDK operation exceeded its deadline.')), 3000); }),
    ]), expected);
  } finally { clearTimeout(watchdog); }
}
try {
  assert.equal((await files.waitUntilReady(44, { timeoutMs: 2000, signal: parent.signal })).id, 44);
  assert.equal(getEventListeners(parent.signal, 'abort').length, 0, 'Successful wait retained its parent listener.');
  for (let iteration = 0; iteration < 3; iteration++) {
    await rejectsWithinDeadline(files.waitUntilReady(42, { timeoutMs: 200 }), { code: 'WAIT_TIMEOUT', assetId: 42 });
    await rejectsWithinDeadline(files.waitUntilReady(42, { timeoutMs: 200, signal: parent.signal }), { code: 'WAIT_TIMEOUT', assetId: 42 });
    assert.equal(getEventListeners(parent.signal, 'abort').length, 0, 'Wait retained its parent listener.');
  }
  for (const id of [42, 43]) {
    await rejectsWithinDeadline(files.getUploadStatus(id, { timeoutMs: 200, signal: parent.signal }), { code: 'REQUEST_TIMEOUT', mayHaveSucceeded: false });
    assert.equal(getEventListeners(parent.signal, 'abort').length, 0, 'Request retained its parent listener.');
  }
  await rejectsWithinDeadline(files.deleteAsset(42, { timeoutMs: 200, signal: parent.signal }), { code: 'REQUEST_TIMEOUT', assetId: 42, mayHaveSucceeded: true });
  assert.equal(requests.filter(value => value.startsWith('DELETE ')).length, 1, 'A timed-out write was replayed.');
  assert.equal(getEventListeners(parent.signal, 'abort').length, 0);
  const cancelled = new AbortController();
  const cancel = setTimeout(() => cancelled.abort(), 200);
  try {
    await rejectsWithinDeadline(files.waitUntilReady(42, { timeoutMs: 5000, signal: cancelled.signal }), { code: 'WAIT_CANCELLED', assetId: 42 });
    assert.equal(getEventListeners(cancelled.signal, 'abort').length, 0);
  } finally { clearTimeout(cancel); }
  console.log('Installed SDK deadlines survive garbage collection: stalled headers/body, readiness, cancellation, write ambiguity and listener cleanup.');
} finally {
  clearInterval(gc);
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
}
