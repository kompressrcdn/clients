# SDK API reference

This reference describes the `1.0.0` client. Import `KompressrClient`, `PlatformClient`, `KompressrError` and the exported TypeScript types from `@kompressr/sdk`. The package provides ESM and CommonJS entry points. All methods are asynchronous unless described otherwise.

## Constructor

`new KompressrClient(options: ClientOptions)`

| Option | Required/default | Meaning |
| --- | --- | --- |
| `apiKey: string` | Required | Project or scoped key; supplied explicitly, never persisted by SDK |
| `projectId: string` | Optional | Default project UUID for upload listing |
| `apiBaseUrl: string` | `https://kompressr.com` | HTTP(S) origin override; the production origin selects the production upload origin; custom origins use themselves unless uploadBaseUrl is provided |
| `uploadBaseUrl: string` | Derived upload origin | Explicit upload-body origin override |
| `requestTimeoutMs: number` | `30000` | Overall management request deadline, including retries/body reads |
| `uploadTimeoutMs: number` | `600000` | Overall upload request deadline |
| `maxReadRetries: number` | `2` | Integer 0–5; eligible GET retries only |
| `fetch: Fetch` | Native fetch | Injectable compatible fetch for testing/custom transports; must honor the signal |

Timeouts are positive integers no greater than 2147483647 milliseconds. `apiBaseUrl` and `uploadBaseUrl` are readable resolved properties. `platform` is the administration interface using the same credentials/transport. `resolveEndpoints(options)` and `ENDPOINTS` are also exported for configuration; resolving addresses performs no network requests. `ENDPOINTS` contains the public production pair. Other deployments explicitly supply both origins; the removed `environment` option is rejected at runtime.

`new PlatformClient(options: ClientOptions)` constructs an independent administration client. The API requires a project/master credential for platform calls; a scoped key remains unauthorized regardless of which class constructs it.

## Common options and data limits

`RequestOptions = { signal?: AbortSignal, timeoutMs?: number }` applies to every HTTP method. Per-call timeouts override the corresponding constructor deadline. Abort/cancellation never promises rollback of accepted server work.

`UploadOptions` adds:

| Option | Default | Meaning |
| --- | --- | --- |
| `visibility` | Server default `public` | `public` or `private` |
| `quality` | Server video default | `480p`, `720p`, `1080p`, `4k`; video only, subject to plan |
| `data` | Omitted | Up to five scalar strings, finite numbers, booleans or null |
| `privateUrlExpiresIn` | Server default 3600 | Integer 60–604800 seconds for the initial private URL |

Data keys are trimmed and must remain unique, nonempty and at most 64 UTF-8 bytes; string values support 512 UTF-8 bytes. Upload data's JSON encoding is limited to 4096 bytes because multipart field parsing is bounded. Platform metadata supports up to 8192 encoded bytes with the same scalar/key limits. The SDK always sends options before the file; callers do not construct multipart boundaries or headers.

Asset IDs are positive safe JS integers. Platform/project/key identifiers are UUID strings. Byte sizes and counters must be finite valid numbers. Unknown or malformed server shapes fail with `INVALID_RESPONSE`, rather than silently being treated as successful results.

## Upload and delivery methods

| Method | Arguments | Result and behavior |
| --- | --- | --- |
| `uploadFile(path, options?)` | Node file path, `UploadOptions` | `UploadAccepted`; file-backed multipart reads; filename comes from path |
| `uploadBytes(bytes, filename, options?)` | Uint8Array/Buffer, filename, `UploadOptions` | `UploadAccepted`; caller already holds bytes in memory; Blob snapshots the selected view once for ordinary buffers. Shared-backed views need a compatibility snapshot before Blob construction |
| `uploadBlob(blob, filename, options?)` | Blob, filename, `UploadOptions` | `UploadAccepted`; explicit filename; invalid/control-character names rejected |
| `getUploadStatus(id, options?)` | Numeric asset ID, `RequestOptions` | `UploadAsset`; server-reported current processing/deletion/delivery state |
| `waitUntilReady(id, options?)` | Numeric ID, `WaitOptions` | Active processed `UploadAsset`; fails on terminal/deleting state or deadline/cancellation |
| `generatePrivateUrl(id, options?)` | Numeric ID, `RequestOptions` plus `expiresIn?`, `variant?` | `PrivateUrl`; only processed private files; variant `webp` default or available `avif` |

Uploads require `upload`; status/waiting require `status`; signing requires `private_url` on a scoped key. Plan/project policy and identity ownership are enforced by the server. A filename does not establish format support or upload entitlement.

`WaitOptions` adds `pollIntervalMs` (default 2000, maximum 30000) and uses `timeoutMs` as the total waiting budget (default 120000). A stopped wait returns `WAIT_TIMEOUT`/`WAIT_CANCELLED` with `assetId`. Failed/unprocessable/unknown processing returns `PROCESSING_FAILED`; nonactive deletion returns `ASSET_DELETED`. A processed private result is ready to obtain a link; the helper does not mint one automatically.

`generatePrivateUrl` defaults to `expiresIn: 3600`, integer seconds between 60 and 604800. Requesting unavailable AVIF or an unprocessed/public file yields the server's error. It returns `{ asset_id, variant, private_url, expires_at, expires_in }`. Links are authorization material and should not enter routine logs.

### Upload result fields

`UploadAccepted` has required `id`, `status`, `deletion_status`, `visibility`, `original_name`, `original_size`, `asset_type`. Optional fields: `deletion_requested_at`, `cdn_url`, `cdn_url_avif`, `private_url`, `private_url_expires_at`, `data`, `external_id`, `options`, `quality`, `warning`. `id` is the normalized upload wire `asset_id`; the response envelope is removed.

`UploadAsset` makes `original_name` optional because existing status/list records may omit it (an empty string is also accepted), then adds `kompressd_size`, `savings_percent`, `can_generate_private_url` and optional `input_format`, `output_format`, `created_at`. Sizes are bytes; savings is the server's percentage, not a guaranteed bandwidth or cost reduction. Private assets have no public URL. Inactive/deleting assets have no usable delivery URL. A public URL can exist on a pending active asset; status determines readiness.

## Listing and lifecycle

| Method | Arguments | Result |
| --- | --- | --- |
| `listUploads(filters?)` | `UploadFilters` | `Page<UploadAsset>`; upload-only list, requires projectId |
| `iterateUploads(filters?)` | Same filters | Async generator of UploadAsset; sequential bounded page requests; stops when exhausted |
| `listAssets(filters?)` | `AssetFilters` | `Page<AssetState>`; all managed assets allowed by the key, project inferred |
| `getAsset(id, options?)` | Numeric ID, `RequestOptions` | AssetState with processing/deletion progress and recorded storage credits |
| `deleteAsset(id, options?)` | Explicit numeric ID, `RequestOptions` | AssetState; accepted deletion or already completed removal |
| `bulkDeleteAssets(ids, options?)` | Array of 1–100 explicit numeric IDs, `RequestOptions` | BulkDeletion with per-item success/failure and counts |

Both list options include `page` (default 1), `limit` (default 20, 1–100), request options and `deletionStatus`: `active` default, `deleting`, `deleted`, `legacy_deleted`. Upload filters also include `projectId`, `visibility`, `externalId`, `data` (up to five string filters), and `status` (`pending`, `processing`, `processed`, `failed`, `unprocessable`, or numeric 1–6). Status names are mapped to the server's numeric filter. The iterator starts at the selected page; each page has its own finite request budget. Cancelling/breaking stops subsequent page requests. Concurrent mutations can affect offset-based pagination; it is not an immutable export snapshot.

`Page<T> = { data: T[], page, limit, total }`. No automatic paging occurs in `listUploads`/`listAssets`.

`AssetState` has `id`, `project_id`, `kind`, `source` (`upload`/`origin`), numeric `processing_status`, `deletion_status`, `storage_credited_mb`; optional `deletion_requested_at`, `accounting_status` (`pending`/`settled`/`unavailable`), `last_failure: { code, message, at }`. This smaller lifecycle record does not supply upload metadata/URLs. List credits are zero; inspect detail. Processing and deletion states are independent.

Deletion requires project authority or opt-in scoped `delete`. List/detail use `list`/`status`. Deletion is permanent, background removal is asynchronous, caches may remain, and storage credits follow actual file removal. `getAsset` can inspect the old ID after a replacement reuses its URL. There is no delete-by-URL, restore, cancel or automatic batch expansion.

`BulkDeletion = { results: [{ id, status, accepted, state?, code?, error? }], counts: { total, accepted, failed } }`. Duplicate input IDs count toward 100, then the server deduplicates in first-seen order. Every item's result is retained even under HTTP 200. No automatic mutating retries; after an uncertain outcome, inspect/retry the same explicit IDs. Never infer that `counts.accepted` certifies cache removal.

## Platform methods

These methods use `client.platform` or a standalone `PlatformClient`. `RequestOptions` may be passed as the final argument. Use project/master credentials; server checks remain authoritative.

| Method | Input | Result |
| --- | --- | --- |
| `listUsers(options?)` | `PageOptions` | ProjectUserPage: page data, project_active_count, org_active_count, optional usage_period { start, end } (subscription date boundaries) |
| `createUser(input, options?)` | `customerUserId` (1–256 UTF-8 bytes), optional `displayName` (120 bytes), `metadata` | `{ created, project_user }`; server finds/creates by stable customer ID |
| `updateUser(id, input, options?)` | User UUID; optional displayName/metadata | ProjectUser |
| `suspendUser(id, options?)` | User UUID | ProjectUser; revokes keys without deleting files |
| `reactivateUser(id, options?)` | User UUID | ProjectUser; old revoked keys stay revoked |
| `listUploadKeys(id, options?)` | User UUID; PageOptions | Page<UploadKey>; contains no raw secrets |
| `createUploadKey(id, input, options?)` | User UUID; CreateKeyOptions | IssuedKey; one-time raw secret |
| `rotateUploadKey(id, keyId, options?)` | User UUID, key-record UUID | IssuedKey; one-time replacement secret; upload_key may be absent |
| `revokeUploadKey(id, keyId, options?)` | User UUID, key-record UUID | void on success |

`PageOptions` uses page/limit plus request options. `CreateKeyOptions`: required `name` (1–120 UTF-8 bytes), optional `scopes`, `allowedVisibility` (`public`, `private`, `both`), `allowedAssetTypes` (numeric server asset types; empty means all supported), future ISO `expiresAt`. Omitted scopes use the server's non-destructive defaults. An explicitly empty `scopes: []` raises `INVALID_ARGUMENT` before dispatch. If permission filtering leaves no scopes, do not issue a key. Nonempty explicit scopes replace defaults; allowed values are `upload`, `status`, `list`, `private_url`, `delete`. The SDK does not invent spending limits.

`ProjectUser` includes `id`, `project_id`, `customer_user_id`, `status` (`active`/`suspended`) and optional `display_name` (omitted when empty), `metadata`, usage counts, sizes and activity timestamps. `UploadKey` includes identity/project IDs, `key_id`, label, scopes, visibility, permitted types and optional expiry/revocation/activity timestamps. `IssuedKey` includes `{ id, key_id, api_key, upload_key? }`. Store or deliver `api_key` only to the intended runtime; it is not recoverable through list methods.

## Error contract

`KompressrError` extends Error; `toJSON()` returns its safe public fields. `kind` is `validation`, `api`, `network`, `timeout`, `cancelled`, `invalid_response`, or `processing`. `code` contains the server's code where supplied, or a client code such as `INVALID_ARGUMENT`, `INVALID_RESPONSE`, `NETWORK_ERROR`, `REQUEST_TIMEOUT`, `REQUEST_CANCELLED`, `WAIT_TIMEOUT`, `WAIT_CANCELLED`, `PROCESSING_FAILED`, `ASSET_DELETED`. Optional fields are HTTP `status`, `retryAfterMs`, `assetId`. `mayHaveSucceeded` is true when a dispatched write has an ambiguous outcome, including malformed JSON, incomplete/mismatched successful response data, interruption, or a server failure; false does not certify the safety of retrying an application-level workflow.

A request cancelled before dispatch reports `mayHaveSucceeded: false` and sends nothing. Cancellation after dispatch cannot undo accepted server work. Malformed write responses preserve HTTP status and the validated requested asset ID for single-asset operations; malformed upload acceptance can recover only a positive safe-integer `data.asset_id` from a successfully parsed `success: true` envelope. Broken JSON and unsafe IDs are never guessed; bulk errors do not choose an arbitrary single asset ID. One-time secrets from malformed key responses are never included in errors.

Only eligible GET network/429/502/503/504 failures automatically retry. Retry-After is respected within the deadline. Upload, sign, delete, provision, rotate and revoke are not automatically replayed. Readiness polling is separate from request retries. Native local-file errors can occur before any HTTP write; SDK validation uses KompressrError. Always handle request/deadline failures and keep the accepted ID in your application.
