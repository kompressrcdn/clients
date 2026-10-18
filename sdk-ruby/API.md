# Ruby API reference

Require `kompressr`. Public classes are `Kompressr::Client`, `Kompressr::PlatformClient`, `Kompressr::CancellationToken`, `Kompressr::Error` and `Kompressr::IssuedKey`. All methods are synchronous. Responses use string-keyed hashes, except key creation/rotation, which return `IssuedKey`. Unknown response fields are dropped; field matching is case-sensitive at every level.

## Configuration

```ruby
files = Kompressr::Client.new(
  api_key: ENV.fetch('KOMPRESSR_API_KEY'),
  project_id: ENV.fetch('KOMPRESSR_PROJECT_ID'), # Needed only for upload listing.
  request_timeout: 30,
  upload_timeout: 600,
  max_read_retries: 2
)
```

| Keyword | Default | Meaning |
| --- | --- | --- |
| `api_key` | Required | Supplied project or scoped credential; no fallback credentials |
| `project_id` | Omitted | File client only; UUID default for upload listing |
| `api_base_url` | `https://kompressr.com` | Management HTTP(S) origin |
| `upload_base_url` | Derived | Production uses `https://uploads.kompressr.com`; a custom management origin is also used for uploads unless overridden |
| `request_timeout` | `30` | Management request deadline, in seconds |
| `upload_timeout` | `600` | Upload request deadline, in seconds |
| `max_read_retries` | `2` | Additional GET attempts, integer 0–5 |

Origins cannot contain credentials, a path other than `/`, query, fragment or IPv6 zone identifier. HTTP supports local testing; production defaults use HTTPS. TLS verifies the trust chain and original hostname and sends that hostname as SNI. The standard OpenSSL CA store is used. Clients expose resolved `api_base_url`, `upload_base_url` and `platform`; credentials are redacted from inspection. Constructor strings are copied where they are retained.

Individual HTTP methods accept `timeout: nil` and `cancel: nil`. A supplied timeout must be positive, finite seconds no greater than 2,147,483.647; `nil` selects the configured budget. `wait_until_ready` has its own overall timeout, described below. `false` is invalid. A cancel value must be a `CancellationToken`. Cancellation is cooperative and observed approximately every 10 ms while waiting for network activity, admission or retry delay. Normal OS thread scheduling can add latency.

## Uploads and delivery

| Method | Required positional arguments | Result |
| --- | --- | --- |
| `upload_file` | Local regular-file path, String or Pathname | Accepted upload |
| `upload_bytes` | Binary String, filename | Accepted upload |
| `get_upload_status` | Asset ID | Upload asset |
| `wait_until_ready` | Asset ID | Processed, active and deliverable upload asset |
| `generate_private_url` | Asset ID | Private link |

Upload keywords: `visibility: 'public'|'private'`, `quality: '480p'|'720p'|'1080p'|'4k'`, `data:`, `private_url_expires_in:`, `timeout:` and `cancel:`. Omitted visibility uses the server default. Quality applies to video. Private URL lifetime is an integer from 60 through 604800 seconds. Multipart fields precede the file. Filenames contain valid UTF-8, no control characters, and at most 4096 bytes; directory components are removed. Raw file content is binary and has no UTF-8 requirement.

`upload_file` opens/closes its own file and checks that it is regular before and after opening. A nonblocking open prevents a raced FIFO replacement from blocking at open. It streams 64 KiB chunks and detects a source that ends before the initial length. Keep the file unchanged during upload. `upload_bytes` snapshots its String before dispatch; supplying a large String therefore uses memory proportional to the bytes already supplied. Arbitrary IO objects, streams, sockets, devices and pipes are unsupported. There is no `upload_stream` method in this release.

Metadata is a String-keyed Hash of at most five scalars: String, finite Integer/Float, boolean or nil. Keys are trimmed, unique after trimming, nonempty and at most 64 UTF-8 bytes. String values allow 512 bytes. Encoded upload metadata allows 4096 bytes; platform metadata allows 8192. `nil` scalar values are preserved. UTF-8 String values and binary Strings containing valid UTF-8 bytes are accepted; incompatible encodings must be converted by the caller.

An accepted upload requires `id`, `status`, `deletion_status`, `visibility`, `original_name`, `original_size`, `asset_type`. Wire `asset_id` is normalized to `id`. Optional fields include `cdn_url`, `cdn_url_avif`, `private_url`, `private_url_expires_at`, `data`, `external_id`, `options`, `quality`, `warning`, `deletion_requested_at`.

Upload status adds `kompressd_size`, `savings_percent`, `can_generate_private_url`; `original_name` can be absent/empty for older records. Optional `created_at`, `input_format` and `output_format` are retained. Sizes are bytes. Processing states: pending, processing, processed, failed, unprocessable, unknown. Deletion states: active, deleting, deleted, legacy_deleted. Private assets cannot contain public delivery URLs; nonactive assets cannot contain delivery URLs.

`wait_until_ready(asset_id, timeout: 120, poll_interval: 2, cancel: nil)` polls within one overall deadline; interval must be positive and at most 30 seconds. Failed, unprocessable and unknown states raise `PROCESSING_FAILED`; nonactive deletion raises `ASSET_DELETED`. A processed public asset without `cdn_url`, or processed private asset without `can_generate_private_url: true`, raises `INVALID_RESPONSE` immediately. Pending/processing assets continue polling even if a URL is already present. Waiting never reuploads or signs automatically. Timeout/cancellation preserves the ID for recovery. An earlier per-request timeout remains `REQUEST_TIMEOUT`; overall wait exhaustion becomes `WAIT_TIMEOUT`.

`generate_private_url(asset_id, expires_in: 3600, variant: 'webp', ...)` also supports `variant: 'avif'`. The returned hash contains `asset_id`, `variant`, `private_url`, `expires_at`, `expires_in`. The service rejects unavailable variants and assets that cannot be signed. Treat private URLs as credentials.

## Listing and lifecycle

| Method | Arguments | Result |
| --- | --- | --- |
| `list_uploads` | Upload filters below | Page of upload assets |
| `iterate_uploads` | Same filters | Lazy Enumerator of upload assets |
| `list_assets` | `page: 1`, `limit: 20`, `deletion_status:`, request options | Page of asset states |
| `get_asset` | Asset ID, request options | Asset state |
| `delete_asset` | Asset ID, request options | Accepted/completed deletion state |
| `bulk_delete_assets` | Array of 1–100 explicit IDs, request options | Per-item bulk results |

Upload filters: `project_id:` (UUID, from constructor or call), `page: 1`, `limit: 20` (1–100), `visibility:`, `external_id:` (up to 512 UTF-8 bytes), `data:` (up to five String-valued filters), `status:` (pending/processing/processed/failed/unprocessable or integer 1–6), `deletion_status:`, `timeout:`, `cancel:`. The server defaults deletion filtering to active.

Pages contain `data`, `page`, `limit`, `total`. The Enumerator makes no request until consumed, validates returned page progression, and stops on an empty page or reported total. Each page has its own request deadline. Stopping iteration prevents later page requests. Offset listings can change while records are added or deleted.

Asset state requires `id`, `project_id`, `kind`, `source` (upload/origin), numeric `processing_status`, `deletion_status`, `storage_credited_mb`. Optional fields: `deletion_requested_at`, `accounting_status` (pending/settled/unavailable), `last_failure: {code, message, at}`. This lifecycle shape has no upload delivery metadata. List credits are zero; detail provides accounting.

Bulk deletion returns `results` and `counts: {total, accepted, failed}`. Each result includes `id`, `status`, `accepted` and, as appropriate, `state`, `code`, `error`. The SDK validates all outcomes and counts together. Duplicate input IDs are sent unchanged and count against the input limit; responses use first-seen deduplication. HTTP 200 can contain failed items. A malformed bulk response does not choose an arbitrary ID for its error.

Input asset IDs must be Ruby Integers from 1 through 9007199254740991. Strings, booleans and Floats are rejected as IDs. Deletion is permanent and asynchronous; acceptance does not prove physical removal or cache expiry. There is no implicit batch expansion, restore, delete-by-URL or mutation retry.

## Platform administration

Use `files.platform` or `Kompressr::PlatformClient.new(api_key: ..., ...)` with project authority. The standalone client accepts the shared configuration, excluding `project_id`.

| Method | Required positional arguments | Optional keywords / result |
| --- | --- | --- |
| `list_users` | None | `page:`, `limit:`; user page plus `project_active_count`, `org_active_count`, optional `usage_period` |
| `create_user` | Customer user ID | `display_name:`, `metadata:`; `{created, project_user}` |
| `update_user` | Project user UUID | `display_name:`, `metadata:`; project user |
| `suspend_user` | Project user UUID | Project user |
| `reactivate_user` | Project user UUID | Project user |
| `list_upload_keys` | Project user UUID | `page:`, `limit:`; page of upload keys |
| `create_upload_key` | Project user UUID, name | Policy below; `IssuedKey` |
| `rotate_upload_key` | Project user UUID, key UUID | `IssuedKey` |
| `revoke_upload_key` | Project user UUID, key UUID | `nil` on success |

All accept request options. Customer user IDs allow 1–256 UTF-8 bytes; display names and key names allow up to 120. Empty display names and empty metadata hashes can clear those fields. Missing/nil optional fields are omitted.

Key policy keywords: `scopes:` (upload/status/list/private_url/delete), `allowed_visibility:` (public/private/both), `allowed_asset_types:` (positive integer IDs), `expires_at:` (future ISO 8601 timestamp with timezone). Omitted/nil scopes use service defaults, excluding deletion. An explicit empty scopes array is rejected without dispatch. A nonempty array replaces defaults.

An omitted/nil or empty `allowed_asset_types` list adds no asset-type restriction. Omitted/nil `expires_at` leaves the expiration policy to the service. Persist the project-user ID and provisioned key securely; list operations do not reveal the secret again.

Project users contain `id`, `project_id`, `customer_user_id`, active/suspended `status`; optional display name, metadata, creation/activity timestamps, asset/storage/key counts and usage counters are retained. Key records contain `id`, `key_id`, `project_id`, `project_user_id`, `name`, `scopes`, `allowed_visibility`, optional asset-type restrictions and timestamps. Returned key records never include a secret field.

IssuedKey exposes `id`, `key_id`, optional `upload_key`, and `reveal_api_key`. The last method returns a copy of the one-time provisioning/rotation secret. Routine inspection and JSON redact it. Ruby reflection can access object internals; this wrapper prevents accidental logging rather than providing a security boundary against code running in the same process.

## Errors and timing

`Kompressr::Error` exposes `kind`, `code`, `status`, `retry_after_ms`, `asset_id`, `may_have_succeeded`, plus standard `message`. `to_h`, JSON and inspection contain this safe metadata. Kinds: validation, api, network, timeout, cancelled, invalid_response, processing. Exceptions omit raw response bodies and nested transport exceptions; messages redact the supplied key, bearer credentials and URLs.

Only GET network failures and HTTP 429/502/503/504 automatically retry, up to `max_read_retries`. Backoff starts near 250 ms and includes small jitter. Header `Retry-After` (seconds/date) or JSON `retry_after` (seconds) is a minimum delay; enormous values are saturated without an early retry. Deadline/cancellation during backoff retains the latest status and retry delay. Permission denials, malformed data and processing failures are not retryable reads.

Writes are never replayed and redirects are never followed. A write becomes potentially successful when request bytes may have been sent. Losing the response or receiving malformed successful data retains that uncertainty. Upload ID recovery requires valid JSON with `success: true` and valid numeric `data.asset_id`; broken JSON and invalid Unicode do not produce IDs. Single-asset mutations retain the requested ID. Cancellation before dispatch does not claim success.

During body transmission, the client also watches for an early server response. A permission, size-limit or rate-limit rejection can stop the upload before the whole file is sent, while retaining its API status, code and retry hint. Informational responses allow transmission to continue. A disconnect without a usable response still retains write uncertainty.

When `may_have_succeeded` is true, persist `asset_id` if available and inspect the existing operation's outcome. If an upload has no recoverable ID, reconcile it with your application's records or an authorized listing before retrying. A readiness error can be resumed with the same ID; there is no need to upload again. For key creation or rotation, reconcile administrative state before retrying because the one-time secret might have been issued without reaching your application.

The monotonic request deadline includes connection admission, DNS, TCP, TLS, writes, all response reads and retry delays. Every attempt has a fresh HTTP/1.1 connection closed on completion. Responses are limited to 2 MiB, headers/trailers to 64 KiB each, and status/chunk lines to 8 KiB; at most five informational responses are accepted. Content-Length, chunked and close-delimited bodies are supported. Ambiguous framing, unsupported protocol upgrades and nonidentity content encoding are rejected. No decompressor runs on a server response. JSON parsing is limited to 100 nesting levels and rejects invalid UTF-8 and invalid escaped Unicode.

The transport uses Socket/OpenSSL nonblocking I/O and a small HTTP/1.1 parser. Net::HTTP's per-phase timeouts do not by themselves provide the same total deadline and cancellation across DNS/body reads; this implementation avoids asynchronously interrupting arbitrary threads. It has no native retry layer, proxy discovery or shared connection pool.

DNS uses a process-wide maximum of eight background workers, with no queued resolver jobs. A timed-out/cancelled lookup cannot connect or send a late request. A blocked OS lookup holds its slot until it returns; later hostname requests can time out waiting for admission. Numeric IP origins bypass DNS. At most 64 attempts hold connection slots per process. Waiting for either limit remains inside the same deadline. Addresses are tried sequentially with a share of the remaining budget, preserving hostname/SNI; this can be slower than racing address families. Capacity is reset after a process fork, supporting preloaded applications.

File validation/opening and the byte snapshot precede the HTTP deadline. Regular local file reads occur in bounded chunks, but OS/filesystem stalls and arbitrary Ruby thread scheduling are not forcibly interrupted. Local file access errors before dispatch remain normal Ruby filesystem exceptions. The caller supplies trusted local file paths and keeps input files/options unchanged during calls. MRI Ruby 3.2+ is the supported runtime; asynchronous scheduler integration and other Ruby engines are unverified.
