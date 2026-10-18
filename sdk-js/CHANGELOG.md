# Changelog

## 1.0.1

- Support Node.js 22.0 and later.
- Reject explicitly empty scoped-key permissions before dispatch. Omitted scopes retain server defaults; nonempty selections replace defaults.

## 1.0.0

- Initial Node.js JavaScript/TypeScript SDK with ESM/CommonJS exports and declarations.
- File-backed, bytes and Blob uploads; bounded readiness waiting; public and private delivery; paginated listings; single/bulk deletion and identity/key administration.
- Production defaults and explicit custom management/upload origins.
- Typed validation/errors, cancellation, finite deadlines and bounded read retries. Ambiguous writes are never automatically replayed.
- Safe asset-ID recovery, optional historical filenames and efficient selected-view byte uploads.
