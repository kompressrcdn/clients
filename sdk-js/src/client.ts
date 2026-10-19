import { openAsBlob } from 'node:fs';
import { basename } from 'node:path';
import { types } from 'node:util';
import { KompressrError, invalid, invalidResponse } from './errors.js';
import { createDeadline, delay, Transport } from './transport.js';
import { assetId, assetState, bulk, customerData, deletionFilter, page, positive, privateUrl, record, upload, uploadAsset, uuid } from './validation.js';
import { PlatformClient } from './platform.js';
import type { AssetFilters, AssetState, BulkDeletion, ClientOptions, Page, RequestOptions, UploadAccepted, UploadAsset, UploadFilters, UploadOptions, WaitOptions } from './types.js';

export class KompressrClient {
  readonly platform: PlatformClient;
  readonly apiBaseUrl: string;
  readonly uploadBaseUrl: string;
  private readonly transport: Transport;
  private readonly projectId?: string;
  constructor(options: ClientOptions) {
    this.transport = new Transport(options); this.projectId = options.projectId;
    this.apiBaseUrl = this.transport.apiBaseUrl; this.uploadBaseUrl = this.transport.uploadBaseUrl;
    this.platform = new PlatformClient(options);
  }
  async uploadFile(path: string, options: UploadOptions = {}): Promise<UploadAccepted> {
    if (typeof path !== 'string' || !path.trim()) invalid('Supply a file path.');
    // Native file-backed Blob preserves multipart Content-Length and bounded reads.
    return this.uploadBlob(await openAsBlob(path), basename(path), options);
  }
  async uploadBytes(bytes: Uint8Array, filename: string, options: UploadOptions = {}): Promise<UploadAccepted> {
    if (!(bytes instanceof Uint8Array)) invalid('bytes must be a Uint8Array or Buffer.');
    // Blob takes the immutable snapshot; ordinary views need no intermediate copy.
    // Shared buffers need a compatibility copy because Node Blob does not accept them.
    const source = types.isSharedArrayBuffer(bytes.buffer) ? new Uint8Array(bytes) : new Uint8Array(bytes.buffer as ArrayBuffer, bytes.byteOffset, bytes.byteLength);
    return this.uploadBlob(new Blob([source]), filename, options);
  }
  async uploadBlob(blob: Blob, filename: string, options: UploadOptions = {}): Promise<UploadAccepted> {
    if (!(blob instanceof Blob) || typeof filename !== 'string' || !filename.trim() || /[\r\n\0]/.test(filename)) invalid('Supply a Blob and nonempty filename without control characters.');
    const form = new FormData();
    if (options.visibility !== undefined) {
      if (!['public', 'private'].includes(options.visibility)) invalid('visibility must be public or private.');
      form.append('visibility', options.visibility);
    }
    if (options.quality !== undefined) {
      if (!['480p', '720p', '1080p', '4k'].includes(options.quality)) invalid('Unsupported video quality.');
      form.append('kmp-quality', options.quality);
    }
    if (options.privateUrlExpiresIn !== undefined) {
      const ttl = positive(options.privateUrlExpiresIn, 'privateUrlExpiresIn', 604800);
      if (ttl < 60) invalid('Private URL lifetime must be at least 60 seconds.');
      form.append('private_url_expires_in', String(ttl));
    }
    if (options.data !== undefined) form.append('data', JSON.stringify(customerData(options.data)));
    form.append('file', blob, basename(filename)); // Server requires file last.
    return this.transport.mutate('/api/upload', { method: 'POST', body: form }, value => {
      const response = record(value);
      if (response.success !== true) invalidResponse();
      const result = upload(response.data, true);
      if (typeof response.warning === 'string') result.warning = response.warning;
      return result;
    }, options, { upload: true, recoverUploadId: true });
  }

  async getUploadStatus(id: number, options?: RequestOptions): Promise<UploadAsset> {
    const result = uploadAsset(await this.transport.data(`/api/upload/${assetId(id)}/status`, undefined, options));
    if (result.id !== id) invalidResponse('API returned a different asset ID.');
    return result;
  }
  async waitUntilReady(id: number, options: WaitOptions = {}): Promise<UploadAsset> {
    assetId(id);
    const timeout = positive(options.timeoutMs ?? 120_000, 'timeoutMs');
    const interval = positive(options.pollIntervalMs ?? 2_000, 'pollIntervalMs', 30_000);
    const deadline = createDeadline(timeout, options.signal);
    const { signal } = deadline;
    const stopped = () => new KompressrError(options.signal?.aborted ? 'Waiting cancelled; resume status checks with the saved asset ID.' : 'Waiting timed out; resume status checks with the saved asset ID.', {
      kind: options.signal?.aborted ? 'cancelled' : 'timeout', code: options.signal?.aborted ? 'WAIT_CANCELLED' : 'WAIT_TIMEOUT', assetId: id,
    });
    try {
      while (true) {
        signal.throwIfAborted();
        const result = await this.getUploadStatus(id, { signal });
        if (result.deletion_status !== 'active') throw new KompressrError('The asset is being deleted or has been deleted.', { kind: 'processing', code: 'ASSET_DELETED', assetId: id });
        if (result.status === 'processed') {
          if (result.visibility === 'public' && !result.cdn_url) invalidResponse('Processed public asset has no delivery URL.');
          if (result.visibility === 'private' && !result.can_generate_private_url) invalidResponse('Processed private asset cannot generate a delivery link.');
          return result;
        }
        if (result.status !== 'pending' && result.status !== 'processing') throw new KompressrError(`Asset processing ended with status ${result.status}.`, { kind: 'processing', code: 'PROCESSING_FAILED', assetId: id });
        await delay(Math.min(30_000, interval + Math.random() * Math.min(interval * 0.1, 250)), signal);
      }
    } catch (error) {
      if (signal.aborted) throw stopped();
      if (error instanceof KompressrError) throw new KompressrError(error.message, { ...error, assetId: id });
      throw error;
    } finally { deadline.dispose(); }
  }
  async generatePrivateUrl(id: number, options: RequestOptions & { expiresIn?: number; variant?: 'webp' | 'avif' } = {}) {
    const expires = positive(options.expiresIn ?? 3600, 'expiresIn', 604800);
    if (expires < 60 || !['webp', 'avif'].includes(options.variant ?? 'webp')) invalid('Use a supported variant and lifetime from 60 to 604800 seconds.');
    const requestedId = assetId(id);
    return this.transport.mutate(`/api/upload/${requestedId}/private-url`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expires_in: expires, variant: options.variant ?? 'webp' }),
    }, value => {
      const response = record(value);
      if (response.success !== true) invalidResponse();
      const result = privateUrl(response.data);
      if (result.asset_id !== id) invalidResponse('API returned a different asset ID.');
      return result;
    }, options, { assetId: requestedId });
  }

  async listUploads(options: UploadFilters = {}): Promise<Page<UploadAsset>> {
    const params = this.pagination(options);
    const project = options.projectId ?? this.projectId;
    if (!project) invalid('Upload listing requires projectId; uploads and asset management need only an API key.');
    params.set('project_id', uuid(project, 'projectId'));
    if (options.visibility !== undefined) { if (!['public', 'private'].includes(options.visibility)) invalid('Invalid visibility filter.'); params.set('visibility', options.visibility); }
    if (options.deletionStatus) params.set('deletion_status', deletionFilter(options.deletionStatus));
    if (options.status !== undefined) {
      const states = { pending: 1, processing: 2, processed: 3, failed: 4, unprocessable: 5 };
      const status = typeof options.status === 'number' ? options.status : states[options.status];
      if (!Number.isInteger(status) || status < 1 || status > 6) invalid('Invalid processing status filter.');
      params.set('status', String(status));
    }
    if (options.externalId !== undefined) { if (typeof options.externalId !== 'string' || Buffer.byteLength(options.externalId) > 512) invalid('Invalid externalId filter.'); params.set('external_id', options.externalId); }
    if (options.data) for (const [key, value] of Object.entries(customerData(options.data))) { if (typeof value !== 'string') invalid('Data filter values must be strings.'); params.set(`data.${key}`, value); }
    const result = record(await this.transport.request(`/api/uploads?${params}`, undefined, options));
    if (result.success !== true) invalidResponse();
    return page(result, uploadAsset);
  }
  async *iterateUploads(options: UploadFilters = {}): AsyncGenerator<UploadAsset> {
    let next = options.page ?? 1;
    while (true) {
      const result = await this.listUploads({ ...options, page: next });
      if (result.page !== next || result.data.length > result.limit) invalidResponse('Invalid pagination response.');
      for (const row of result.data) yield row;
      if (result.data.length === 0 || result.page * result.limit >= result.total) return;
      next++;
    }
  }
  async listAssets(options: AssetFilters = {}): Promise<Page<AssetState>> {
    const params = this.pagination(options);
    if (options.deletionStatus) params.set('deletion_status', deletionFilter(options.deletionStatus));
    return page(await this.transport.request(`/api/assets?${params}`, undefined, options), assetState);
  }
  async getAsset(id: number, options?: RequestOptions): Promise<AssetState> {
    const result = assetState(await this.transport.request(`/api/assets/${assetId(id)}`, undefined, options));
    if (result.id !== id) invalidResponse('API returned a different asset ID.');
    return result;
  }
  async deleteAsset(id: number, options?: RequestOptions): Promise<AssetState> {
    const requestedId = assetId(id);
    return this.transport.mutate(`/api/assets/${requestedId}`, { method: 'DELETE' }, value => {
      const result = assetState(value);
      if (result.id !== id || result.deletion_status === 'active') invalidResponse('Deletion was not accepted for the requested asset.');
      return result;
    }, options, { assetId: requestedId });
  }

  async bulkDeleteAssets(ids: number[], options?: RequestOptions): Promise<BulkDeletion> {
    if (!Array.isArray(ids) || ids.length < 1 || ids.length > 100) invalid('Select 1 to 100 explicit asset IDs.');
    ids.forEach(assetId);
    return this.transport.mutate('/api/assets/bulk-delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ asset_ids: ids }) }, value => bulk(value, [...new Set(ids)]), options);
  }
  private pagination(options: { page?: number; limit?: number }): URLSearchParams {
    return new URLSearchParams({ page: String(positive(options.page ?? 1, 'page')), limit: String(positive(options.limit ?? 20, 'limit', 100)) });
  }
}
