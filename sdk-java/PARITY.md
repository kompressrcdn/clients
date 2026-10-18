# Behavior parity

Baseline: JS SDK 1.0.0 and the repository's shared contract. Java uses typed records, synchronous calls, `Path`/`byte[]` input and `Duration`/`CancellationToken` options. See [API.md](API.md#java-specific-boundaries) for deliberate language differences. Tests are in `src/test/java/com/kompressr/ClientTest.java`; all use local HTTP fixtures.

| Contract | Verification |
| --- | --- |
| `uploadFile`, `uploadBytes`, multipart order/origins, acceptance | `publicFileLifecycleUsesRealMultipartAndCustomOrigins`, `bytesSendSelectedContent`, installed JAR consumer |
| `getUploadStatus`, `waitUntilReady`, private/public readiness | `privateReadinessAndFreshSigning`, `invalidOrTerminalReadinessNeverProducesReadyResult` |
| `generatePrivateUrl`, freshness and TTL | `privateReadinessAndFreshSigning`, validation and mutation regressions |
| `listUploads`, lazy iteration, filters | `listsAreFilteredAndLazyWithIndividualBulkOutcomes` |
| `listAssets`, `getAsset`, `deleteAsset`, bulk partial outcomes | `listsAreFilteredAndLazyWithIndividualBulkOutcomes` |
| All nine platform methods and non-destructive defaults | `allNinePlatformMethodsUseAuthorityAndDefaultNonDestructiveScopes` |
| Empty scopes rejected before HTTP; omitted/default and explicit scopes preserved | `emptyKeyScopesAreRejectedBeforeHttpWhileDefaultsAndExplicitScopesArePreserved` |
| Invalid success/JSON on every mutation | Two parameterized suites across all eleven write operations |
| Safe ID recovery and mismatched IDs | `unsafeUploadIdsAreNeverRecovered`, `mismatchedIdsDoNotReplaceKnownMutationContext` |
| GET retries and Retry-After deadline | `eligibleReadsRetryAndHonorRetryAfter`, `longRetryAfterCannotEscapeDeadline` |
| No hidden mutation replay/redirect follow | `networkDisconnectNeverRetriesDelete`, `redirectsNeverForwardCredentialOrReplayMutation` |
| Blocked DNS caller deadline and no late writes | `blockedDnsCannotEscapeCallerDeadlineOrSendAfterItExpires` |
| Total body deadline, cancellation and uncertain writes | `bodyDeadlineCoversReadsAndWrites`, `cancellationStopsAnInFlightBodyAndKeepsWriteId`, `preCancelledWriteIsNeverDispatched` |
| Wait recovery/cancellation without upload replay | `waitsAreBoundedResumableAndNeverReupload` |
| Permission errors and redaction | `scopesAndRedactionPreserveDenialWithoutCredentialFallback`, `responsesAreBoundedAndNeverExposeGatewayHtml` |
| Client/response validation and bounded JSON | `validationRejectsBeforeAnyHttpRequest`, `oversizedSuccessfulBodyIsRejected` |
| Package installation and bounded file memory | `scripts/verify.sh`: clean consumer, installed JAR, 32 MiB upload under 64 MiB heap |
| Fixture consistency | `fixtureCopyMatchesSharedContract` |

Local fixtures establish SDK behavior, not live plan entitlement, authentication, storage processing or CDN delivery. Before release, run a dedicated project's public/private lifecycle, scoped-user isolation and opt-in deletion checks against the target service.
