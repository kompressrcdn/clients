# Python API reference

The Python SDK follows JS SDK 1.0.0 and the shared API contract. Import `KompressrClient`, `PlatformClient`, `AsyncKompressrClient`, `AsyncPlatformClient`, `KompressrError`, `KompressrCancelledError` and `CancellationToken` from `kompressr`. Public response types are exported from that module too. Sync and async methods accept the same arguments and return the same typed dictionaries; async methods must be awaited. Async iteration uses `async for`.

## Configuration

Construct clients with keyword arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `api_key` | Required | Explicit project or scoped key; never persisted |
| `project_id` | Omitted | File client only; UUID default for upload listing |
| `api_base_url` | `https://kompressr.com` | Management origin |
| `upload_base_url` | Derived | `https://uploads.kompressr.com` for the production management origin; otherwise the custom management origin |
| `request_timeout` | `30` | Total management request budget in seconds |
| `upload_timeout` | `600` | Total upload request budget in seconds |
| `max_read_retries` | `2` | Additional eligible GET attempts, integer 0–5 |

Origins must be absolute HTTP(S) origins without credentials, path, query or fragment. File clients expose resolved `api_base_url`, `upload_base_url` and `platform`. `resolve_endpoints(...)` and `ENDPOINTS` allow inspecting configuration without a request. For an alternate deployment, explicitly supply its management and upload origins. There is no environment-name switch.

HTTPX verifies TLS certificates, does not follow redirects, has transport retries disabled and does not automatically read proxy settings from the environment. The SDK creates and closes a connection pool for each operation, including all retries. There is no persistent connection pool or client lifecycle method. No caller-supplied transport is accepted.

DNS resolution shares a process-wide limit of eight daemon workers with no queued resolver jobs. Cancelling or timing out stops the caller promptly and prevents a late connection/write, even while an operating-system lookup remains blocked. That lookup keeps its slot until the OS returns; if all eight slots remain occupied, later hostname requests can time out waiting for admission. Numeric IP origins bypass DNS. A separate limit permits 64 live connections per process; waiting for either limit remains inside the request deadline.

Resolved TCP addresses are tried sequentially in system order. Each receives a fair share of the **remaining** request budget divided by the remaining addresses, so a stalled first address leaves time for fallback. There is only one connection attempt per request at a time. This can take longer than Happy Eyeballs, which races address families, but avoids extra background connection attempts. DNS time is deducted before allocating those shares. The original hostname remains the HTTP Host and TLS SNI/certificate identity. Scoped IPv6 zone identifiers are unsupported.

Every HTTP method supports keyword-only `timeout: float | None` and `cancel: CancellationToken | None`. Positive finite timeouts use seconds (maximum 2147483.647); constructor budgets apply when omitted. Deadlines include connection setup, upload writes, response reads and retry waits. File opening, validation and the snapshot of an in-memory buffer happen before the request budget. Standard local file reads occur in bounded chunks on the calling thread; filesystem I/O itself is subject to operating-system behavior. Arbitrary/custom stream readers, pipes and sockets are rejected.

## Uploads and delivery

| Method | Required arguments | Result |
| --- | --- | --- |
| `upload_file` | `path: str | PathLike[str]` | `UploadAccepted`; opens and closes a regular binary file |
| `upload_bytes` | `content: bytes | bytearray | memoryview`, `filename` | `UploadAccepted`; snapshots the selected bytes when the operation starts |
| `upload_stream` | `stream: BinaryIO`, `filename` | `UploadAccepted`; standard regular `FileIO`/`BufferedReader` or `BytesIO` only; rewinds to zero and leaves it open |
| `get_upload_status` | `asset_id: int` | `UploadAsset` |
| `wait_until_ready` | `asset_id: int` | Active, processed `UploadAsset` |
| `generate_private_url` | `asset_id: int` | `PrivateUrl` |

Upload keyword arguments: `visibility='public'|'private'` (server default if omitted), `quality='480p'|'720p'|'1080p'|'4k'` (video only), `data: CustomerData`, `private_url_expires_in: int` (60–604800 seconds). Metadata fields always precede the multipart file. Filenames must be nonempty, contain valid UTF-8 and have no control characters; directory components are removed. Stream subclasses/custom wrappers are unsupported because their reads can block cancellation or misreport length. File source contents must remain unchanged during upload.

`CustomerData` is a dictionary of up to five scalar strings, finite numbers, booleans or `None`. Keys are trimmed, unique after trimming, nonempty and at most 64 UTF-8 bytes. String values support 512 UTF-8 bytes. Encoded upload data is limited to 4096 bytes; platform metadata to 8192.

`wait_until_ready` accepts `timeout=120`, `poll_interval=2` (positive seconds, maximum 30) and `cancel`. A timeout raises `WAIT_TIMEOUT`; cancellation raises `WAIT_CANCELLED`. Both preserve `asset_id`. Failed, unprocessable or unknown processing raises `PROCESSING_FAILED`; nonactive deletion raises `ASSET_DELETED`. A processed public asset must have a delivery URL; a private one must be eligible to generate a link. Waiting never reuploads or signs automatically. The total wait deadline also bounds any in-flight status request and its retries. An earlier per-request deadline can surface as `REQUEST_TIMEOUT`, still with the saved asset ID.

`generate_private_url` accepts `expires_in=3600` (60–604800 integer seconds), `variant='webp'|'avif'` (default `webp`), plus request options. The server rejects unprocessed/public assets or unavailable variants. Private URLs authorize access: do not place them in ordinary logs.

`UploadAccepted` requires `id`, `status`, `deletion_status`, `visibility`, `original_name`, `original_size`, `asset_type`. The wire `asset_id` is normalized to `id`. Optional fields include delivery URLs, `private_url_expires_at`, `data`, `external_id`, `options`, `quality`, `warning`, `deletion_requested_at`.

`UploadAsset` adds `kompressd_size`, `savings_percent`, `can_generate_private_url`; `original_name` is optional or empty for older records. Optional `input_format`, `output_format` and `created_at` may be returned. Sizes are bytes. Processing states are `pending`, `processing`, `processed`, `failed`, `unprocessable`, `unknown`; deletion is independent (`active`, `deleting`, `deleted`, `legacy_deleted`). Private assets cannot contain public URLs; nonactive assets cannot contain delivery URLs. A pending public URL does not prove readiness.

`PrivateUrl` contains `asset_id`, `variant`, `private_url`, `expires_at`, `expires_in`.

## Listing and lifecycle

| Method | Arguments | Result |
| --- | --- | --- |
| `list_uploads` | Upload filters below | `Page[UploadAsset]` |
| `iterate_uploads` | Same filters | Lazy sync iterator / async iterator of `UploadAsset` |
| `list_assets` | `page=1`, `limit=20`, optional `deletion_status`, request options | `Page[AssetState]` |
| `get_asset` | `asset_id`, request options | `AssetState` |
| `delete_asset` | `asset_id`, request options | Accepted or completed deletion `AssetState` |
| `bulk_delete_assets` | List of 1–100 explicit numeric IDs, request options | `BulkDeletion` |

Upload filters are keyword-only `project_id` (required from constructor or call), `page=1`, `limit=20` (1–100), `visibility`, `external_id` (at most 512 UTF-8 bytes), `data` (up to five string-valued filters), `status` (pending/processing/processed/failed/unprocessable or integer 1–6), `deletion_status`, `timeout`, `cancel`. The server defaults deletion filtering to active. Status names are mapped to the numeric wire filter.

`Page[T]` contains `data: list[T]`, `page`, `limit`, `total`. Iteration fetches only as needed, checks page progression and stops on an empty page or the reported total. Each page has a separate finite request deadline. Breaking iteration prevents further requests. Offset-based listings can change while files are added or deleted.

`AssetState` requires `id`, `project_id`, `kind`, `source` (`upload`/`origin`), numeric `processing_status`, `deletion_status`, `storage_credited_mb`. Optional fields: `deletion_requested_at`, `accounting_status` (`pending`/`settled`/`unavailable`), `last_failure: {code, message, at}`. This lifecycle shape does not contain upload delivery metadata. List credits are zero; inspect detail for accounting.

`BulkDeletion` preserves `results` (each `id`, HTTP-like `status`, `accepted`, optional `state`, `code`, `error`) and `counts` (`total`, `accepted`, `failed`). Duplicate input IDs count toward the input limit and are sent unchanged; response validation expects first-seen deduplication. Success of the HTTP request does not mean every item succeeded. Results and counts are validated together.

Asset IDs must be positive integers no greater than 9007199254740991, retaining compatibility with the JS baseline. Booleans, strings and Python floats are rejected as ID inputs. Deletion is permanent and asynchronous; acceptance does not prove storage cleanup or cache expiry. There is no delete-by-URL, restore, implicit batch expansion or automatic mutation retry.

## Platform administration

Use `client.platform` or a standalone `PlatformClient`/`AsyncPlatformClient` with project authority. A scoped key cannot gain administration access by constructing a different client.

| Method | Arguments | Result |
| --- | --- | --- |
| `list_users` | `page=1`, `limit=20`, request options | `ProjectUserPage` |
| `create_user` | `customer_user_id`, optional `display_name`, `metadata`, request options | `{created, project_user}` |
| `update_user` | `project_user_id`, optional `display_name`, `metadata`, request options | `ProjectUser` |
| `suspend_user` | `project_user_id`, request options | `ProjectUser` |
| `reactivate_user` | `project_user_id`, request options | `ProjectUser` |
| `list_upload_keys` | `project_user_id`, `page=1`, `limit=20`, request options | `Page[UploadKey]` |
| `create_upload_key` | `project_user_id`, `name`, optional policy below, request options | `IssuedKey` |
| `rotate_upload_key` | `project_user_id`, key-record `key_id`, request options | `IssuedKey` |
| `revoke_upload_key` | `project_user_id`, key-record `key_id`, request options | `None` |

Project/user/key-record identifiers are UUID strings. Stable `customer_user_id` supports 1–256 UTF-8 bytes; the server finds or creates that identity. Display names support 120 bytes and can be cleared with `''`; omitted or `None` fields are not sent. Use `{}` to clear metadata.

`create_upload_key` policy: optional `scopes: list[UploadScope]` drawn from `upload`, `status`, `list`, `private_url`, `delete`; `allowed_visibility='public'|'private'|'both'`; `allowed_asset_types: list[int]` (positive IDs; empty means all supported); `expires_at` (future ISO timestamp with timezone). Key names require 1–120 UTF-8 bytes. Omitted scopes (or `None`) use server defaults excluding delete; a nonempty explicit list replaces defaults. An explicitly empty list raises `INVALID_ARGUMENT` before any request: do not create a key when your permission filter selects no scopes. Issuing another key is not idempotent, and the SDK invents no spending limits.

`ProjectUser` contains identity/project IDs, `customer_user_id`, `status` (`active`/`suspended`) and optional `display_name`, metadata, usage counters and activity timestamps. `ProjectUserPage` adds `project_active_count`, `org_active_count`, optional `usage_period: {start,end}` date strings. `UploadKey` contains `id`, `key_id`, project/user IDs, `name`, scopes, `allowed_visibility`, optional asset types and expiry/revocation/activity timestamps.

`IssuedKey` contains `id`, `key_id`, `api_key` and optional `upload_key`. The raw key is returned once and must be stored or delivered securely; list methods do not recover it. Suspension revokes keys without deleting files. Reactivation does not restore revoked keys; issue a new key. Rotation replaces the secret.

## Error and cancellation contract

`KompressrError` exposes `kind`, `code`, optional `status`, `retry_after_ms`, `asset_id`, and boolean `may_have_succeeded`. `to_dict()` returns these safe fields and the message. Kinds: `validation`, `api`, `network`, `timeout`, `cancelled`, `invalid_response`, `processing`. Known credentials, bearer values, URLs and credential assignments are redacted from error messages; raw response bodies and one-time secrets are not attached. Do not log successful key or signed-URL result dictionaries.

Eligible GET network errors and HTTP 429/502/503/504 retry with bounded backoff; `Retry-After` seconds/date or body `retry_after` is respected inside the total deadline. Other statuses, malformed successful responses and all writes have no automatic replay. Failed envelopes are handled even under HTTP 200. Responses above 2 MiB or malformed shapes raise `INVALID_RESPONSE`. Requests advertise `Accept-Encoding: identity`; other response content encodings are rejected before decompression. Successful compressed responses raise `INVALID_RESPONSE`; error responses retain their HTTP status and header retry delay without parsing the compressed body. Request timeouts and cancellation preserve the last known response status and retry delay, including while reading a body or waiting to retry. Starting a new attempt clears that prior response context.

If a server rejects a large upload before reading its body and closes the connection, HTTPX can report a write/network error before exposing the HTTP response. The SDK then returns `NETWORK_ERROR` with `may_have_succeeded=True`, rather than the server's rejection status. Inspect the upload outcome before retrying; the SDK does not replay it automatically.

A dispatched mutation can have succeeded despite timeout, network failure, task cancellation, rejected redirect, server failure, or invalid successful data. These errors set `may_have_succeeded=True`. Pre-dispatch cancellation and local validation set it false. A false value does not certify that replaying an entire application workflow is safe. Single-asset writes retain the requested ID. Upload recovery only trusts a positive safe numeric `data.asset_id` from a parsed successful envelope; broken JSON has no recoverable ID. Bulk errors never choose one arbitrary ID.

`CancellationToken.cancel()` is thread-safe; pass the token as `cancel=`. Cancellation is checked before dispatch and during network activity/backoff with a small polling interval. Token cancellation raises `KompressrError`; native asyncio task cancellation raises `KompressrCancelledError`, retaining `asyncio.CancelledError` semantics and the same metadata. Catch native cancellation only for cleanup, then re-raise. Native task cancellation before a coroutine starts cannot attach SDK metadata because no SDK code has run. Standard local file errors may occur before a request and remain native Python exceptions.
