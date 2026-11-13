# Changelog
## Unreleased

- Add optional passthrough uploads, immediate ready File results, and explicit mode confirmation with safe asset-ID recovery.
- Preserve validated asset IDs and write uncertainty on partial upload errors, including HTTP 403/409/500, without replaying uploads.


## 0.1.0

- Support MRI Ruby 3.2 and later, including isolated installation of required runtime gems.
- Initial Ruby client for file upload, readiness, signing, listing, iteration and asset deletion.
- Project-user administration and scoped-key issuance, rotation and revocation.
- Total request deadlines, cooperative cancellation, bounded reads and streaming regular-file uploads.
- Safe GET retries, mutation uncertainty, strict response validation and explicit secret access.
- Rails-compatible service example, native package verification and public release instructions.
