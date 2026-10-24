# Behavior parity

The Go SDK 0.1.1 implements the public file and platform APIs of JS SDK 1.0.0 against contract snapshot 2026-10-15. Dashboard/session routes are outside SDK scope. This matrix identifies executable local evidence; it does not claim production verification.

| Surface or behavior | Go API | Evidence |
| --- | --- | --- |
| Upload file, selected bytes, native stream; fields first | `UploadFile`, `UploadBytes`, `UploadReader` | `TestPublicFileLifecycle`, `TestUploadBytesSelectedSlice`, `TestReaderClosedAndExactSize`, `TestUploadFileRejectsNamedPipeBeforeOpen` |
| Public/private status, readiness, fresh signing | `GetUploadStatus`, `WaitUntilReady`, `GeneratePrivateURL` | `TestPrivateFileLifecycle`, `TestReadinessStates`, `TestExistingUnnamedAssets` |
| Filtered uploads, lazy bounded pages | `ListUploads`, `IterateUploads` | `TestPaginationAndFilters`, `TestIteratorStopsOnBreakAndRejectsBadPage` |
| Managed asset listing/detail and deletion | `ListAssets`, `GetAsset`, `DeleteAsset`, `BulkDeleteAssets` | `TestDeletionAndMixedBulk`, `TestProjectOnlyRequiredForUploadListing`, `TestWrongAssetID` |
| All nine identity/key operations | `PlatformClient` | `TestPlatformCompleteLifecycle`, `TestExplicitEmptyScopesRejectedBeforeDispatch` |
| Permission errors, no privilege fallback | All methods | `TestPermissionsAndRedaction`, `TestPlatformScopedKeyDenied` |
| Bounded response reads, context cancellation | Request context/options | `TestSlowResponseBodiesBounded`, `TestCancellationAfterWriteDispatch`, `TestNativeContextDeadline`, `TestUploadCancellationClosesBlockedSource` |
| Resume existing ID, never reupload on wait timeout | `WaitUntilReady` | `TestWaitTimeoutNeverReuploads`, upload example `-resume` |
| Bounded eligible GET retry and Retry-After | Transport | `TestReadRetriesOnlyEligibleFailures`, `TestRetryAfterUsesWholeDeadline`, `TestRetryAfterIsNotShortened`, `TestGETNetworkRecovery` |
| Every mutation preserves uncertain outcomes | `Error.MayHaveSucceeded` | `TestMalformedWritesRemainUncertain`, `TestNoMutationReplayOnDisconnect`, `TestBulkResponseMustPreserveOutcomes` |
| Safe ID recovery, missing/unsafe/null fields | Response validation | `TestUnsafeUploadIDRecovery`, `TestStrictResponseValidation`, `TestPlatformMalformedLists` |
| Predispatch validation/cancellation | Inputs/context | `TestInputsRejectedBeforeDispatch`, `TestPreCancelledRequestDoesNotDispatch` |
| Redirect and implicit replay prevention | Controlled transports | `TestNoRedirectsOrCredentialForwarding`, `TestHTTP2ServerWritesUseFreshHTTP1` |
| Public defaults and explicit overrides | `ResolveEndpoints`, `Config` | `TestEndpointsAndConfiguration`, `TestPublicFileLifecycle` |
| Redaction and body-size bounds | `Error`, key/config formatting | `TestPermissionsAndRedaction`, `TestGatewayAndResponseSize`, `TestPlatformCompleteLifecycle`, `TestExplicitEmptyScopesRejectedBeforeDispatch` |
| Exact response field names, including nested records | Typed decoding | `TestExactFieldsPreventFalseReadiness`, `TestExactFieldsAcrossFileResponses`, `TestExactFieldsAcrossPlatformResponses` |
| Shared fixture compatibility | Parsers | `TestSharedContractFixture`; bundled copy checked against repository fixture when present |
| Concurrent client use | Reusable `Client` | `TestConcurrentClient` under race detector |
| Installed module consumer | Distribution ZIP | `go run ./scripts/verify.go` uses a clean cache and local module proxy; its consumer checks upload/readiness, exact response fields and empty-scope validation |

## Go-specific choices

- Methods return typed values and errors synchronously. Contexts provide cancellation; streaming iteration uses Go `iter.Seq2`. There is no browser Blob equivalent; `UploadReader` takes ownership of a sized `io.ReadCloser` instead.
- Zero-valued options mean omitted/default. Pointers distinguish explicit zero retries, an empty display name and absent counters. Nil scopes omit the field; an explicitly empty slice is rejected before dispatch, and a nonempty slice replaces defaults. Empty `ExternalID` is omitted rather than sent as an empty query filter.
- `time.Duration` replaces millisecond numbers. Positive sub-millisecond deadlines are valid. `time.Time` replaces free-form input expiry strings; it serializes in RFC3339 format.
- Responses decode into typed structs using exact, case-sensitive JSON tags recursively and discard unknown fields. Differently cased aliases never override validated fields. Arbitrary metadata/option-map keys and permitted null values retain their meaning. Optional strings collapse missing/empty to an empty Go string. Null values are rejected where the contract expects a non-null field; nullable key timestamps are pointers. Selected optional fields are validated more strictly than the JS implementation, including invalid control characters in filenames and malformed key restrictions.
- Numeric asset IDs retain the shared safe-integer limit despite Go's wider integer range. JSON integer fields must use integer tokens; fractional or exponent spellings are rejected instead of coerced.
- Configured origins and one-time keys have redacted formatting. No arbitrary `RoundTripper` injection is exposed because it could silently replay writes. A cloned `http.Transport` supports ordinary TLS/proxy customization.
- Reads may receive Go's safe transport-level connection recovery in addition to bounded SDK retries, all within the same deadline. Writes use a separate fresh HTTP/1 connection per request to prevent implicit retries; this trades connection reuse for deterministic write safety.
- HTTP redirects are reported as API failures without following them. A write redirect is conservatively uncertain. Native file-opening failures remain native Go errors; remote response/body/network diagnostics use sanitized SDK errors.

The application still authenticates end users, stores credentials and asset IDs, authorizes conversations, and decides how to recover an uncertain write. Server-side permission, plan and storage behavior need separate live verification with dedicated credentials.
