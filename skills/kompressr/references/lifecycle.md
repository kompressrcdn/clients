# File lifecycle, failure recovery and deletion

## Upload through to delivery

1. Validate file/visibility requirements and authenticate the application user.
2. Upload once with the selected credential. In raw HTTP, multipart options precede the file.
3. Persist the numeric asset ID before waiting. SDKs normalize acceptance `data.asset_id` to the language's `id`/`ID`/`Id` field.
4. Poll within a finite deadline. SDK readiness helpers do this. Pending/processing means wait; failed, unprocessable, deleted or unknown states must not become successful delivery results.
5. For a processed public asset, use its current `cdn_url`. For a processed private asset, require `can_generate_private_url`, authorize the viewer and explicitly generate a fresh signed link.

A `processed` response missing a public URL or private signing readiness is invalid, not permission to construct a URL. Upload status uses named states; managed-asset records also expose numeric `processing_status`. Use the correct response shape.

## Identifiers

| Identifier | Meaning |
| --- | --- |
| Asset ID | Numeric identifier for status, signing and deletion |
| Project ID | UUID selecting the project; required for upload listing |
| Project-user ID | UUID for a tenant/user/agent identity within the project |
| Customer user ID | Your stable application identity used in provisioning |
| Key record ID | UUID for key management; not the API secret |
| External ID / customer data | Correlation metadata; not authorization or an automatic idempotency key |

Use a durable application record. CLI receipt files demonstrate recovery but do not replace deployed database/job storage. Preserve the project/owner association so an ID supplied later cannot bypass authorization.

## Timeouts, cancellation and retries

SDK defaults: management 30 seconds, upload 600 seconds, readiness wait 120 seconds with roughly two-second polling. Request budgets include response bodies and retries. A readiness timeout is a caller budget, not a processing SLA. JavaScript/PHP options use milliseconds; Python/Ruby use seconds; Go/Java/.NET use native duration types.

`WAIT_TIMEOUT` or `WAIT_CANCELLED` preserves the ID. Schedule another status check or resume on that ID. Stopping a request does not stop an accepted server job.

SDKs retry eligible GET network errors and HTTP 429/502/503/504 within bounded budgets, twice by default, respecting `Retry-After`. They do not automatically replay writes. A generic retry wrapper around uploads or key issuance would defeat that policy.

An error's `mayHaveSucceeded` (language-specific spelling) means a dispatched write can have succeeded despite its missing/invalid response. Save any safely recovered asset ID and inspect the outcome. Without an ID, reconcile through application metadata/project records or listing; a missing ID does not prove no upload occurred. Metadata correlation is not a uniqueness guarantee.

Explicitly repeating deletion of the same selected IDs is supported after inspection. This does not authorize repeating every mutation or widening a failed selection into delete-all.

## Private delivery

Private files have no public CDN URL. Wait for signing readiness, authorize access and generate a link. The default lifetime is 3,600 seconds; requested lifetimes are 60–604,800 seconds. Generate fresh links when authorized users reopen documents. The asset remains stored when a link expires.

Keep asset IDs as permanent attachment references. Preserve signed URLs unchanged and exclude them from ordinary logs/public diagnostics. A recipient can share an unexpired bearer link; identity isolation does not make it non-transferable.

## Listing and reconciliation

- Upload listing returns upload metadata, processing and delivery fields, needs a project UUID, and respects scoped identity access.
- Managed-asset listing covers assets within the key's authority, including project-authorized URL-prepend records. It infers the project from the key and returns lifecycle records rather than complete upload delivery records.
- Page through results; maximum page size is 100. SDK iterators fetch lazily. Concurrent changes mean pages are not an immutable snapshot.
- Deletion filters: `active`, `deleting`, `deleted`, `legacy_deleted`. Historical records do not provide live delivery URLs.
- Use asset detail for recorded deletion/storage-credit progress; list records do not report those credits meaningfully.

## Permanent deletion

Delete by numeric asset ID. Acceptance means background removal was requested. `deletion_status=deleting` is pending removal; `deleted` reports file removal. Cached, downloaded and offline copies may remain. No trash, restore or cancellation is provided.

Bulk deletion accepts 1–100 explicitly selected IDs. Inspect every `results[].accepted` and failure count even under HTTP 200. Resolve failed items before retrying. Deletion requires its own permission.

A GET cannot restore deleted upload bytes. Deliberate reupload creates a new asset ID and may reuse its delivery URL. URL-prepend content can regenerate from an available origin. Deleting an old ID does not target a replacement with a new ID.

Storage credit follows recorded removal; shared stored content can count while another asset uses it. Historical bandwidth and processing are not undone. Recorded MB storage credit is not money refunded.

Full behavior: [cross-language contract](https://github.com/kompressrcdn/clients/blob/main/contracts/sdk-behavior.md), [HTTP schemas](https://github.com/kompressrcdn/clients/blob/main/contracts/kompressr-api.yaml).
