# Behavior and verification

The baseline is JavaScript SDK 1.0.0 and the public HTTP contract. This package covers its complete file surface and all nine platform operations. Naming and inputs follow C#: async methods, `TimeSpan`, `CancellationToken`, regular file paths and byte memory. It does not expose JavaScript Blob or arbitrary stream inputs.

| Behavior | Implementation | Real HTTP verification |
| --- | --- | --- |
| Acceptance, readiness, private signing | `KompressrClient`, validated models | Public processing sequence; private wait and explicit signing; separate upload origin |
| Upload fields and bounded file reads | `MultipartFormDataContent`, `StreamContent` | Option-before-file ordering, Content-Length, immutable bytes, 32 MiB file with under 8 MiB total managed allocation |
| Recovery and partial failures | `Transport`, `Validation` | Malformed upload ID matrix, mismatched sign/delete IDs, partial bulk results and count consistency |
| No write replay or redirects | Exact HTTP/1.1, one connection per attempt, redirects disabled | EOF after upload, sign, DELETE, bodyless suspend/revoke; redirected destination receives no request |
| Read retries | SDK GET-only retry loop | HTTP 429/502/503/504, exact EOF attempt count, Retry-After seconds/date/body, original deadline |
| Deadlines and cancellation | Linked cancellation across HTTP/body/backoff/wait | Delayed bodies, cancellation before and after dispatch, saved-ID wait timeout/cancel/resume |
| Scoped authority | Supplied credential only | 403 file/admin denials are preserved; no fallback key or retry; omitted/null scopes use defaults, empty selections fail before dispatch, nonempty selections are preserved |
| Administration | `PlatformClient` | List/create/update/suspend/reactivate users and list/create/rotate/revoke keys |
| Untrusted responses | Explicit shape checks before model deserialization | Private/deleted URL violations, malformed IDs/counters/metadata/keys, oversized JSON and truncated bodies |
| Pagination | Lazy async iterator | Filters, sequential pages, stop on break, reject mismatched returned page |
| Error privacy | Sanitized exceptions; plain model classes | Credential/URL redaction, malformed one-time key results, no raw inner exception |
| Package behavior | `scripts/verify.sh` | Actual NuGet archive installed in an isolated package cache; all HTTP scenarios repeated and examples compiled |

The self-contained fixture in `tests/Kompressr.Sdk.Tests/fixtures/file-lifecycle.json` is compared with the repository fixture when that file is available. Tests use synthetic credentials and loopback servers; there are no live API calls.

## Deliberate language boundaries

The library targets `net8.0`; verification runs its tests and clean consumers on .NET 8 and .NET 10. There are no runtime package dependencies. C# returns the signed link as `PrivateUrl.Url` and pagination as `Page<T>.PageNumber`. Numeric upload filters are strings `"1"` through `"6"`; ordinary callers should use named statuses.

File paths must identify trusted regular local files. .NET's portable attributes do not identify every Unix special file before opening. The client rejects known directories/devices and nonseekable opened sources, but pipes/devices remain unsupported inputs; local opening and filesystem stalls are outside the HTTP deadline. This avoids making cancellation promises about arbitrary blocking streams. Normal file bodies stream asynchronously and are closed on success or failure.

Fresh HTTP/1.1 connections prevent hidden transport replay at the cost of connection setup on each attempt. The one-connection callback also blocks .NET's bodyless-request EOF reconnect behavior. The request deadline includes network connection establishment, response reads and retry delay. It cannot undo a write already accepted by the service, or control independent intermediary retries.

Verification does not establish production authorization, registry account ownership or a published package. Test a dedicated project after release for entitlement, scoped ownership and signed-link access. Application authentication, conversation membership, credential storage and durable recovery receipts remain application responsibilities.
