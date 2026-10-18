# SDK behavior across languages

The JavaScript SDK 1.0.0 and the [HTTP contract](README.md) define the compatibility baseline. Language clients use native naming, input types and cancellation mechanisms. Each package documents its supported runtimes and maps its methods to this API. A generated HTTP wrapper alone does not provide waiting, recovery or safe retry behavior.

## File and platform operations

Every SDK covers file and byte uploads, upload status, readiness waiting, private URL generation, upload listing and iteration, managed-asset listing/detail, single and bulk deletion, and platform identity/key administration. Native file/stream inputs replace JavaScript-specific Blob inputs where appropriate. Dashboard session endpoints in the OpenAPI snapshot are outside the SDK surface.

Platform administration includes listing, creating, updating, suspending and reactivating project users, and listing, creating, rotating and revoking their upload keys. A project credential is required for administration. Passing a scoped key to an administration client does not grant additional authority.

## Defaults and limits

| Setting | Shared behavior |
| --- | --- |
| Management origin | `https://kompressr.com` |
| Upload-body origin | `https://uploads.kompressr.com` |
| Custom management origin | Also used for uploads unless an explicit upload origin is supplied |
| Management request deadline | 30 seconds, including body reads and retry delays |
| Upload deadline | 600 seconds |
| Eligible read retries | At most two by default; configurable from zero to five |
| Readiness wait | 120 seconds, polling approximately every two seconds |
| Private link lifetime | 3,600 seconds by default; 60–604,800 allowed |
| List page / size | Page 1, 20 items; maximum 100 per page |
| Bulk deletion | 1–100 explicit IDs; retain per-item outcomes |
| JSON response | Maximum 2 MiB |

SDKs validate inputs before dispatch, including positive IDs, UUIDs where required, finite durations, supported enums and UTF-8 metadata limits. The shared ID compatibility range is positive integers up to 9,007,199,254,740,991. JSON booleans and strings are not numeric IDs. Each package documents its duration units.

## Lifecycle and recovery

An accepted upload is still allowed to be processing. Save its ID before waiting. A public asset is ready only after successful processing with a delivery URL; a private asset is ready for signing when the service permits generating a private URL. Failed, unprocessable, unknown and deleting states do not become successful delivery results.

A status response that says `processed` but omits the public delivery URL or denies private URL generation is an invalid response. Readiness waiting stops with that error and retains the asset ID; it does not keep polling an inconsistent completed result.

A wait timeout or cancellation retains the asset ID so the application can check later. Stopping the caller's wait does not cancel server processing. A resumed wait checks the existing asset; it does not upload it again. Private links are generated explicitly and can expire independently of the asset.

Deletion acceptance indicates that cleanup was requested, not that physical removal or cache invalidation has finished. Bulk deletion retains every accepted and failed item, including failures inside an HTTP 200 response. Pagination advances lazily and checks the returned page; it does not promise an immutable snapshot while files change.

## Failure contract

Errors distinguish validation, API, network, timeout, cancellation, invalid-response and processing failures. Preserve the machine-readable code, HTTP status when known, retry delay, safe asset ID and `mayHaveSucceeded` (using idiomatic field naming). Messages omit raw gateway pages, credentials and private URLs.

Only GET network errors and HTTP 429/502/503/504 responses automatically retry. Respect `Retry-After` without shortening it, and stop when the overall request deadline expires. Processing failures, malformed responses and permission denials are not transient read failures. The configured retry count bounds the SDK retry loop. A native library's safe connection recovery for GET requests must be documented and stay within the same deadline; it must never replay a mutation or follow a redirect.

Writes are never automatically replayed. A dispatched write that times out, loses its response or receives malformed successful data can have succeeded. Preserve this uncertainty even when response validation fails. An upload may recover an asset ID only from a parsed `success: true` envelope containing a valid numeric `data.asset_id`; never infer one from broken JSON. A malformed single-asset mutation retains its requested ID. A bulk failure does not arbitrarily select one ID. Cancellation before dispatch sends nothing and does not claim a possible write.

## Credentials and permissions

SDKs use only the supplied credential. The service enforces plan access, project/identity ownership and scopes. Clients preserve denials rather than switching credentials or hiding failures. Omitting scopes uses server defaults (`upload`, `status`, `list`, `private_url`), which exclude deletion. An explicitly empty scopes list is a local validation error and sends no request; a nonempty list replaces defaults. If application permission filtering leaves no scopes, skip issuing the key. The JS SDK enforces this guard starting in 1.0.1; applications using 1.0.0 must validate explicit scopes before issuing keys. Returned provisioning/rotation secrets belong only to the caller and are not included in exceptions or routine logs.

Application authentication, conversation access, secure key storage and durable recovery records remain application responsibilities. A client library cannot establish these boundaries for an application.

## Verification

Each package's parity reference maps these behaviors to its implementation and tests. Verification must exercise real local HTTP boundaries, including multipart ordering, separate origins, delayed bodies, cancellation, malformed mutations, retries, permission denials, platform operations and partial bulk results. Build and install the actual distribution in a clean consumer as part of release checks.

Shared [lifecycle fixtures](fixtures/file-lifecycle.json) provide synthetic baseline records. Local permission fixtures test how a client handles denials; authenticated service checks are required to verify deployed authorization. CI and source tests do not establish registry publication or production verification.
