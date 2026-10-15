import { lookup } from 'node:dns/promises';
import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { BlockList, isIP, type LookupFunction } from 'node:net';
import { mkdtemp, rm } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import { Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { KompressrError } from '@kompressr/sdk';

// Numeric CIDR membership handles compressed and expanded addresses identically.
// Restrict IPv6 to ordinary global unicast. Exclude IETF protocol allocations
// conservatively (including globally reachable special-use exceptions), transition
// and documentation ranges. Registry: https://www.iana.org/assignments/iana-ipv6-special-registry/
const globalIPv6 = new BlockList(); globalIPv6.addSubnet('2000::', 3, 'ipv6');
const excludedIPv6 = new BlockList();
for (const [address, prefix] of [['2001::', 23], ['2001:db8::', 32], ['2002::', 16], ['3fff::', 20]] as const) excludedIPv6.addSubnet(address, prefix, 'ipv6');
// Protocol assignments and TEST-NET-1 are distinct /24 blocks; ordinary
// public addresses elsewhere in 192.0.0.0/16 remain eligible.
const excludedIPv4 = new BlockList();
for (const [address, prefix] of [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['127.0.0.0', 8], ['224.0.0.0', 3],
  ['169.254.0.0', 16], ['172.16.0.0', 12], ['192.168.0.0', 16],
  ['100.64.0.0', 10], ['192.0.0.0', 24], ['192.0.2.0', 24], ['198.18.0.0', 15],
  ['198.51.100.0', 24], ['203.0.113.0', 24],
] as const) excludedIPv4.addSubnet(address, prefix, 'ipv4');
export function isPublicAddress(address: string): boolean {
  const family = isIP(address);
  if (family === 4) return !excludedIPv4.check(address, 'ipv4');
  if (family === 6) return globalIPv6.check(address, 'ipv6') && !excludedIPv6.check(address, 'ipv6');
  return false;
}
function rejected(message: string): never { throw new KompressrError(message, { kind: 'validation', code: 'REMOTE_SOURCE_REJECTED' }); }

export async function downloadForUpload(source: string, callerSignal?: AbortSignal) {
  const ceiling = 2 * 1024 * 1024 * 1024;
  const allowed = new Set((process.env.KOMPRESSR_REMOTE_ALLOWED_HOSTS ?? '').split(',').map(x => x.trim().toLowerCase()).filter(Boolean));
  const deadline = AbortSignal.timeout(300_000);
  const signal = callerSignal ? AbortSignal.any([callerSignal, deadline]) : deadline;
  const cancelled = () => new KompressrError('Remote download cancelled before the upload started.', { kind: 'cancelled', code: 'REQUEST_CANCELLED' });
  if (callerSignal?.aborted) throw cancelled();
  let current: URL;
  try { current = new URL(source); } catch { rejected('Supply an absolute HTTP(S) source URL.'); }
  let initialName: string;
  try { initialName = basename(decodeURIComponent(current.pathname)); } catch { rejected('Invalid source filename.'); }
  const directory = await mkdtemp(join(tmpdir(), 'kompressr-download-'));
  const cleanup = () => rm(directory, { recursive: true, force: true });
  try {
    for (let redirects = 0; redirects <= 5; redirects++) {
      signal.throwIfAborted();
      if (!['http:', 'https:'].includes(current.protocol) || current.username || current.password) rejected('Source URLs must use HTTP(S) without embedded credentials.');
      const hostname = current.hostname.replace(/^\[|\]$/g, '').toLowerCase();
      const trusted = allowed.has(hostname);
      if (isIP(hostname) && !trusted && !isPublicAddress(hostname)) rejected('Private/local source addresses require an explicit KOMPRESSR_REMOTE_ALLOWED_HOSTS entry.');
      const safeLookup: LookupFunction = (host, options, callback) => {
        lookup(host, { all: true }).then(addresses => {
          if (!addresses.length || (!trusted && addresses.some(x => !isPublicAddress(x.address)))) {
            callback(new Error('Source network policy rejected the address.'), '', 4); return;
          }
          // Connection uses the validated addresses; no second DNS lookup/rebinding.
          if (options.all) callback(null, addresses);
          else callback(null, addresses[0].address, addresses[0].family);
        }).catch(error => callback(error, '', 4));
      };
      const request = current.protocol === 'https:' ? httpsRequest : httpRequest;
      const response = await new Promise<import('node:http').IncomingMessage>((resolve, reject) => {
        const req = request(current, { signal, lookup: safeLookup }, resolve);
        req.once('error', reject); req.end();
      });
      if ([301, 302, 303, 307, 308].includes(response.statusCode ?? 0)) {
        const location = response.headers.location; response.destroy();
        if (!location || redirects === 5) rejected('Source exceeded the redirect limit.');
        const next = new URL(location, current);
        if (current.protocol === 'https:' && next.protocol !== 'https:') rejected('HTTPS source redirects must remain HTTPS.');
        current = next; continue;
      }
      if ((response.statusCode ?? 0) < 200 || (response.statusCode ?? 0) >= 300) { response.destroy(); rejected('Source download failed. Verify access to the source file.'); }
      if (Number(response.headers['content-length']) > ceiling) { response.destroy(); rejected('Remote file exceeds the 2 GiB transport ceiling.'); }
      const filename = (initialName || basename(decodeURIComponent(current.pathname)) || 'download').replace(/[\r\n\0]/g, '_');
      const path = join(directory, filename === '.' || filename === '..' ? 'download' : filename);
      let bytes = 0;
      const bounded = new Transform({ transform(chunk: Buffer, _encoding, callback) {
        bytes += chunk.length;
        if (bytes > ceiling) callback(new Error('Remote file exceeds the transport ceiling.'));
        else callback(null, chunk);
      } });
      await pipeline(response, bounded, createWriteStream(path, { flags: 'wx', mode: 0o600 }), { signal });
      signal.throwIfAborted();
      return { path, cleanup };
    }
    rejected('Source exceeded the redirect limit.');
  } catch (error) {
    await cleanup();
    if (callerSignal?.aborted) throw cancelled();
    if (error instanceof KompressrError) throw error;
    throw new KompressrError('Remote download failed or exceeded its time/size/network limits.', { kind: signal.aborted ? 'timeout' : 'network', code: 'REMOTE_DOWNLOAD_FAILED' });
  }
}
