# Ruby behavior and verification

The compatibility baseline is the JS SDK file API and the shared [SDK behavior contract](../contracts/sdk-behavior.md). Ruby uses synchronous methods, String-keyed hashes, native integer IDs and a lazy Enumerator. It supports regular local-file paths and binary Strings; there is no arbitrary stream method or framework adapter.

| Behavior | Implementation | Real-boundary regression coverage |
| --- | --- | --- |
| Separate management/upload origins and field-before-file multipart | `Client`, `Multipart` | Multipart body/header inspection and separate servers |
| Accepted upload, resumable wait, private signing | `Client` | Pending→processed, private readiness/signing, terminal states, early request deadline vs wait deadline |
| Strict lifecycle fields and exact matching | `Validation` | Case variants cannot override status/IDs; private/deleted delivery URL contradictions fail |
| Listing/filtering/lazy pages | `Client` | Encoded filters, no eager request, page progression, total/empty termination |
| Single/bulk deletion | `Client`, `Validation` | Requested ID retention, accepted deletion state, duplicates and mixed outcomes |
| Nine identity/key methods | `PlatformClient` | Real HTTP path/method/body checks, nullable metadata, state transitions, issuance/rotation/revocation |
| Supplied credential and denied authority | `PlatformClient`, `Transport` | HTTP 403 retained without retry/escalation; secret redaction |
| Empty scopes reject; omission selects defaults | `PlatformClient` | Empty scopes sends zero requests; omitted scopes absent on wire |
| Retry and mutation uncertainty | `Transport` | Eligible GET retries, attempt limits, EOF, no mutation replay/redirect, malformed writes |
| Retry-After and safe errors | `Context`, `Transport` | Huge delays, HTTP date/JSON fallback, cancellation/backoff context, raw response redaction |
| Total deadlines and cancellation | `Context`, `Network` | Delayed headers/body/TLS, pre/postdispatch cancellation, DNS no-late-write and slot exhaustion |
| TLS trust/hostname/SNI | `Network` | Locally generated CA/leaf, accepted hostname, mismatch and untrusted CA rejection |
| Bounded HTTP parsing | `Wire` | Content-Length, chunked/trailers, close-delimited, interim statuses, framing conflicts, EOF, size/line limits |
| Early upload rejection | `Wire` | HTTP/TLS denials before the body is consumed, partial response headers and informational responses during upload |
| No response decompression | `Wire` | Gzip expansion fixture rejected before decompression; compressed errors retain status/delay |
| Unicode response safety | `Transport`, `Validation` | Raw invalid UTF-8 and escaped lone surrogates remain typed errors for success and denial |
| Streaming and cleanup | `Multipart`, `Network` | 32 MiB file upload, bounded retained String memory, repeated cancellation, bounded DNS threads, process exit |
| Concurrent requests | `Transport`, `Capacity` | Separate credentials remain isolated; shared-client calls retain their own state; connection admission honors cancellation and deadlines |
| Application examples | `examples/` | Private upload and Rails service execute against HTTP fixtures; recovery IDs are saved before waiting, including uncertain-upload recovery; CLI recovery files are private and never overwritten |
| Actual distribution use | `scripts/verify.rb` | Strict gem build, allowlist check, clean gem home install, same HTTP regressions and example execution |

The CI matrix targets MRI Ruby 3.2, 3.3, 3.4 and 4.0. Run the native verifier on each before release; it checks source and a clean installation of the `.gem`. Tests generate temporary TLS certificates locally; no signing material is committed. The large-file test measures retained String memory while uploading a 32 MiB regular file, with garbage collection between samples; its bound is 8 MiB above baseline. This is a bounded-buffer regression, not a claim about total process RSS or every runtime's allocator.

The SDK is synchronous and has no automatic native-library recovery beyond its explicit GET retry loop. DNS admission is bounded at eight workers and connection admission at 64 attempts. A blocked OS resolver retains a slot until it finishes but cannot issue a late request. Filesystem stalls and Ruby thread scheduling remain OS/runtime boundaries. See [API.md](API.md#errors-and-timing) for exact limits and supported runtimes.

These local fixtures establish client behavior, not deployed plan entitlement, tenant isolation or registry publication.
