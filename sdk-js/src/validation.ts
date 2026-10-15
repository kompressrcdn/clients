import { invalid, invalidResponse } from './errors.js';
import type { AssetState, BulkDeletion, CustomerData, DeletionStatus, Page, PrivateUrl, ProjectUser, UploadAccepted, UploadAsset, UploadKey } from './types.js';

export function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) invalidResponse();
  return value as Record<string, unknown>;
}
export function string(value: unknown): string { if (typeof value !== 'string' || !value.trim()) invalidResponse(); return value; }
export function number(value: unknown, integer = false): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || (integer && !Number.isSafeInteger(value))) invalidResponse();
  return value;
}
export function assetId(value: number): number {
  if (!Number.isSafeInteger(value) || value < 1) invalid('Use a positive safe integer asset ID.');
  return value;
}
export function positive(value: number, label: string, maximum = 2_147_483_647): number {
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) invalid(`${label} must be a positive integer no greater than ${maximum}.`);
  return value;
}
export function uuid(value: string, label = 'ID'): string {
  if (typeof value !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) invalid(`${label} must be a UUID.`);
  return value;
}
export function customerData(value: CustomerData, maximumBytes = 4096): CustomerData {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length > 5) invalid('Customer data supports at most five scalar fields.');
  const output: CustomerData = Object.create(null);
  for (const [rawKey, val] of Object.entries(value)) {
    const key = rawKey.trim();
    if (!key || Buffer.byteLength(key) > 64 || Object.hasOwn(output, key)) invalid('Data keys must be unique, nonempty and at most 64 UTF-8 bytes.');
    if (typeof val === 'string' ? Buffer.byteLength(val) > 512 : val !== null && typeof val !== 'boolean' && !(typeof val === 'number' && Number.isFinite(val))) invalid('Data values must be finite scalar values; strings support at most 512 UTF-8 bytes.');
    output[key] = val;
  }
  if (Buffer.byteLength(JSON.stringify(output)) > maximumBytes) invalid(`Encoded customer data exceeds ${maximumBytes} bytes.`);
  return output;
}
const deletionStates = ['active', 'deleting', 'deleted', 'legacy_deleted'];
export function deletion(value: unknown): DeletionStatus {
  if (typeof value !== 'string' || !deletionStates.includes(value)) invalidResponse('Missing or invalid deletion status; verify server compatibility.');
  return value as DeletionStatus;
}
export function deletionFilter(value: DeletionStatus): string {
  if (!deletionStates.includes(value)) invalid('Invalid deletion filter.'); return value;
}
function optionalFields(source: Record<string, unknown>, names: string[]): void {
  for (const name of names) if (source[name] !== undefined && typeof source[name] !== 'string') invalidResponse();
}
function safeUrls(source: Record<string, unknown>): void {
  for (const key of ['cdn_url', 'cdn_url_avif', 'private_url']) {
    if (source[key] === undefined) continue;
    const value = string(source[key]);
    try { const parsed = new URL(value); if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password) invalidResponse(); }
    catch { invalidResponse('Invalid delivery URL.'); }
  }
}
export function upload(value: unknown, accepted: true): UploadAccepted;
export function upload(value: unknown, accepted?: false): Omit<UploadAccepted, 'original_name'> & { original_name?: string };
export function upload(value: unknown, accepted = false): Omit<UploadAccepted, 'original_name'> & { original_name?: string } {
  const v = record(value);
  const id = number(v[accepted ? 'asset_id' : 'id'], true);
  if (id < 1) invalidResponse();
  const status = string(v.status);
  if (!['pending', 'processing', 'processed', 'failed', 'unprocessable', 'unknown'].includes(status)) invalidResponse('Unknown processing status.');
  const visibility = string(v.visibility);
  if (visibility !== 'public' && visibility !== 'private') invalidResponse();
  const deletion_status = deletion(v.deletion_status);
  if (number(v.original_size, true) < 0) invalidResponse();
  if (accepted) string(v.original_name);
  else optionalFields(v, ['original_name']);
  string(v.asset_type);
  optionalFields(v, ['deletion_requested_at', 'external_id', 'created_at', 'input_format', 'output_format', 'private_url_expires_at']);
  safeUrls(v);
  if (visibility === 'private' && (v.cdn_url !== undefined || v.cdn_url_avif !== undefined)) invalidResponse('Private asset response contains a public URL.');
  if (deletion_status !== 'active' && (v.cdn_url !== undefined || v.cdn_url_avif !== undefined || v.private_url !== undefined)) invalidResponse('Deleted asset response contains a delivery URL.');
  if (v.data !== undefined) { try { customerData(v.data as CustomerData, 8192); } catch { invalidResponse('Invalid customer data response.'); } }
  if (v.options !== undefined && Object.values(record(v.options)).some(x => typeof x !== 'string')) invalidResponse();
  const { asset_id: _wireId, ...rest } = v;
  return { ...rest, id, status, visibility, deletion_status } as unknown as UploadAccepted;
}
export function uploadAsset(value: unknown): UploadAsset {
  const v = record(value), result = upload(v);
  if (number(v.kompressd_size, true) < 0 || typeof v.can_generate_private_url !== 'boolean') invalidResponse();
  number(v.savings_percent);
  return result as UploadAsset;
}
export function privateUrl(value: unknown): PrivateUrl {
  const v = record(value);
  if (number(v.asset_id, true) < 1 || !['webp', 'avif'].includes(string(v.variant))) invalidResponse();
  safeUrls(v); string(v.private_url); string(v.expires_at);
  if (number(v.expires_in, true) < 60 || (v.expires_in as number) > 604800) invalidResponse();
  return v as unknown as PrivateUrl;
}
export function assetState(value: unknown): AssetState {
  const v = record(value);
  if (number(v.id, true) < 1 || number(v.kind, true) < 1 || number(v.storage_credited_mb, true) < 0) invalidResponse();
  string(v.project_id); number(v.processing_status, true); deletion(v.deletion_status);
  if (!['upload', 'origin'].includes(string(v.source))) invalidResponse();
  optionalFields(v, ['deletion_requested_at']);
  if (v.accounting_status !== undefined && !['pending', 'settled', 'unavailable'].includes(string(v.accounting_status))) invalidResponse();
  if (v.last_failure !== undefined) { const f = record(v.last_failure); string(f.code); string(f.message); string(f.at); }
  return v as unknown as AssetState;
}
export function page<T>(value: unknown, parse: (row: unknown) => T, key = 'data'): Page<T> {
  const v = record(value);
  if (!Array.isArray(v[key]) || number(v.page, true) < 1 || number(v.limit, true) < 1 || number(v.total, true) < 0) invalidResponse();
  return { data: (v[key] as unknown[]).map(parse), page: v.page as number, limit: v.limit as number, total: v.total as number };
}
export function bulk(value: unknown, expected: number[]): BulkDeletion {
  const v = record(value), counts = record(v.counts);
  if (!Array.isArray(v.results) || v.results.length !== expected.length) invalidResponse();
  const results = v.results.map((row, index) => {
    const item = record(row);
    if (number(item.id, true) !== expected[index] || typeof item.accepted !== 'boolean') invalidResponse();
    number(item.status, true);
    if (item.accepted) {
      const state = assetState(item.state);
      if (![200, 202].includes(item.status as number) || state.id !== item.id || state.deletion_status === 'active') invalidResponse();
    } else { if ((item.status as number) < 400) invalidResponse(); string(item.error); }
    return item as unknown as BulkDeletion['results'][number];
  });
  const accepted = results.filter(x => x.accepted).length;
  if (counts.total !== results.length || counts.accepted !== accepted || counts.failed !== results.length - accepted) invalidResponse();
  return { results, counts: { total: results.length, accepted, failed: results.length - accepted } };
}
export function projectUser(value: unknown): ProjectUser {
  const v = record(value); string(v.id); string(v.project_id); string(v.customer_user_id);
  if ((v.display_name !== undefined && typeof v.display_name !== 'string') || !['active', 'suspended'].includes(string(v.status))) invalidResponse();
  for (const field of ['asset_count', 'storage_bytes', 'active_key_count', 'bandwidth_bytes_current_period', 'requests_current_period']) if (v[field] !== undefined && number(v[field], true) < 0) invalidResponse();
  if (v.metadata !== undefined) { try { customerData(v.metadata as CustomerData, 8192); } catch { invalidResponse('Invalid project user metadata.'); } }
  optionalFields(v, ['created_at', 'last_seen_at', 'last_upload_at', 'last_key_used_at']);
  return v as unknown as ProjectUser;
}
export function uploadKey(value: unknown): UploadKey {
  const v = record(value); for (const key of ['id', 'key_id', 'project_id', 'project_user_id', 'name']) string(v[key]);
  if (!Array.isArray(v.scopes) || v.scopes.some(x => !['upload', 'status', 'list', 'private_url', 'delete'].includes(x))) invalidResponse();
  if (!['public', 'private', 'both'].includes(string(v.allowed_visibility))) invalidResponse();
  return v as unknown as UploadKey;
}
