# Changelog

## 0.1.0

- Reject explicitly empty scoped-key permissions before dispatch; omission still uses server defaults.
- Reject nonidentity response encodings before decompression to preserve bounded response memory and write-error context.
- Retain known retry delays on request timeout and cancellation, clearing prior response metadata before another attempt.

- Add typed sync and asyncio clients for uploads, readiness, private signing, listing and asset lifecycle operations.
- Add complete project identity and scoped-key administration.
- Bound DNS worker and connection resources, preserve TLS hostname verification and ensure slow resolver calls cannot delay cancellation or cause late writes.
- Preserve bounded deadlines, read-only retries, cancellation, ambiguous-write context and credential-safe errors.
- Add local HTTP regressions, package consumer verification, runnable examples and publishing guidance.
