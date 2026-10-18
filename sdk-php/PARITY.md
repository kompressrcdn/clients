# PHP behavior and verification

Baseline: JavaScript SDK 1.0.0 and the public HTTP contract. All file operations and all nine platform user/key operations are implemented. Native PHP uses synchronous methods, binary strings or regular file paths, associative result arrays, and a polling cancellation callback. It does not provide a JavaScript Blob or an arbitrary PHP stream adapter.

| Behavior | Implementation | Real HTTP regression |
| --- | --- | --- |
| Upload file/bytes; metadata before file; separate origins | `Client::uploadFile`, `uploadBytes`, `upload` | Multipart ordering, authorization, content length, custom origins |
| Bounded file memory | Native `CURLFile` | 32 MiB file to drain-only fixture, PHP allocation growth below 8 MiB |
| Acceptance and readiness are distinct | `waitUntilReady` | Public/private readiness, processing failures, deleted assets, unusable URLs |
| Save/resume accepted IDs | `getUploadStatus`, wait error context | Wait timeout/cancellation and resumed GET without upload |
| Private signing and expiry | `generatePrivateUrl` | Private readiness, signing JSON fields, malformed signing response |
| Pagination/filtering | `listUploads`, `iterateUploads`, `listAssets` | Encoded filters, lazy requests, page advancement rejection |
| Deletion acceptance and bulk partial failure | `deleteAsset`, `bulkDeleteAssets` | HTTP 202 state, per-item failure in HTTP 200, duplicate ID ordering |
| All platform operations | `PlatformClient` | All nine routes, request bodies, omitted scope defaults, empty/null scopes rejected before HTTP, explicit scopes preserved, issued secret |
| Permission denials are preserved | `Transport` | HTTP 403, same supplied credential, no retry or authority fallback |
| Safe read retries | `Transport::request` | GET network and 429/502/503/504 retry; malformed reads do not retry |
| Deadline includes bodies and backoff | Monotonic deadline, cURL multi polling | Delayed bodies, Retry-After exceeding remaining time, integer overflow saturation, numeric/date/body hints, request/wait deadlines |
| Cancellation | Polling callback and handle removal | Before dispatch, mid-body, one-shot cancellation, callback errors |
| No automatic mutation replay | New HTTP/1.1 connection per attempt, no redirects | Disconnect/redirect writes counted once; target receives no credentials |
| Mutation uncertainty and safe recovery ID | Validation inside mutation request boundary | Malformed uploads/signing/deletion/bulk/provisioning, truncated JSON |
| Input and response validation | `Internal\Validate` | Strict integer IDs, UTF-8, metadata constraints, wrong types, bad URLs |
| Secret handling | Sensitive parameters, safe errors, `IssuedKey` | Credential/URL redaction, argument-free SDK exception traces on PHP 8.1+, safe client/key debug and JSON |
| Installed distribution | `scripts/verify.php` | Composer installs actual TAR; installed copy runs all HTTP regressions |

`tests/fixtures/file-lifecycle.json` is a self-contained copy of the shared fixture. Tests compare it with the repository copy when present. Package verification also lints every PHP source and example, validates Composer metadata, and checks archive membership.

Networking requires libcurl asynchronous DNS support; initialization rejects builds that cannot provide it. Fresh connections sacrifice pooling performance to keep mutation replay behavior predictable. Fast cancellation callbacks and local regular file reads are application responsibilities; a PHP process blocked in application code or filesystem I/O cannot be preempted by this synchronous library.

Local fixtures verify client behavior when the service accepts, denies or fails a request. They do not establish live billing entitlements, deployed tenant isolation, registry ownership, public publication, or production behavior. Before release, use a dedicated service test project to verify those integrations and then install the published version anonymously in a separate application.
