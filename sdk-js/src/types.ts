export type Visibility = 'public' | 'private';
export type VideoQuality = '480p' | '720p' | '1080p' | '4k';
export type DeletionStatus = 'active' | 'deleting' | 'deleted' | 'legacy_deleted';
export type ProcessingStatus = 'pending' | 'processing' | 'processed' | 'failed' | 'unprocessable' | 'unknown';
export type CustomerData = Record<string, string | number | boolean | null>;
export type Fetch = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
export interface ClientOptions {
  apiKey: string;
  projectId?: string;
  apiBaseUrl?: string;
  uploadBaseUrl?: string;
  requestTimeoutMs?: number;
  uploadTimeoutMs?: number;
  maxReadRetries?: number;
  fetch?: Fetch;
}
export interface RequestOptions { signal?: AbortSignal; timeoutMs?: number }
export interface UploadOptions extends RequestOptions {
  visibility?: Visibility;
  quality?: VideoQuality;
  data?: CustomerData;
  privateUrlExpiresIn?: number;
}
/** Acceptance is not readiness. Save id before waiting or returning a link. */
export interface UploadAccepted {
  id: number;
  status: ProcessingStatus;
  deletion_status: DeletionStatus;
  deletion_requested_at?: string;
  visibility: Visibility;
  original_name: string;
  original_size: number;
  asset_type: string;
  cdn_url?: string;
  cdn_url_avif?: string;
  private_url?: string;
  private_url_expires_at?: string;
  data?: CustomerData;
  external_id?: string;
  options?: Record<string, string>;
  quality?: VideoQuality;
  warning?: string;
}
export interface UploadAsset extends Omit<UploadAccepted, 'original_name'> {
  original_name?: string;
  kompressd_size: number;
  savings_percent: number;
  can_generate_private_url: boolean;
  input_format?: string;
  output_format?: string;
  created_at?: string;
}
export interface PrivateUrl {
  asset_id: number;
  variant: 'webp' | 'avif';
  private_url: string;
  expires_at: string;
  expires_in: number;
}
export interface Page<T> { data: T[]; page: number; limit: number; total: number }
export interface PageOptions extends RequestOptions { page?: number; limit?: number }
export interface UploadFilters extends PageOptions {
  projectId?: string;
  visibility?: Visibility;
  externalId?: string;
  data?: Record<string, string>;
  status?: Exclude<ProcessingStatus, 'unknown'> | number;
  deletionStatus?: DeletionStatus;
}
export interface AssetFilters extends PageOptions { deletionStatus?: DeletionStatus }
export interface AssetState {
  id: number;
  project_id: string;
  kind: number;
  source: 'upload' | 'origin';
  processing_status: number;
  deletion_status: DeletionStatus;
  deletion_requested_at?: string;
  storage_credited_mb: number;
  accounting_status?: 'pending' | 'settled' | 'unavailable';
  last_failure?: { code: string; message: string; at: string };
}
export interface BulkDeletion {
  results: Array<{ id: number; status: number; accepted: boolean; state?: AssetState; code?: string; error?: string }>;
  counts: { total: number; accepted: number; failed: number };
}
export interface WaitOptions extends RequestOptions { pollIntervalMs?: number }
export interface ProjectUser {
  id: string; project_id: string; customer_user_id: string; display_name?: string;
  status: 'active' | 'suspended'; metadata?: CustomerData;
  asset_count?: number; storage_bytes?: number; active_key_count?: number;
  bandwidth_bytes_current_period?: number; requests_current_period?: number;
  last_seen_at?: string; last_upload_at?: string; last_key_used_at?: string; created_at?: string;
}
export type UploadScope = 'upload' | 'status' | 'list' | 'private_url' | 'delete';
export interface UploadKey {
  id: string; key_id: string; project_id: string; project_user_id: string;
  name: string; scopes: UploadScope[]; allowed_visibility: Visibility | 'both';
  allowed_asset_types?: number[]; expires_at?: string | null; revoked_at?: string | null;
  last_used_at?: string | null; created_at?: string;
}
export interface CreateUserOptions { customerUserId: string; displayName?: string; metadata?: CustomerData }
export interface UpdateUserOptions { displayName?: string; metadata?: CustomerData }
export interface CreateKeyOptions {
  name: string; scopes?: UploadScope[]; allowedVisibility?: Visibility | 'both';
  allowedAssetTypes?: number[]; expiresAt?: string;
}
export interface IssuedKey { id: string; key_id: string; api_key: string; upload_key?: UploadKey }

export interface ProjectUserPage extends Page<ProjectUser> {
  project_active_count: number; org_active_count: number;
  usage_period?: { start: string; end: string };
}
