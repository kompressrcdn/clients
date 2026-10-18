# API reference

Import `Kompressr.Sdk`. All HTTP methods return `Task<T>` (or `Task` for revocation), and accept an optional final `CancellationToken`. Options use `init` properties. Returned models are typed classes; their default `ToString()` does not expose credentials or signed URLs.

## Client configuration

`new KompressrClient(ClientOptions)` exposes the file API and its `Platform` property. `new PlatformClient(ClientOptions)` exposes administration separately, with the same credential and transport rules.

| ClientOptions property | Default / meaning |
| --- | --- |
| `ApiKey` | Required project or scoped credential, supplied explicitly |
| `ProjectId` | Optional default UUID for upload listing |
| `ApiBaseUrl` | `https://kompressr.com`; absolute HTTP(S) origin only |
| `UploadBaseUrl` | `https://uploads.kompressr.com` for the production management origin; otherwise the custom management origin |
| `RequestTimeout` | 30 seconds, including response bodies and retry delays |
| `UploadTimeout` | 600 seconds |
| `MaxReadRetries` | 2; configurable from 0 through 5 |

`KompressrClient.ApiBaseUrl` and `.UploadBaseUrl` expose the resolved origins. Clients may be reused concurrently and need no disposal. Requests use fresh HTTP/1.1 connections, adding connection setup cost in exchange for explicit control of retries. Redirects, cookies, automatic authentication and transport reconnects are disabled. Normal OS proxy configuration is honored. A proxy or service can still have its own behavior outside the client.

`RequestOptions.Timeout` overrides the constructor deadline for one call. Durations are `TimeSpan` values containing positive whole milliseconds, at most 2,147,483,647 milliseconds. Cancellation before dispatch sends nothing. File opening and OS filesystem stalls are outside HTTP deadline guarantees; only trusted regular local files are supported as paths. The SDK does not accept arbitrary `Stream` implementations.

## File methods

| Method | Input | Return value |
| --- | --- | --- |
| `UploadFileAsync` | `string path`, `UploadOptions?` | `UploadAccepted`; bounded-memory multipart from a local file |
| `UploadBytesAsync` | `ReadOnlyMemory<byte> bytes`, `string filename`, `UploadOptions?` | `UploadAccepted`; snapshots bytes before dispatch |
| `GetUploadStatusAsync` | `long id`, `RequestOptions?` | `UploadAsset`; current processing and delivery state |
| `WaitUntilReadyAsync` | `long id`, `WaitOptions?` | Ready `UploadAsset`; preserves ID on failure |
| `GeneratePrivateUrlAsync` | `long id`, `PrivateUrlOptions?` | `PrivateUrl` with `.Url`, `.AssetId`, `.Variant`, `.ExpiresAt`, `.ExpiresIn` |
| `ListUploadsAsync` | `UploadFilters?` | `Page<UploadAsset>`; requires a project UUID in filters or client options |
| `IterateUploadsAsync` | `UploadFilters?` | `IAsyncEnumerable<UploadAsset>`; fetches pages lazily |
| `ListAssetsAsync` | `AssetFilters?` | `Page<AssetState>`; project inferred from the key |
| `GetAssetAsync` | `long id`, `RequestOptions?` | `AssetState`; lifecycle detail and storage credits |
| `DeleteAssetAsync` | `long id`, `RequestOptions?` | `AssetState`; deletion acceptance, not completed cleanup |
| `BulkDeleteAssetsAsync` | `IReadOnlyList<long> ids`, `RequestOptions?` | `BulkDeletion`; preserves every outcome |

Asset IDs are positive integers no greater than 9,007,199,254,740,991. Bulk deletion accepts 1–100 explicit IDs; duplicates count toward this input limit, then response validation follows first-seen unique IDs. Nothing automatically expands a deletion selection or repeats a write.

`UploadOptions` adds `Visibility` (`public` or `private`), `Quality` (`480p`, `720p`, `1080p`, `4k`), `PrivateUrlExpiresIn` (60–604800 seconds), and `Data` (`IReadOnlyDictionary<string, object?>`). Omitted values use server defaults. Data supports at most five string, finite number, boolean or null values. Keys are trimmed, unique after trimming and at most 64 UTF-8 bytes; string values support 512 bytes. Upload data's encoded JSON limit is 4096 bytes. Multipart fields always precede the file. Format and plan entitlement remain service decisions.

`UploadAccepted` includes `Id`, `Status`, `DeletionStatus`, `Visibility`, `OriginalName`, `OriginalSize`, `AssetType` and optional delivery/metadata fields. Its wire `asset_id` becomes `Id`. `UploadAsset` adds `KompressdSize`, `SavingsPercent` and `CanGeneratePrivateUrl`, plus optional format/timestamp fields. Historical status records can omit `OriginalName`. A public URL on a processing asset is not evidence of readiness. Private/deleted assets cannot expose public/usable delivery URLs in validated responses.

`WaitOptions.Timeout` defaults to 120 seconds for the entire wait; `PollInterval` defaults to 2 seconds, at most 30 seconds. Each status request also has the client's management deadline. A processed public asset needs a CDN URL; a private one must permit signing. Failed, unprocessable and unknown states raise `PROCESSING_FAILED`; nonactive deletion raises `ASSET_DELETED`. Resuming a wait checks the saved asset ID without uploading or signing again.

`PrivateUrlOptions.ExpiresIn` defaults to 3600 seconds (60–604800 allowed). `Variant` defaults to `webp`; `avif` requires service availability. Store or return `.Url` only to the intended caller.

## Pagination and lifecycle models

`PageOptions` has `Page` (default 1), `Limit` (default 20, maximum 100), and request timeout. `Page<T>` returns `Data`, `PageNumber`, `Limit` and `Total`.

`UploadFilters` adds `ProjectId`, `Visibility`, `ExternalId` (maximum 512 UTF-8 bytes), `Data` (up to five string filters), `DeletionStatus`, and `Status`. Status accepts `pending`, `processing`, `processed`, `failed`, `unprocessable`, or numeric filter strings `1` through `6`. `AssetFilters` adds only `DeletionStatus`. Deletion filters are `active` (server default), `deleting`, `deleted`, `legacy_deleted`.

Iteration starts at the selected page, validates the returned page and stops at exhaustion. Breaking or cancelling prevents subsequent page requests. Offset pagination does not promise a stable snapshot during concurrent changes.

`AssetState` includes `Id`, `ProjectId`, `Kind`, `Source`, numeric `ProcessingStatus`, `DeletionStatus`, `StorageCreditedMb`, and optional `DeletionRequestedAt`, `AccountingStatus`, `LastFailure`. It is a lifecycle record without upload URLs. List credits are zero; inspect detail for recorded cleanup credits.

`BulkDeletion.Results` contains `Id`, HTTP `Status`, `Accepted`, and optional `State`, `Code`, `Error`. `Counts` contains `Total`, `Accepted`, `Failed`. Acceptance does not certify cache removal or finished physical cleanup.

## Platform methods

All methods below use `client.Platform` or a standalone `PlatformClient`. Project/master authority is required; passing a scoped key does not elevate it.

| Method | Input before optional request options/token | Return |
| --- | --- | --- |
| `ListUsersAsync` | `PageOptions?` | `ProjectUserPage` |
| `CreateUserAsync` | `CreateUserOptions` | `CreatedUser` with `Created` and `ProjectUser` |
| `UpdateUserAsync` | user UUID, `UpdateUserOptions` | `ProjectUser` |
| `SuspendUserAsync` | user UUID | `ProjectUser`; revokes keys, retains files |
| `ReactivateUserAsync` | user UUID | `ProjectUser`; old keys remain revoked |
| `ListUploadKeysAsync` | user UUID, `PageOptions?` | `Page<UploadKey>`; no raw secrets |
| `CreateUploadKeyAsync` | user UUID, `CreateKeyOptions` | `IssuedKey`; one-time secret |
| `RotateUploadKeyAsync` | user UUID, key-record UUID | `IssuedKey`; optional key record |
| `RevokeUploadKeyAsync` | user UUID, key-record UUID | `Task`; success envelope required |

`CreateUserOptions.CustomerUserId` is required (1–256 UTF-8 bytes after trimming). `DisplayName` is optional (120 bytes); `Metadata` uses upload scalar/key limits with an 8192-byte encoded limit. `UpdateUserOptions` has the same optional display and metadata fields. Stable customer IDs allow the service to find or create the same application identity.

`CreateKeyOptions.Name` is required (1–120 UTF-8 bytes after trimming). Optional `Scopes` replaces server defaults; supported values are `upload`, `status`, `list`, `private_url`, `delete`. Omitted or `null` scopes leave the field out of the request and use server defaults, which exclude deletion. An explicit empty collection raises `INVALID_ARGUMENT` before any HTTP request; it does not mean no permissions. Nonempty selections are sent exactly as supplied. `AllowedVisibility` is `public`, `private` or `both`; `AllowedAssetTypes` contains positive numeric types (empty means all supported); `ExpiresAt` is a future `DateTimeOffset`.

`ProjectUserPage` adds `ProjectActiveCount`, `OrgActiveCount` and optional `UsagePeriod`. `ProjectUser` includes identity, status, metadata and optional usage/activity fields. `UploadKey` includes its IDs, name, scopes, visibility, permitted types and optional expiry/revocation/activity timestamps. `IssuedKey.ApiKey` is secret authorization material. The client never persists or logs it; your application must securely store or deliver it before discarding the result.

## Error and recovery behavior

`KompressrException` exposes `Kind`, `Code`, optional `Status`, `RetryAfter` (`TimeSpan`), `AssetId` and `MayHaveSucceeded`. Kinds are `validation`, `api`, `network`, `timeout`, `cancelled`, `invalid_response`, `processing`.

Client codes include `INVALID_ARGUMENT`, `INVALID_RESPONSE`, `NETWORK_ERROR`, `REQUEST_TIMEOUT`, `REQUEST_CANCELLED`, `WAIT_TIMEOUT`, `WAIT_CANCELLED`, `PROCESSING_FAILED`, `ASSET_DELETED`. Safe machine-readable API codes are preserved. Error messages redact the supplied credential, bearer tokens, credential assignments and URLs; raw gateway pages and transport inner exceptions are omitted. Response bodies are bounded at 2 MiB. Native filesystem failures during preparation may remain .NET I/O exceptions.

Only GET network errors and HTTP 429/502/503/504 retry automatically, within the original deadline. `Retry-After` is never shortened. Invalid responses, permission denials and terminal processing failures are not transient reads. Underlying HTTP reconnects cannot dispatch an extra attempt.

A dispatched write interrupted by timeout/cancellation, a lost response, rejected redirect, server failure or malformed success can have succeeded. `MayHaveSucceeded` preserves that uncertainty. Validated single-asset mutation IDs survive errors; upload recovery accepts only a safe numeric `data.asset_id` inside a parsed `success: true` envelope. Broken JSON, unsafe IDs and bulk results never produce guessed recovery IDs. A false ambiguity flag is not a promise that repeating your whole application workflow is safe.
