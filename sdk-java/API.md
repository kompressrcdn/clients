# Java API reference

`com.kompressr.KompressrClient`, `Options`, `Models`, `CancellationToken` and `KompressrException` form the public API. Responses are typed records with camel-case accessors; optional fields are null. Collection results are immutable. `UploadAccepted`, `UploadAsset`, `PrivateUrl` and `IssuedKey` deliberately exclude links/secrets from `toString()`.

## Configuration

`KompressrClient.builder(apiKey)` exposes `projectId(String)`, `apiBaseUrl(String)`, `uploadBaseUrl(String)`, `requestTimeout(Duration)`, `uploadTimeout(Duration)`, `maxReadRetries(int)` and `build()`. Default origins are `https://kompressr.com` and `https://uploads.kompressr.com`. A custom management origin becomes the upload origin unless explicitly overridden. Origins allow HTTP(S), with no credentials, path, query or fragment. Redirects are rejected.

Default management timeout: 30 seconds. Upload timeout: 10 minutes. GET retries: 2 (allowed 0–5). Durations use positive whole milliseconds, maximum 2147483647. Every HTTP method accepts a final `Options.Request(timeout, cancellation)` overload. Null options select defaults. Request timeout overrides the constructor deadline. Use `close()` or try-with-resources to release connections.

## File operations

| Method | Input | Result |
| --- | --- | --- |
| `uploadFile` | `Path`, optional `Options.Upload`, optional request | `UploadAccepted`; streams a readable regular file |
| `uploadBytes` | `byte[]`, filename, optional upload/request options | `UploadAccepted`; snapshots input bytes |
| `getUploadStatus` | Asset ID, optional request | `UploadAsset` |
| `waitUntilReady` | Asset ID, optional `Options.Wait` | Active processed `UploadAsset` |
| `generatePrivateUrl` | Asset ID, optional signing/request options | `PrivateUrl` |
| `listUploads` | Optional upload filters/request | `Page<UploadAsset>` |
| `iterateUploads` | Optional upload filters/request | Lazy `Iterable<UploadAsset>` |
| `listAssets` | Optional asset filters/request | `Page<AssetState>` |
| `getAsset` | Asset ID, optional request | `AssetState` |
| `deleteAsset` | Explicit asset ID, optional request | `AssetState` indicating deletion accepted/completed |
| `bulkDeleteAssets` | `List<Long>` of explicit IDs, optional request | `BulkDeletion` with every outcome |

Asset IDs are positive `long` values up to 9007199254740991, matching the shared contract. Project/user/key record IDs supplied to methods are UUID strings. Upload listing needs `projectId`; uploads and lifecycle operations do not.

`Options.Upload(visibility, quality, data, privateUrlExpiresIn)` accepts `public`/`private`, video quality `480p`/`720p`/`1080p`/`4k`, a map of up to five scalar data fields and optional initial private-link lifetime 60–604800 seconds. Metadata keys are trimmed, unique and 1–64 UTF-8 bytes; string values are limited to 512 bytes. Values may also be finite numbers, booleans or null. Encoded upload data is capped at 4096 bytes; platform metadata at 8192. Multipart options always precede the file.

`Options.Wait(timeout, pollInterval, cancellation)` defaults to two minutes and a two-second poll interval (maximum 30 seconds). It requires active deletion state. Processed public files need a CDN URL; processed private files need `canGeneratePrivateUrl=true`. Failed/unprocessable/unknown states produce `PROCESSING_FAILED`; deleting/deleted states produce `ASSET_DELETED`. Readiness does not automatically mint a private link.

`Options.Signing(expiresIn, variant)` defaults to 3600 seconds and `webp`; TTL is 60–604800 and variant is `webp` or `avif`. Availability, ownership and processing are enforced by the service.

`Options.UploadFilters(projectId, page, limit, visibility, status, externalId, data, deletionStatus)` supports status names `pending`, `processing`, `processed`, `failed`, `unprocessable`, or string numbers `1`–`6`; data filter values must be strings. `Options.AssetFilters(page, limit, deletionStatus)` supports lifecycle listing. Pagination defaults to page 1, limit 20, with maximum limit 100. Deletion states are `active`, `deleting`, `deleted`, `legacy_deleted`; omitted selects the server's active default. `externalId` supports up to 512 UTF-8 bytes. The iterator fetches each page on demand with its own finite request budget and stops if iteration stops. Offset pagination is not an immutable snapshot under concurrent changes.

`AssetState` is a lifecycle record, without delivery metadata. `storageCreditedMb` reflects recorded physical-removal credit, not a billing guarantee. Bulk inputs allow 1–100 IDs including duplicates; expected output is deduplicated in first-seen order. HTTP 200 may contain failed items. Deletion acceptance does not certify cache removal; use asset detail to inspect progress. There is no implicit delete-by-URL or batch expansion.

## Platform operations

Use `client.platform()`. It shares the owning client's configuration, credential and lifecycle.

| Method | Input | Result |
| --- | --- | --- |
| `listUsers` | Optional `Options.Pagination`, request | `ProjectUserPage`, active counts and optional usage period |
| `createUser` | `Options.CreateUser(customerUserId, displayName, metadata)`, optional request | `PlatformClient.CreatedUser(created, projectUser)` |
| `updateUser` | User UUID, `Options.UpdateUser(displayName, metadata)`, optional request | `ProjectUser` |
| `suspendUser` / `reactivateUser` | User UUID, optional request | `ProjectUser` |
| `listUploadKeys` | User UUID, optional pagination/request | `Page<UploadKey>` |
| `createUploadKey` | User UUID, `Options.CreateKey`, optional request | `IssuedKey` |
| `rotateUploadKey` | User UUID, key-record UUID, optional request | `IssuedKey` |
| `revokeUploadKey` | User UUID, key-record UUID, optional request | `void` |

Stable `customerUserId` is 1–256 UTF-8 bytes after trimming; display name supports 120. Creating a user finds/creates the server identity by stable customer ID. Key creation is not idempotent.

`Options.CreateKey(name, scopes, allowedVisibility, allowedAssetTypes, expiresAt)` requires a 1–120-byte name. Omitted/null scopes use the non-destructive server defaults. An explicit empty list is rejected before any HTTP request; it does not create a key with no permissions. Nonempty explicit scopes replace defaults and may contain `upload`, `status`, `list`, `private_url`, `delete`. `allowedVisibility` accepts `public`, `private`, `both`; positive numeric asset types constrain formats, and an empty list permits all supported types. Optional expiry is a future ISO instant. `new Options.CreateKey(name)` selects server defaults.

Issued secrets are accessible through `apiKey()` once and may have optional key metadata. List responses have no raw secrets. Rotation invalidates the old key; revocation removes access. Suspension revokes the user's keys without deleting files; reactivation does not restore revoked keys. Applications authenticate users, persist customer mappings/asset IDs and securely retain keys. The API enforces project, identity and scope permissions.

## Failures and recovery

`KompressrException` has `kind()`, `code()`, nullable `status()`, `retryAfterMs()`, `assetId()`, and `mayHaveSucceeded()`. `details()` returns safe fields for diagnostics. Kinds are `validation`, `api`, `network`, `timeout`, `cancelled`, `invalid_response`, `processing`. Native file access can throw `IOException` before dispatch.

GET network failures and HTTP 429/502/503/504 retry with bounded exponential backoff and jitter. `Retry-After` delta seconds or HTTP date, then structured `retry_after`, are honored without shortening the delay; the overall request deadline wins. Other reads and all mutations are not automatically retried. No credentials follow redirects. Server error messages redact configured credentials, Bearer tokens, URLs and named secrets; untrusted gateway HTML is never returned in exceptions.

A pre-cancelled operation sends nothing and reports `mayHaveSucceeded=false`. Once dispatched, an interrupted write, malformed successful response, server failure or redirect is ambiguous. Single-asset mutations retain the requested ID. Malformed upload acceptance can recover only a positive safe `data.asset_id` from a parsed `success:true` envelope. Broken JSON cannot recover an ID; bulk errors never pick an arbitrary item. Save accepted IDs immediately, resume status checks after waiting errors, and inspect uncertain writes before retrying. `mayHaveSucceeded=false` is not a general guarantee that an entire business workflow can be replayed.

## Java-specific boundaries

Calls are synchronous and thread-safe. A shared, bounded pool permits up to 64 concurrent HTTP attempts across clients. An exhausted pool produces a network failure rather than an unbounded queue; eligible GET retries still obey their deadlines. Caller deadlines remain bounded even if JVM DNS/provider I/O ignores interruption; such background work retains a worker slot until it ends. Cancellation tokens may be shared across calls; Java thread interruption is also observed. Timeouts bound HTTP requests/body reads/retry waits; they do not roll back accepted work. File reading and validation before dispatch are local operations. Keep file contents stable during streaming and use regular local files. Arbitrary caller-provided `InputStream` is not accepted because its `read()` may block indefinitely and ignore cancellation; spool such sources to a regular file under your application's own source-read deadline. There is no Java equivalent of Node's Blob overload, separate async API or injectable HTTP adapter. Local fixture origins provide real transport testing. Platform administration is accessed through the owning client rather than a separate independently configured constructor.
