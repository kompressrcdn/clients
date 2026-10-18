import { invalid, invalidResponse } from './errors.js';
import { Transport } from './transport.js';
import { customerData, number, page, positive, projectUser, record, string, uploadKey, uuid } from './validation.js';
import type { ClientOptions, CreateKeyOptions, CreateUserOptions, IssuedKey, PageOptions, ProjectUserPage, RequestOptions, UpdateUserOptions } from './types.js';

/** Identity/key administration. The API enforces project authority. */
export class PlatformClient {
  private readonly transport: Transport;
  constructor(options: ClientOptions) { this.transport = new Transport(options); }
  async listUsers(options: PageOptions = {}): Promise<ProjectUserPage> {
    const params = this.pagination(options);
    const response = this.success(await this.transport.request(`/api/platform/project-users?${params}`, undefined, options));
    const result = page(response, projectUser, 'project_users');
    const project_active_count = number(response.project_active_count, true), org_active_count = number(response.org_active_count, true);
    if (project_active_count < 0 || org_active_count < 0) invalidResponse();
    let usage_period: ProjectUserPage['usage_period'];
    if (response.usage_period !== undefined) {
      const period = record(response.usage_period);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(string(period.start)) || !/^\d{4}-\d{2}-\d{2}$/.test(string(period.end))) invalidResponse();
      usage_period = { start: period.start as string, end: period.end as string };
    }
    return { ...result, project_active_count, org_active_count, ...(usage_period ? { usage_period } : {}) };
  }
  async createUser(input: CreateUserOptions, options?: RequestOptions) {
    if (typeof input.customerUserId !== 'string' || !input.customerUserId.trim() || Buffer.byteLength(input.customerUserId.trim()) > 256) invalid('customerUserId must contain 1–256 UTF-8 bytes.');
    return this.write('/api/platform/project-users', 'POST', { customer_user_id: input.customerUserId, ...this.userFields(input) }, response => {
      if (typeof response.created !== 'boolean') invalidResponse();
      return { created: response.created, project_user: projectUser(response.project_user) };
    }, options);
  }
  async updateUser(id: string, input: UpdateUserOptions, options?: RequestOptions) {
    return this.write(this.path(id), 'PATCH', this.userFields(input), response => projectUser(response.project_user), options);
  }
  async suspendUser(id: string, options?: RequestOptions) { return this.mutateUser(id, 'suspend', options); }
  async reactivateUser(id: string, options?: RequestOptions) { return this.mutateUser(id, 'reactivate', options); }
  async listUploadKeys(id: string, options: PageOptions = {}) {
    return page(this.success(await this.transport.request(`${this.path(id)}/upload-keys?${this.pagination(options)}`, undefined, options)), uploadKey, 'upload_keys');
  }
  async createUploadKey(id: string, input: CreateKeyOptions, options?: RequestOptions): Promise<IssuedKey> {
    if (typeof input.name !== 'string' || !input.name.trim() || Buffer.byteLength(input.name.trim()) > 120) invalid('Key name must contain 1–120 UTF-8 bytes.');
    if (input.scopes !== undefined && (!Array.isArray(input.scopes) || input.scopes.length === 0 || input.scopes.some(x => !['upload', 'status', 'list', 'private_url', 'delete'].includes(x)))) invalid('scopes must contain at least one supported scope; omit scopes to use server defaults.');
    if (input.allowedVisibility !== undefined && !['public', 'private', 'both'].includes(input.allowedVisibility)) invalid('Invalid allowedVisibility.');
    if (input.allowedAssetTypes !== undefined && (!Array.isArray(input.allowedAssetTypes) || input.allowedAssetTypes.some(x => !Number.isInteger(x) || x < 1))) invalid('Asset types must be positive integers.');
    if (input.expiresAt !== undefined && (!Number.isFinite(Date.parse(input.expiresAt)) || Date.parse(input.expiresAt) <= Date.now())) invalid('expiresAt must be a future timestamp.');
    return this.write(`${this.path(id)}/upload-keys`, 'POST', { name: input.name, scopes: input.scopes, allowed_visibility: input.allowedVisibility, allowed_asset_types: input.allowedAssetTypes, expires_at: input.expiresAt }, response => this.issued(response), options);
  }
  async rotateUploadKey(id: string, keyId: string, options?: RequestOptions) {
    return this.write(`${this.path(id)}/upload-keys/${uuid(keyId, 'keyId')}/rotate`, 'POST', undefined, response => this.issued(response), options);
  }
  async revokeUploadKey(id: string, keyId: string, options?: RequestOptions): Promise<void> {
    await this.write(`${this.path(id)}/upload-keys/${uuid(keyId, 'keyId')}/revoke`, 'POST', undefined, () => undefined, options);
  }
  private path(id: string) { return `/api/platform/project-users/${uuid(id, 'projectUserId')}`; }
  private pagination(options: PageOptions) { return new URLSearchParams({ page: String(positive(options.page ?? 1, 'page')), limit: String(positive(options.limit ?? 20, 'limit', 100)) }); }
  private userFields(input: UpdateUserOptions) {
    if (input.displayName !== undefined && (typeof input.displayName !== 'string' || Buffer.byteLength(input.displayName.trim()) > 120)) invalid('displayName supports at most 120 UTF-8 bytes.');
    return { display_name: input.displayName, metadata: input.metadata === undefined ? undefined : customerData(input.metadata, 8192) };
  }
  private write<T>(path: string, method: string, body: unknown, parse: (response: Record<string, unknown>) => T, options?: RequestOptions) {
    return this.transport.mutate(path, { method, ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) }, response => parse(this.success(response)), options);
  }
  private success(value: unknown) { const v = record(value); if (v.success !== true) invalidResponse(); return v; }
  private issued(value: unknown): IssuedKey {
    const v = this.success(value); string(v.id); string(v.key_id); string(v.api_key);
    if (v.upload_key !== undefined) uploadKey(v.upload_key);
    return { id: v.id as string, key_id: v.key_id as string, api_key: v.api_key as string, ...(v.upload_key === undefined ? {} : { upload_key: v.upload_key as IssuedKey['upload_key'] }) };
  }
  private async mutateUser(id: string, action: string, options?: RequestOptions) {
    return this.write(`${this.path(id)}/${action}`, 'POST', undefined, response => projectUser(response.project_user), options);
  }
}
