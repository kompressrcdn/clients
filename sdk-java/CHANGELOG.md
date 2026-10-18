# Changelog

## 0.1.0

- Java 17+ file and platform APIs aligned with the JS SDK 1.0.0 behavior contract.
- Typed results, streaming file uploads, bounded GET retries, request cancellation and resumable readiness waits.
- Structured errors, safe recovery IDs, ambiguous-write handling and secret redaction.
- Local HTTP regression fixtures and installed-JAR verification.

- Reject explicit empty scoped-key permissions before HTTP, while preserving omitted defaults.
