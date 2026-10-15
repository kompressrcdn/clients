import { KompressrClient as SDK, KompressrError, resolveEndpoints } from '@kompressr/sdk';
import type { AssetState, BulkDeletion, CustomerData, DeletionStatus, UploadAsset, UploadOptions, VideoQuality } from '@kompressr/sdk';
import { downloadForUpload } from './download.js';

export type { UploadOptions, VideoQuality } from '@kompressr/sdk';
export type AssetVisibility = 'public' | 'private';
export type PrivateURLVariant = 'webp' | 'avif';
export type UploadData = CustomerData;
export interface ListAssetFilters {
  visibility?: AssetVisibility; externalId?: string; data?: Record<string, string>;
  page?: number; status?: 'pending' | 'processing' | 'processed' | 'failed' | 'unprocessable'; deletionStatus?: DeletionStatus;
}
export interface SignupResponse { success: boolean; message?: string; error?: string; code?: string }
export interface VerifyResponse extends SignupResponse { api_key?: string; project_id?: string }
export interface UploadResponse { success: boolean; data?: Omit<Awaited<ReturnType<SDK['uploadFile']>>, 'id'> & { asset_id: number }; error?: string; warning?: string }
export interface StatusResponse { success: boolean; data?: UploadAsset; error?: string }
export interface ListResponse { success: boolean; data?: UploadAsset[]; total?: number; page?: number; limit?: number; error?: string }
export interface PrivateURLResponse { success: boolean; data?: Awaited<ReturnType<SDK['generatePrivateUrl']>>; error?: string }

/** Compatibility adapter. Asset HTTP behavior lives in the public SDK. */
export class KompressrClient {
  private sdk?: SDK;
  private projectId?: string;
  readonly apiUrl: string;
  readonly uploadUrl: string;
  constructor(apiUrl = 'https://kompressr.com', apiKey?: string, projectId?: string, uploadUrl?: string) {
    const endpoints = resolveEndpoints({ apiBaseUrl: apiUrl, uploadBaseUrl: uploadUrl });
    this.apiUrl = endpoints.apiBaseUrl; this.uploadUrl = endpoints.uploadBaseUrl;
    if (apiKey) this.setCredentials(apiKey, projectId);
  }
  isConfigured() { return !!this.sdk; }
  setCredentials(apiKey: string, projectId?: string): void {
    this.projectId = projectId;
    this.sdk = new SDK({ apiKey, projectId, apiBaseUrl: this.apiUrl, uploadBaseUrl: this.uploadUrl });
  }
  async register(email: string, password: string): Promise<SignupResponse> {
    return this.account('/api/v1/signup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password, password_confirm: password }) });
  }
  async verifyEmail(token: string): Promise<VerifyResponse> {
    return this.account(`/api/v1/verify-email?token=${encodeURIComponent(token)}&issue_key=true`);
  }
  async uploadFile(path: string, optionsOrQuality?: UploadOptions | VideoQuality): Promise<UploadResponse> {
    const options = this.options(optionsOrQuality);
    this.checkUploadCancellation(options.signal);
    return this.accepted(await this.requireSDK().uploadFile(path, options));
  }
  async uploadFromUrl(url: string, optionsOrQuality?: UploadOptions | VideoQuality): Promise<UploadResponse> {
    const sdk = this.requireSDK();
    const options = this.options(optionsOrQuality);
    this.checkUploadCancellation(options.signal);
    const download = await downloadForUpload(url, options.signal);
    try {
      this.checkUploadCancellation(options.signal);
      return this.accepted(await sdk.uploadFile(download.path, options));
    }
    finally { await download.cleanup(); }
  }
  async getStatus(id: string | number): Promise<StatusResponse> { return { success: true, data: await this.requireSDK().getUploadStatus(this.id(id)) }; }
  async waitUntilReady(id: string | number, timeoutMs = 120_000, signal?: AbortSignal): Promise<StatusResponse> { return { success: true, data: await this.requireSDK().waitUntilReady(this.id(id), { timeoutMs, signal }) }; }
  async listAssets(limit = 20, filters: ListAssetFilters = {}): Promise<ListResponse> {
    if (!this.projectId) throw new KompressrError('Set KOMPRESSR_PROJECT_ID to list uploads; other file operations need only the API key.', { kind: 'validation', code: 'PROJECT_ID_REQUIRED' });
    return { success: true, ...await this.requireSDK().listUploads({ ...filters, limit }) };
  }
  async generatePrivateUrl(id: string | number, expiresIn = 3600, variant: PrivateURLVariant = 'webp'): Promise<PrivateURLResponse> {
    return { success: true, data: await this.requireSDK().generatePrivateUrl(this.id(id), { expiresIn, variant }) };
  }
  getAssetDeletionStatus(id: string | number): Promise<AssetState> { return this.requireSDK().getAsset(this.id(id)); }
  deleteAsset(id: string | number): Promise<AssetState> { return this.requireSDK().deleteAsset(this.id(id)); }
  bulkDeleteAssets(ids: number[]): Promise<BulkDeletion> { return this.requireSDK().bulkDeleteAssets(ids); }
  private checkUploadCancellation(signal?: AbortSignal): void {
    if (signal?.aborted) throw new KompressrError('Upload cancelled before it was sent.', { kind: 'cancelled', code: 'REQUEST_CANCELLED' });
  }
  private requireSDK(): SDK {
    if (!this.sdk) throw new KompressrError('Configure KOMPRESSR_API_KEY or set up a Kompressr account first.', { kind: 'validation', code: 'NOT_CONFIGURED' });
    return this.sdk;
  }
  private id(value: string | number): number {
    if (typeof value === 'string' && !/^[1-9]\d*$/.test(value)) throw new KompressrError('Use a positive numeric asset ID.', { kind: 'validation', code: 'INVALID_ARGUMENT' });
    return Number(value);
  }
  private options(value?: UploadOptions | VideoQuality): UploadOptions { return typeof value === 'string' ? { quality: value } : value ?? {}; }
  private accepted(value: Awaited<ReturnType<SDK['uploadFile']>>): UploadResponse {
    const { id, warning, ...data } = value;
    return { success: true, data: { ...data, asset_id: id }, ...(warning ? { warning } : {}) };
  }
  private async account(path: string, options: RequestInit = {}): Promise<VerifyResponse> {
    let response: Response;
    try { response = await fetch(`${this.apiUrl}${path}`, { ...options, redirect: 'error', signal: AbortSignal.timeout(30_000) }); }
    catch { throw new KompressrError('Account request failed; check your connection and API address.', { kind: 'network', code: 'ACCOUNT_REQUEST_FAILED' }); }
    let value: unknown;
    try { value = await response.json(); } catch { throw new KompressrError(`Account API returned a non-JSON response (HTTP ${response.status}).`, { kind: 'invalid_response', code: 'INVALID_RESPONSE', status: response.status }); }
    if (!value || typeof value !== 'object' || Array.isArray(value) || typeof (value as VerifyResponse).success !== 'boolean') throw new KompressrError('Invalid account response.', { kind: 'invalid_response', code: 'INVALID_RESPONSE' });
    const result = value as VerifyResponse;
    if (response.status < 200 || response.status >= 300) return { success: false, error: 'Account request was rejected. Check your input or sign in at Kompressr.', code: result.code };
    return result;
  }
}
