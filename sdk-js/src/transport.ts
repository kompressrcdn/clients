import { KompressrError, invalid, invalidResponse, safeMessage } from './errors.js';
import { positive, record } from './validation.js';
import type { ClientOptions, RequestOptions } from './types.js';

export const ENDPOINTS = {
  production: { apiBaseUrl: 'https://kompressr.com', uploadBaseUrl: 'https://uploads.kompressr.com' },
} as const;
export function baseUrl(value: string): string {
  let url: URL;
  try { url = new URL(value); } catch { invalid('Base URL must be an absolute HTTP(S) origin.'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/') invalid('Base URL must be an HTTP(S) origin without credentials, path, query or fragment.');
  return url.origin;
}
export function resolveEndpoints(options: Pick<ClientOptions, 'apiBaseUrl' | 'uploadBaseUrl'> = {}) {
  if ('environment' in options) invalid('Use explicit apiBaseUrl and uploadBaseUrl options for custom endpoints.');
  const apiBaseUrl = baseUrl(options.apiBaseUrl ?? ENDPOINTS.production.apiBaseUrl);
  const known = Object.values(ENDPOINTS).find(x => x.apiBaseUrl === apiBaseUrl);
  const uploadBaseUrl = baseUrl(options.uploadBaseUrl ?? known?.uploadBaseUrl ?? apiBaseUrl);
  return { apiBaseUrl, uploadBaseUrl };
}
export function createDeadline(timeoutMs: number, parent?: AbortSignal) {
  // Retain the timer explicitly: composed timeout signals can be collected on
  // older supported Node versions before an in-flight request has finished.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException('The operation was aborted due to timeout', 'TimeoutError')), timeoutMs);
  timer.unref();
  const abort = () => controller.abort(parent?.reason);
  if (parent?.aborted) abort();
  else parent?.addEventListener('abort', abort, { once: true });
  return {
    signal: controller.signal,
    dispose() { clearTimeout(timer); parent?.removeEventListener('abort', abort); },
  };
}
export function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(signal.reason); return; }
    const done = () => { signal?.removeEventListener('abort', abort); resolve(); };
    const timer = setTimeout(done, ms);
    const abort = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); reject(signal?.reason); };
    signal?.addEventListener('abort', abort, { once: true });
  });
}
function retryDelay(response: Response, body: unknown): number | undefined {
  const header = response.headers.get('Retry-After');
  if (header !== null) {
    const seconds = Number(header);
    const milliseconds = header.trim() && Number.isFinite(seconds) && seconds >= 0 ? seconds * 1000 : Date.parse(header) - Date.now();
    if (Number.isFinite(milliseconds)) return Math.max(0, milliseconds);
  }
  if (body && typeof body === 'object' && !Array.isArray(body)) {
    const seconds = (body as Record<string, unknown>).retry_after;
    if (typeof seconds === 'number' && Number.isFinite(seconds) && seconds >= 0) return seconds * 1000;
  }
  return undefined;
}
async function jsonBody(response: Response, signal: AbortSignal): Promise<unknown> {
  // Management responses are small. Never buffer an arbitrary gateway page.
  const ceiling = 2 * 1024 * 1024;
  const reader = response.body?.getReader();
  let text = '';
  if (reader) {
    const decoder = new TextDecoder(); let size = 0;
    // Cancel the reader directly as well as fetch: some supported runtimes
    // lose fetch's abort forwarding after response headers and GC.
    const abort = () => { void reader.cancel(signal.reason).catch(() => {}); };
    if (signal.aborted) abort();
    else signal.addEventListener('abort', abort, { once: true });
    try {
      signal.throwIfAborted();
      while (true) {
        const chunk = await reader.read();
        signal.throwIfAborted();
        if (chunk.done) break;
        size += chunk.value.byteLength;
        if (size > ceiling) { await reader.cancel(); invalidResponse('API response exceeds the supported size.'); }
        text += decoder.decode(chunk.value, { stream: true });
      }
      text += decoder.decode();
    } finally { signal.removeEventListener('abort', abort); reader.releaseLock(); }
  } else {
    text = await response.text();
    if (Buffer.byteLength(text) > ceiling) invalidResponse('API response exceeds the supported size.');
  }
  try { return JSON.parse(text); } catch { invalidResponse(`API returned a non-JSON response (HTTP ${response.status}).`); }
}

export class Transport {
  readonly apiBaseUrl: string;
  readonly uploadBaseUrl: string;
  readonly #key: string;
  private readonly fetch: NonNullable<ClientOptions['fetch']>;
  private readonly requestTimeout: number;
  private readonly uploadTimeout: number;
  private readonly retries: number;
  constructor(options: ClientOptions) {
    if (typeof options.apiKey !== 'string' || !options.apiKey.trim() || /[\r\n]/.test(options.apiKey)) invalid('Supply a nonempty API key on your trusted backend.');
    this.#key = options.apiKey;
    const endpoints = resolveEndpoints(options); this.apiBaseUrl = endpoints.apiBaseUrl; this.uploadBaseUrl = endpoints.uploadBaseUrl;
    this.fetch = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
    this.requestTimeout = positive(options.requestTimeoutMs ?? 30_000, 'requestTimeoutMs');
    this.uploadTimeout = positive(options.uploadTimeoutMs ?? 600_000, 'uploadTimeoutMs');
    this.retries = options.maxReadRetries ?? 2;
    if (!Number.isInteger(this.retries) || this.retries < 0 || this.retries > 5) invalid('maxReadRetries must be an integer from 0 to 5.');
  }
  /** Validate every mutation before leaving the request/ambiguity boundary. */
  async mutate<T>(path: string, init: RequestInit, parse: (body: unknown) => T, options: RequestOptions = {}, context: { upload?: boolean; assetId?: number; recoverUploadId?: boolean } = {}): Promise<T> {
    if (!init.method || !['POST', 'PUT', 'PATCH', 'DELETE'].includes(init.method)) invalid('A mutation must use a write method.');
    return this.request(path, init, options, context.upload, { parse, ...context });
  }
  async request<T = unknown>(path: string, init: RequestInit = {}, options: RequestOptions = {}, upload = false, validation?: { parse: (body: unknown) => T; assetId?: number; recoverUploadId?: boolean }): Promise<T> {
    const method = init.method ?? 'GET';
    const canRetry = method === 'GET';
    const timeout = positive(options.timeoutMs ?? (upload ? this.uploadTimeout : this.requestTimeout), 'timeoutMs');
    const headers = new Headers(init.headers); headers.set('Authorization', `Bearer ${this.#key}`); headers.set('Accept', 'application/json');
    const deadline = createDeadline(timeout, options.signal);
    const { signal } = deadline;
    let dispatched = false;
    let responseStatus: number | undefined;
    let knownAssetId = validation?.assetId;
    const contextualError = (kind: 'timeout' | 'cancelled' | 'network') => new KompressrError(
      kind === 'timeout' ? 'Request timed out. A write may have succeeded; inspect its outcome before retrying.' : kind === 'cancelled' ? 'Request cancelled.' : 'Unable to reach Kompressr. Check the configured endpoint and connection.',
      { kind, code: kind === 'timeout' ? 'REQUEST_TIMEOUT' : kind === 'cancelled' ? 'REQUEST_CANCELLED' : 'NETWORK_ERROR', status: responseStatus, assetId: knownAssetId, mayHaveSucceeded: dispatched && !canRetry },
    );
    try {
      for (let attempt = 0; ; attempt++) {
        responseStatus = undefined;
        try {
          signal.throwIfAborted();
          dispatched = true;
          const response = await this.fetch(`${upload ? this.uploadBaseUrl : this.apiBaseUrl}${path}`, { ...init, headers, signal, redirect: 'error' });
          responseStatus = response.status;
          const ok = response.status >= 200 && response.status < 300;
          let body: unknown;
          try { body = await jsonBody(response, signal); }
          catch (error) {
            if (signal.aborted) throw error;
            if (ok || !(error instanceof KompressrError)) throw error;
            // Preserve HTTP failure information without publishing the response body.
            body = null;
          }
          if (validation?.recoverUploadId && ok && body && typeof body === 'object' && !Array.isArray(body)) {
            const envelope = body as Record<string, unknown>;
            const data = envelope.data;
            if (envelope.success === true && data && typeof data === 'object' && !Array.isArray(data)) {
              const id = (data as Record<string, unknown>).asset_id;
              if (typeof id === 'number' && Number.isSafeInteger(id) && id > 0) knownAssetId = id;
            }
          }
          const failedEnvelope = body !== null && typeof body === 'object' && (body as Record<string, unknown>).success === false;
          if (!ok || failedEnvelope) {
            const failure = body !== null && typeof body === 'object' && !Array.isArray(body) ? body as Record<string, unknown> : {};
            const wait = retryDelay(response, body);
            throw new KompressrError(safeMessage(failure.error ?? `Kompressr returned HTTP ${response.status}.`, this.#key), {
              kind: 'api', status: response.status,
              code: typeof failure.code === 'string' ? safeMessage(failure.code, this.#key) : 'API_ERROR',
              retryAfterMs: wait, assetId: knownAssetId, mayHaveSucceeded: !canRetry && (ok || response.status >= 500),
            });
          }
          if (validation) {
            try { return validation.parse(body); }
            catch (error) { if (error instanceof KompressrError) throw error; invalidResponse(); }
          }
          return body as T;
        } catch (error) {
          if (signal.aborted) throw contextualError(options.signal?.aborted ? 'cancelled' : 'timeout');
          let failure = error instanceof KompressrError ? error : contextualError('network');
          if (failure.kind === 'invalid_response') failure = new KompressrError(failure.message, {
            ...failure, status: responseStatus, assetId: knownAssetId ?? failure.assetId, mayHaveSucceeded: dispatched && !canRetry,
          });
          const transient = failure.kind === 'network' || (failure.kind === 'api' && failure.status !== undefined && [429, 502, 503, 504].includes(failure.status));
          if (!canRetry || !transient || attempt >= this.retries) throw failure;
          const backoff = Math.min(30_000, 250 * 2 ** attempt + Math.random() * 100);
          // Never shorten Retry-After. The request deadline bounds a long delay.
          try { await delay(Math.max(backoff, failure.retryAfterMs ?? 0), signal); }
          catch { throw contextualError(options.signal?.aborted ? 'cancelled' : 'timeout'); }
        }
      }
    } finally { deadline.dispose(); }
  }

  async data(path: string, init?: RequestInit, options?: RequestOptions, upload = false): Promise<unknown> {
    const response = record(await this.request(path, init, options, upload));
    if (response.success !== true || !Object.hasOwn(response, 'data')) invalidResponse();
    return response.data;
  }
}
