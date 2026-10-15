import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { downloadForUpload, isPublicAddress } from '../download.js';
const state = vi.hoisted(() => ({ addresses: new Map<string, Array<{address: string; family: number}>>(), connected: [] as string[], redirects: new Map<string,string>() }));
vi.mock('node:dns/promises', () => ({ lookup: vi.fn(async (host: string) => state.addresses.get(host) ?? []) }));
async function networkMock() {
  const { EventEmitter } = await import('node:events'); const { Readable } = await import('node:stream');
  return { request: vi.fn((url: URL, options: { lookup: Function; signal: AbortSignal }, callback: Function) => {
    const request = new EventEmitter() as InstanceType<typeof EventEmitter> & { end: () => void };
    request.end = () => { options.lookup(url.hostname, { all: true }, (error: Error | null, addresses: unknown) => {
      if (error) { request.emit('error', error); return; }
      state.connected.push(url.hostname);
      const redirect = state.redirects.get(url.hostname);
      const response = Readable.from(redirect ? [] : ['fixture']) as InstanceType<typeof Readable> & { statusCode: number; headers: Record<string, string> };
      response.statusCode = redirect ? 302 : 200; response.headers = redirect ? { location: redirect } : {};
      callback(response); void addresses;
    }); };
    return request;
  }) };
}
vi.mock('node:http', networkMock); vi.mock('node:https', networkMock);
beforeEach(() => { vi.stubEnv('KOMPRESSR_REMOTE_ALLOWED_HOSTS', ''); state.addresses.clear(); state.connected.length = 0; state.redirects.clear(); });
afterEach(() => vi.unstubAllEnvs());

it.each(['2001:2::1', '2001:0002:0000::1', '2001:2:0:ffff:ffff:ffff:ffff:ffff', '3fff::1', '3FFF:0fff:ffff:ffff:ffff:ffff:ffff:ffff', '2001::1', '2001:0000:ffff::1', '2001:1ff:ffff:ffff:ffff:ffff:ffff:ffff', '2002::1'])('blocks special/transition IPv6 %s', address => {
  expect(isPublicAddress(address)).toBe(false);
});
it.each(['2001:200::1', '2001:4860:4860::8888', '2606:4700:4700::1111', '3fff:1000::1', '2003::1'])('permits ordinary global IPv6 adjacent to exclusions: %s', address => {
  expect(isPublicAddress(address)).toBe(true);
});
it.each(['1fff:ffff:ffff:ffff:ffff:ffff:ffff:ffff', '4000::', 'fe80::1', 'fc00::1', '::ffff:8.8.8.8'])('rejects addresses outside the direct global-unicast policy: %s', address => {
  expect(isPublicAddress(address)).toBe(false);
});
it.each(['2001:2::1', '3fff::1', '2001::1'])('rejects a DNS result %s before a connection is permitted', async address => {
  state.addresses.set('source.example', [{ address, family: 6 }]);
  let rejected = false;
  try { const download = await downloadForUpload('https://source.example/fixture.png'); await download.cleanup(); } catch { rejected = true; }
  expect(rejected).toBe(true); expect(state.connected).toEqual([]);
});
it('rejects mixed public and non-global DNS results rather than choosing only the public one', async () => {
  state.addresses.set('source.example', [{ address: '2606:4700::1', family: 6 }, { address: '2001:2::1', family: 6 }]);
  let rejected = false;
  try { const download = await downloadForUpload('https://source.example/fixture.png'); await download.cleanup(); } catch { rejected = true; }
  expect(rejected).toBe(true); expect(state.connected).toEqual([]);
});
it('rechecks DNS at a redirect destination instead of inheriting the initial host decision', async () => {
  state.addresses.set('source.example', [{ address: '2606:4700::1', family: 6 }]);
  state.addresses.set('redirect.example', [{ address: '3fff::1', family: 6 }]);
  state.redirects.set('source.example', 'https://redirect.example/fixture.png');
  let rejected = false;
  try { const download = await downloadForUpload('https://source.example/fixture.png'); await download.cleanup(); } catch { rejected = true; }
  expect(rejected).toBe(true); expect(state.connected).toEqual(['source.example']);
});
it('retains explicit trusted-host exceptions for special-address sources', async () => {
  vi.stubEnv('KOMPRESSR_REMOTE_ALLOWED_HOSTS', 'source.example');
  state.addresses.set('source.example', [{ address: '2001:2::1', family: 6 }]);
  const download = await downloadForUpload('https://source.example/fixture.png'); await download.cleanup();
  expect(state.connected).toEqual(['source.example']);
});
