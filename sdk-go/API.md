# Go API reference

Import `github.com/kompressrcdn/clients/sdk-go` as `kompressr`. The client supports file operations and platform administration.

## Configuration

`New(Config) (*Client, error)` creates a reusable, concurrent client. `NewPlatform(Config)` creates a standalone administration client; `Client.Platform` shares the existing client's transport. Close idle resources with `CloseIdleConnections` when finished.

| Config field | Default | Meaning |
| --- | --- | --- |
| `APIKey string` | Required | Project or scoped credential; never persisted |
| `ProjectID string` | Omitted | Default project UUID, required only for upload listing |
| `APIBaseURL string` | `https://kompressr.com` | Management origin |
| `UploadBaseURL string` | `https://uploads.kompressr.com` | Upload origin; a custom API origin defaults uploads to itself |
| `RequestTimeout time.Duration` | 30 seconds | Total management request budget |
| `UploadTimeout time.Duration` | 10 minutes | Total upload request budget |
| `MaxReadRetries *int` | Nil means 2 | Pointer to 0 disables; range 0–5 |
| `HTTPTransport *http.Transport` | Standard transport | Cloned configuration for TLS, proxy and dialing; SDK owns redirect/replay policy |

`ResolveEndpoints(api, upload)` validates and resolves origins without making requests. `APIBaseURL()` and `UploadBaseURL()` return a client's resolved origins. Origins permit HTTP/HTTPS and must omit credentials, paths, queries and fragments.

Every HTTP method takes a non-nil context as its first parameter and a typed options value as its last. Use `RequestOptions{}` for defaults; its `Timeout` overrides the corresponding constructor deadline. The earlier of the context deadline and SDK deadline wins. Durations must be positive, at most 2147483647 milliseconds; zero means default. Sub-millisecond positive durations are allowed.

## Files

| Method | Arguments after context | Result |
| --- | --- | --- |
| `UploadFile` | path, `UploadOptions` | `UploadAccepted`; streams a regular file |
| `UploadBytes` | bytes, filename, `UploadOptions` | `UploadAccepted`; snapshots exactly the slice |
| `UploadReader` | `io.ReadCloser`, size, filename, `UploadOptions` | `UploadAccepted`; takes ownership and closes source |
| `GetUploadStatus` | asset ID, `RequestOptions` | `UploadAsset` |
| `WaitUntilReady` | asset ID, `WaitOptions` | Active processed `UploadAsset` |
| `GeneratePrivateURL` | asset ID, `PrivateURLOptions` | `PrivateURL` |
| `ListUploads` | `UploadFilters` | `Page[UploadAsset]` |
| `IterateUploads` | `UploadFilters` | Lazy `iter.Seq2[UploadAsset, error]` |
| `ListAssets` | `AssetFilters` | `Page[AssetState]` |
| `GetAsset` | asset ID, `RequestOptions` | `AssetState` |
| `DeleteAsset` | asset ID, `RequestOptions` | `AssetState`; deletion accepted, not necessarily completed |
| `BulkDeleteAssets` | 1–100 explicit IDs, `RequestOptions` | `BulkDeletion`; preserves all per-item results |

Except the iterator, each method returns `(result, error)`. IDs are `int64` restricted to positive JS-safe integers (maximum 9007199254740991), so all language SDKs target identical identifiers.

`UploadOptions` embeds `RequestOptions` and adds `Visibility` (`Public`/`Private`), `Quality` (`480p`/`720p`/`1080p`/`4k`), `Data CustomerData`, and `PrivateURLExpiresIn` (60–604800 seconds; zero omits). Defaults are server-selected public visibility, plan-dependent video quality and 3600 seconds for a private URL. Filenames must be nonempty, valid UTF-8 and contain no control characters. Multipart options precede the file.

`CustomerData` accepts up to five scalar strings, finite numbers, booleans or nil values. Trimmed keys must be unique and contain 1–64 UTF-8 bytes; string values support 512 bytes. JSON is capped at 4096 bytes for upload metadata and 8192 for platform metadata. Nested structures are rejected.

`UploadAccepted.ID` is normalized from wire `asset_id`. It includes processing/deletion state, visibility, original filename/size, type and optional delivery/metadata fields. `UploadAsset` embeds these and adds `KompressdSize`, `SavingsPercent`, `CanGeneratePrivateURL`, optional formats and creation time. Existing status/list records may omit the original name; the Go string is then empty. Private assets cannot contain public URLs, and inactive assets cannot contain delivery URLs.

`WaitOptions` contains `Timeout` (default two minutes) and `PollInterval` (default two seconds, maximum 30 seconds). Ready public assets require a public URL; ready private assets must support signing. Failed, unprocessable or unknown processing returns `PROCESSING_FAILED`; inactive deletion returns `ASSET_DELETED`. A stopped wait returns `WAIT_TIMEOUT`/`WAIT_CANCELLED` and retains the asset ID. It never signs or uploads automatically.

`PrivateURLOptions` embeds `RequestOptions`, with `ExpiresIn` (default 3600; 60–604800 seconds) and `Variant` (`webp` default or `avif`). `PrivateURL` contains `AssetID`, `Variant`, `PrivateURL`, `ExpiresAt`, and `ExpiresIn`. Signing requires a processed private asset and appropriate permission.

## Listing and deletion

`PageOptions` embeds `RequestOptions`, with `Page` (default 1) and `Limit` (default 20; 1–100). `Page[T]` contains `Data`, `Page`, `Limit`, `Total`.

`UploadFilters` embeds `PageOptions` and adds `ProjectID`, `Visibility`, `ExternalID` (up to 512 UTF-8 bytes), `Data map[string]string`, `DeletionStatus`, and either `Status` or `StatusCode`. Named filters are `Pending`, `Processing`, `Processed`, `Failed`, `Unprocessable`; numeric filters accept 1–6. `AssetFilters` adds only `DeletionStatus` to `PageOptions`. Deletion filters are `Active`, `Deleting`, `Deleted`, `LegacyDeleted`; omission uses the server's active default.

```go
for asset, err := range files.IterateUploads(ctx, kompressr.UploadFilters{
    PageOptions: kompressr.PageOptions{Limit: 50},
    Status: kompressr.Processed,
}) {
    if err != nil { return err }
    // Process asset. Breaking the loop prevents subsequent page requests.
    _ = asset
}
```

Every page has a finite request budget; pagination is not a snapshot while records change. The iterator rejects mismatched pages or more rows than the reported limit.

`AssetState` contains `ID`, `ProjectID`, `Kind`, `Source`, `ProcessingStatus`, `DeletionStatus`, `StorageCreditedMB`, optional deletion/accounting state and `LastFailure`. It is a lifecycle record, without upload URLs or metadata. List credits are zero; inspect detail for recorded credits.

`BulkDeletion.Results` contains ordered `DeletionResult` entries with `ID`, HTTP `Status`, `Accepted`, optional `State`, `Code` and `Error`. `Counts` includes total, accepted and failed. Duplicate input IDs count toward the 100-input limit; expected results deduplicate in first-seen order. Acceptance does not certify cache removal. There is no delete-by-URL, automatic batch expansion, restore or cancel operation.

## Platform administration

Use project authority for these methods. A scoped credential remains unauthorized even through `NewPlatform`.

| Method | Arguments after context | Result |
| --- | --- | --- |
| `ListUsers` | `PageOptions` | `ProjectUserPage` |
| `CreateUser` | `CreateUserOptions`, `RequestOptions` | `CreatedUser` (`Created`, `ProjectUser`) |
| `UpdateUser` | user UUID, `UpdateUserOptions`, `RequestOptions` | `ProjectUser` |
| `SuspendUser` | user UUID, `RequestOptions` | `ProjectUser` |
| `ReactivateUser` | user UUID, `RequestOptions` | `ProjectUser` |
| `ListUploadKeys` | user UUID, `PageOptions` | `Page[UploadKey]` |
| `CreateUploadKey` | user UUID, `CreateKeyOptions`, `RequestOptions` | `IssuedKey` |
| `RotateUploadKey` | user UUID, key-record UUID, `RequestOptions` | `IssuedKey` |
| `RevokeUploadKey` | user UUID, key-record UUID, `RequestOptions` | `error` only |

`CreateUserOptions.CustomerUserID` is a stable application identity (1–256 trimmed UTF-8 bytes), which the server finds or creates. Both create/update accept optional `DisplayName *string` (120 trimmed UTF-8 bytes; pointer to empty string clears it) and `Metadata CustomerData`. `ProjectUser` contains identity/project/customer IDs, status, optional name/metadata/activity counters and timestamps. Optional counters are pointers, preserving absence. `ProjectUserPage` includes project/org active counts and optional subscription `UsagePeriod`.

`CreateKeyOptions` requires `Name` (1–120 trimmed UTF-8 bytes). Optional `Scopes []UploadScope` permits `ScopeUpload`, `ScopeStatus`, `ScopeList`, `ScopePrivateURL`, `ScopeDelete`. Nil omits scopes and uses server defaults; an explicit nonempty slice replaces defaults. An explicitly empty scope slice fails validation before any request. The SDK never adds delete. `AllowedVisibility` accepts `Public`, `Private`, `Both`. `AllowedAssetTypes []int` contains positive numeric API types; empty means all supported. `ExpiresAt *time.Time` must be in the future.

`UploadKey` contains record/key/project/user IDs, name, scopes, restrictions and optional expiry/revocation/activity timestamps. `IssuedKey` has `ID`, `KeyID`, one-time `APIKey`, and optional `UploadKey`. Its formatting hides credentials; deliberate JSON encoding includes the secret for secure storage. Suspend revokes keys without deleting files; reactivate leaves revoked keys revoked. Key creation/rotation are not idempotent recovery operations.

## Error fields and transport policy

Use `errors.As(err, &failure)` with `var failure *kompressr.Error`:

| Field | Meaning |
| --- | --- |
| `Kind` | validation, api, network, timeout, cancelled, invalid_response, processing |
| `Code` | Safe API code or stable client code |
| `Message` | Sanitized bounded message |
| `Status` | HTTP status, or zero if unknown |
| `RetryAfter` | Suggested delay as `time.Duration`, or zero |
| `AssetID` | Safe known/requested asset ID, or zero |
| `MayHaveSucceeded` | A dispatched write's outcome may be uncertain |

Client codes: `INVALID_ARGUMENT`, `INVALID_RESPONSE`, `NETWORK_ERROR`, `REQUEST_TIMEOUT`, `REQUEST_CANCELLED`, `WAIT_TIMEOUT`, `WAIT_CANCELLED`, `PROCESSING_FAILED`, `ASSET_DELETED`. Context errors also support `errors.Is`.

Malformed successful writes and interrupted writes remain uncertain; valid successful upload envelopes can recover a safe `data.asset_id`, but broken JSON cannot. Single-asset mutations preserve the requested ID; bulk failures never invent one. Cancellation before dispatch has `MayHaveSucceeded=false`. That false value does not establish application-level workflow idempotency.

Only eligible GET network/429/502/503/504 failures retry. Overall request budgets include retries and body reads. Typed responses use exact, case-sensitive JSON field names at every nesting level. Differently cased aliases cannot override canonical fields; unknown fields are ignored for forward compatibility. Customer metadata and option-map keys retain their original spelling. Responses above 2 MiB are rejected; HTML and raw network errors are not exposed. Credentials and signed URLs are removed from API error messages.

Redirects are never followed. A redirect after a write is conservatively marked uncertain. Writes use fresh HTTP/1 connections and no replay body to prevent implicit transport resubmission. Reads can reuse connections and use HTTP/2. See [transport rationale](CONTRIBUTING.md).
