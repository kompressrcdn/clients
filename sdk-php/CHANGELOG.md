# Changelog

## 0.1.0

- Support PHP 8.1 and later; omit arguments and object references from SDK exception traces on every supported runtime.
- Add synchronous PHP file upload, status, readiness, private signing, listing and asset deletion APIs.
- Add all project-user and scoped-key administration operations.
- Preserve safe read retries, bounded network waits, cancellation, mutation uncertainty and credential redaction.
- Add real HTTP fixtures, streamed-file memory verification and installed Composer archive checks.

- Reject explicit empty scoped-key permissions before HTTP, while preserving omitted defaults.
- Saturate oversized Retry-After delays before integer conversion, preventing early retries on overflow.
