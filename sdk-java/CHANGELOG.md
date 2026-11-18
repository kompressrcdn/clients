# Changelog

## 0.2.0

- Add optional passthrough uploads, immediate ready File results, and explicit mode confirmation with safe asset-ID recovery.
- Preserve validated asset IDs and write uncertainty on partial upload errors, including HTTP 403/409/500, without replaying uploads.

## 0.1.0

- Java 17+ file and platform APIs aligned with the JS SDK 1.0.0 behavior contract.
- Typed results, streaming file uploads, bounded GET retries, request cancellation and resumable readiness waits.
- Structured errors, safe recovery IDs, ambiguous-write handling and secret redaction.
- Local HTTP regression fixtures and installed-JAR verification.

- Reject explicit empty scoped-key permissions before HTTP, while preserving omitted defaults.
