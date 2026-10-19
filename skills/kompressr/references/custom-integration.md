# Build an integration without an official SDK

Use this guide when the developer's language has no official SDK, their environment is outside the SDK's support, or they explicitly want HTTP. Examples include a Rust or Elixir backend or an HTTP-capable automation system. Do not invent `kompressr` packages for unlisted languages or force a backend rewrite to use an SDK.

Check whether an existing official client is usable through a normal ecosystem boundary: Kotlin on a supported JVM may use Java; F# may use .NET. Otherwise use the application's established HTTP library, or its standard library when suitable. Verify current primary documentation for streaming multipart, cancellation, total deadlines, redirects and retries before choosing an implementation. Browser/mobile secrecy restrictions still apply; build the adapter in a trusted backend or design a separate scoped-credential flow.

## Design a small application adapter

Implement only the operation families the application needs, with room to add others. A one-file upload feature does not require publishing a new general-purpose SDK. Keep service communication separate from the application's user authentication and persistence.

Suggested interface, adapted to language conventions:

```text
upload_file(path_or_supported_stream, visibility, metadata) -> accepted asset ID
get_upload_status(asset_id) -> validated processing record
wait_until_ready(asset_id, deadline, cancellation) -> ready record
generate_private_url(asset_id, expires_in) -> signed link and expiry
list_uploads(project_id, page, limit, filters) -> page
get_asset(asset_id) -> management/deletion record
delete_asset(asset_id) -> accepted/completed deletion state
bulk_delete_assets(explicit_ids) -> per-item outcomes
```

Add platform identity/key methods only for a project-authorized provisioning backend. Method names above describe your adapter; they are not claims that an official package exists.

Keep the management and upload origins configurable for local tests, with production defaults from [HTTP API](http-api.md). Use a trusted fixed destination for the key, TLS validation, finite request/body limits and structured errors. Avoid hidden global credentials or a single mutable credential shared among tenants.

## Upload implementation

1. Validate inputs before network dispatch: supported visibility, nonempty file name, regular readable path or explicitly supported bounded stream, positive timing values, scalar metadata limits.
2. Create streaming multipart with options first and the file last. Let the library generate the boundary/header. Preserve bytes; do not base64-encode the file or put a local path in JSON.
3. Send the bearer key to the upload origin, with a finite total deadline covering upload and response reading. For large files, stream instead of loading the whole file into RAM. Account for application/proxy limits separately.
4. Read a bounded JSON response. Validate `success=true` and a positive integer `data.asset_id` in the compatibility range. Reject booleans, numeric strings and fractional IDs.
5. Return the ID immediately to the caller so it can commit ownership/recovery state before waiting. Do not start a second upload if subsequent polling/persistence fails.

On a broken connection, timeout or invalid success response after dispatch, mark the write outcome uncertain. A safe ID may be recoverable from a valid success envelope; do not regex-extract it from broken JSON or HTML. Before dispatch, local validation/cancellation means no write was sent. Neither case should be turned into an automatic mutation replay.

## Readiness algorithm

```text
deadline = monotonic_now + finite_wait_budget
repeat while time remains:
    check cancellation
    status = get_upload_status(saved_id, bounded by remaining time)
    require expected ID and valid required fields
    if deletion state is not active: fail with saved ID
    if status is processed:
        public: require a nonempty delivery URL; return status
        private: require can_generate_private_url == true; return status
    if status is neither pending nor processing: fail with saved ID
    sleep up to the polling interval, cancellable and bounded by deadline
return wait-timeout with saved ID
```

A typical initial wait budget is 120 seconds with a roughly two-second poll interval. This is not a guaranteed processing time. Resume from the saved ID later. The signing step remains explicit after private readiness and authorization.

Use a monotonic clock for deadlines; network attempts, response-body reads and retry delays share that budget. Cancellation stops your request/wait, not an accepted remote job. Respect your language's structured cancellation convention rather than swallowing it as an ordinary success.

## Response and error contract

Normalize the different endpoint shapes intentionally. Upload/status/signing use `success/data`; managed asset detail/deletion return state directly; bulk deletion returns per-item results; platform responses use `project_user`, `project_users` and key fields. Do not blindly unwrap every response through `.data`.

Parse exact documented field names and validate the values you will use. Unknown fields must not override validated lifecycle fields through case-insensitive decoding. Reject contradictory required fields and invalid public/private/deletion combinations. An HTTP 200 containing `success=false` is an error.

Use a bounded management JSON response size; official SDKs cap it at 2 MiB. Enforce limits while reading, not only after allocating the full body. If compression is accepted, bound decoded output during decompression; otherwise request identity encoding and reject an unexpected compressed response before decompressing it.

Expose structured application errors with a category, safe code/message, HTTP status when known, retry delay, known asset ID and mutation uncertainty. Preserve permission and processing failures. Do not attach raw HTML, authorization headers, successful secret issuance bodies or private URLs to error logs.

## Retry policy

- Eligible reads: GET network failures or HTTP 429/502/503/504, with a small bounded retry count and backoff. Two retries is the SDK default.
- Honor `Retry-After` seconds or HTTP date without retrying earlier. Parse large values safely and saturate rather than overflow; a delay beyond the remaining deadline ends the request.
- No automatic replay for uploads, signing, deletion, user/key mutations or malformed responses. Disable hidden retry/redirect middleware that can resend a body or leak authorization.
- Permission errors, invalid inputs, unknown processing states and malformed successful JSON are not transient read failures.
- After an uncertain deletion, inspect or explicitly repeat the same selected IDs. After an uncertain upload/key creation, reconcile before replaying; a missing response is not evidence of failure.

Do not invent an `Idempotency-Key` guarantee. External metadata can help find an operation but is not server-enforced uniqueness.

## Privacy and tenant boundaries

Select credentials from the authenticated application's identity mapping. Never accept a caller-supplied tenant ID as proof of membership or silently retry with a master key. Validate explicit scopes before issuing a key: omission permits defaults, nonempty lists replace them and `[]` must be rejected. Keep issuance/rotation secrets in a private store and preserve key record IDs.

For private files, authorize the user and resource/conversation, sign the existing asset, return the URL/expiry, and refresh later on renewed access. Do not modify signed URLs. Keep project keys off browsers and mobile devices. See [security](security.md).

## Verify the generated adapter

Use a local HTTP fixture or mock server in the chosen language before an authorized live test. These are observable contract cases, not tests that only check method names:

| Scenario | Expected result |
| --- | --- |
| Multipart upload | Options precede the binary file; bytes/name preserved; only one POST |
| Accepted → pending → processed | ID persisted before polling; return current public URL only when ready |
| Private processed file | No public URL; signing occurs only after explicit app authorization |
| Failed/unknown/deleting response | Stop with an error and saved ID |
| Deadline/cancellation after acceptance | Resume ID retained; no second upload |
| Lost response / malformed success after write | Uncertainty preserved; no automatic replay |
| 429/503 with Retry-After | Bounded GET retry; never earlier than requested or past deadline |
| Oversized/compressed JSON | Bounded memory or rejection before decompression |
| 401/403 / cross-user 404 | Denial surfaced; no credential escalation |
| Paginated listing | Correct project/query values and page progression; no pretend snapshot |
| Partial bulk deletion under HTTP 200 | Each item retained; failures not reported as deleted |
| Empty scopes or invalid IDs | Rejected before HTTP |

Compile/typecheck the actual integration and run its framework route/job tests. Then use authorized disposable assets for the real account workflow, including a second scoped identity when relevant. Report fixture and live results separately. The [HTTP contract](https://github.com/kompressrcdn/clients/blob/main/contracts/kompressr-api.yaml) and [shared behavior](https://github.com/kompressrcdn/clients/blob/main/contracts/sdk-behavior.md) are the reference, not guesses based on another storage service.
