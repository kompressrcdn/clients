# PHP API reference

All network methods are synchronous. Instantiate `Kompressr\Client` with an associative options array; `client->platform` provides administration. `Kompressr\PlatformClient` can also be constructed directly with the same configuration. Unknown response fields may be retained for compatibility. Treat returned values as sensitive application data.

## Configuration

| Option | Default | Meaning |
| --- | --- | --- |
| `apiKey` | required | Project or scoped credential; no whitespace/control characters |
| `projectId` | omitted | UUID used as the default for upload listing |
| `apiBaseUrl` | `https://kompressr.com` | Management HTTP(S) origin |
| `uploadBaseUrl` | `https://uploads.kompressr.com` | Upload body origin; a custom management origin is also used here unless overridden |
| `requestTimeoutMs` | `30000` | Total deadline for one read/write, including retries and body reads |
| `uploadTimeoutMs` | `600000` | Total upload deadline |
| `maxReadRetries` | `2` | Integer from 0 to 5 |

Origins reject credentials, paths, queries and fragments. HTTPS verifies certificates using cURL's configured CA trust. Configure development endpoints explicitly; there is no environment-name switch. cURL's standard proxy/CA environment configuration applies. Fresh HTTP/1.1 connections avoid implicit stale-connection or HTTP/2 mutation replay; redirects are disabled. This trades connection reuse for predictable write behavior.

A request options array accepts `timeoutMs` and `cancel` (a nonblocking `callable(): bool`). Durations are positive integer milliseconds, at most 2,147,483,647. Cancellation and deadlines apply to networking and retries, not arbitrary user code or stalled filesystem I/O. The client requires asynchronous DNS in libcurl.

## File methods

| Method | Additional options / return value |
| --- | --- |
| `uploadFile(string $path, array $options = []): array` | Streams a local regular file; returns upload acceptance |
| `uploadBytes(string $bytes, string $filename, array $options = []): array` | Uploads a PHP binary string; returns acceptance |
| `getUploadStatus($id, array $options = []): array` | Returns a validated upload asset |
| `waitUntilReady($id, array $options = []): array` | Returns a processed, deliverable upload asset; `timeoutMs` defaults to 120000 and `pollIntervalMs` to 2000 (maximum 30000) |
| `generatePrivateUrl($id, array $options = []): array` | `expiresIn` defaults to 3600 seconds (60–604800); `variant` is `webp` or `avif` |
| `listUploads(array $options = []): array` | Page of upload assets; requires a UUID `projectId` here or in configuration |
| `iterateUploads(array $options = []): Generator` | Lazily fetches and yields upload rows, validating page advancement |
| `listAssets(array $options = []): array` | Page of managed assets, including deletion state |
| `getAsset($id, array $options = []): array` | Managed asset state |
| `deleteAsset($id, array $options = []): array` | Deletion acceptance state; cleanup may still be running |
| `bulkDeleteAssets(array $ids, array $options = []): array` | 1–100 explicit IDs; returns accepted and failed items separately |

IDs must be PHP integers from 1 to 9,007,199,254,740,991; floats, numeric strings and booleans are rejected. Bulk results follow the first occurrence of each distinct requested ID. The SDK does not turn an HTTP 200 partial bulk result into all-success.

Upload options add `visibility` (`public` or `private`), `quality` (`480p`, `720p`, `1080p`, `4k`), `privateUrlExpiresIn` (60–604800 seconds), and `data` (customer metadata). Metadata precedes the file in multipart bodies. Filename directory components are removed and control characters rejected.

Customer metadata is an associative array or `stdClass` with at most five fields. Keys are trimmed, unique after trimming, and 1–64 UTF-8 bytes. Values are strings of at most 512 UTF-8 bytes, finite numbers, booleans or null. Encoded upload metadata is limited to 4096 bytes; project-user metadata and validated returned metadata use 8192 bytes. Empty metadata is sent as a JSON object. List data filters require string values.

List options add `page` (default 1), `limit` (default 20, maximum 100) and `deletionStatus` (`active`, `deleting`, `deleted`, `legacy_deleted`). Upload lists additionally support `projectId`, `visibility`, `status` (`pending`, `processing`, `processed`, `failed`, `unprocessable`, or integer 1–6), `externalId` (at most 512 UTF-8 bytes), and `data`. Iteration does not promise a stable snapshot while the inventory changes.

Waiting uses the shorter of the configured request deadline and remaining wait budget. A request deadline can therefore raise `REQUEST_TIMEOUT` before `WAIT_TIMEOUT`; both retain the asset ID. Cancellation does not stop server processing.

## Result shapes

Returned arrays retain API snake_case names, except upload acceptance normalizes wire `asset_id` to `id`. Fields marked `?` may be omitted; omission is different from a JSON null. Required numeric and boolean fields are validated without coercion.

```text
UploadAccepted = {
  id: int, status: pending|processing|processed|failed|unprocessable|unknown,
  deletion_status: active|deleting|deleted|legacy_deleted,
  visibility: public|private, original_name: string,
  original_size: int, asset_type: string,
  cdn_url?: string, cdn_url_avif?: string, private_url?: string,
  private_url_expires_at?: string, deletion_requested_at?: string,
  data?: object-like array, external_id?: string, options?: array<string,string>,
  quality?: string, warning?: string
}
UploadAsset = UploadAccepted with optional original_name, plus {
  kompressd_size: int, savings_percent: int|float,
  can_generate_private_url: bool, created_at?: string,
  input_format?: string, output_format?: string
}
PrivateUrl = {asset_id:int, variant:webp|avif, private_url:string,
              expires_at:string, expires_in:int}
Page = {data: list<row>, page:int, limit:int, total:int}
AssetState = {id:int, project_id:string, kind:int, source:upload|origin,
              processing_status:int, deletion_status:string,
              storage_credited_mb:int, deletion_requested_at?:string,
              accounting_status?:pending|settled|unavailable,
              last_failure?:{code:string,message:string,at:string}}
BulkDeletion = {results:list<{id:int,status:int,accepted:bool,
                             state?:AssetState,error?:string,code?:string}>,
                counts:{total:int,accepted:int,failed:int}}
```

Public readiness requires a delivery URL; private readiness requires permission to sign one. Private assets cannot contain public delivery URLs. Deleting/deleted upload records cannot contain delivery URLs. JSON responses are limited to 2 MiB; unknown or malformed statuses are rejected.

## Platform administration

All methods below are available on `$client->platform`. User IDs and key IDs in routes must be UUIDs. They use the project key supplied at construction; the SDK does not maintain a second credential or bypass service permissions.

| Method | Input and result |
| --- | --- |
| `listUsers(array $options = []): array` | Page options; returns user page with `project_active_count`, `org_active_count`, optional `usage_period` |
| `createUser(array $input, array $options = []): array` | Required `customerUserId` (1–256 trimmed UTF-8 bytes); optional `displayName`, `metadata`; returns `{created:bool,project_user:array}` |
| `updateUser($id, array $input, array $options = []): array` | Optional `displayName` (at most 120 trimmed UTF-8 bytes), `metadata`; returns project user |
| `suspendUser($id, array $options = []): array` | Returns suspended project user |
| `reactivateUser($id, array $options = []): array` | Returns active project user |
| `listUploadKeys($id, array $options = []): array` | Page options; returns upload-key page |
| `createUploadKey($id, array $input, array $options = []): IssuedKey` | Key options below; returns a one-time secret wrapper |
| `rotateUploadKey($id, $keyId, array $options = []): IssuedKey` | Returns replacement key secret |
| `revokeUploadKey($id, $keyId, array $options = []): void` | Revokes this key |

Key creation requires `name` (1–120 trimmed UTF-8 bytes). Optional fields: `scopes` (list containing `upload`, `status`, `list`, `private_url`, `delete`), `allowedVisibility` (`public`, `private`, `both`), `allowedAssetTypes` (list of positive integer type IDs), and `expiresAt` (future RFC 3339 timestamp). Omit scopes to use the service's non-destructive default; a nonempty list replaces that default. An explicit empty list or null is rejected before any HTTP request; an empty list does not create a key with no permissions. Suspending a user or revoking a key does not delete their files.

Project user rows contain `id`, `project_id`, `customer_user_id`, `status`, and optional `display_name`, `metadata`, usage counters (`asset_count`, `storage_bytes`, `active_key_count`, `bandwidth_bytes_current_period`, `requests_current_period`) and timestamps. Key rows contain `id`, `key_id`, `project_id`, `project_user_id`, `name`, `scopes`, `allowed_visibility`, and optional type restrictions and lifecycle timestamps.

`IssuedKey` exposes readonly `id`, `keyId`, and optional `uploadKey`. `revealApiKey(): string` returns the one-time credential. Its JSON/debug representation replaces that secret with `[redacted]`; serialization is prohibited. Store secrets explicitly in a secure application store.

## Error contract

`KompressrException` has `kind` (`validation`, `api`, `network`, `timeout`, `cancelled`, `invalid_response`, `processing`), `errorCode`, optional `status`, `retryAfterMs`, `assetId`, and boolean `mayHaveSucceeded`. Retry delays larger than PHP's integer range saturate to `PHP_INT_MAX` milliseconds before conversion; the request deadline still bounds the wait. API errors preserve safe service codes, status and retry hints; messages redact credentials and URLs. Raw cURL errors and response pages are not exposed. SDK exception traces retain call sites but omit arguments and object references, including on PHP 8.1; the SDK does not change process-wide exception settings.

A dispatched mutation that loses its response, receives malformed success data, or encounters an uncertain server/redirect response may have succeeded. Do not replay it automatically. Upload recovery IDs are accepted only from parsed `success:true` envelopes containing a valid numeric `data.asset_id`. Single-asset mutations retain the requested ID; bulk failures do not choose an arbitrary one.
