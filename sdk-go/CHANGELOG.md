# Changelog

## 0.2.0

- Add optional passthrough uploads, immediate ready File results, and explicit mode confirmation with safe asset-ID recovery.
- Preserve validated asset IDs and write uncertainty on partial upload errors, including HTTP 403/409/500, without replaying uploads.

## 0.1.1

- Remove the publishing guide and its README link from the module distribution.
- Verify module archives and installed consumers using the declared SDK version.

## 0.1.0

- Support Go 1.24 and later.
- Initial Go SDK for the complete Kompressr file and platform APIs.
- Streaming uploads, typed responses, lazy listing, bounded readiness waits and context cancellation.
- Safe read retry policy, explicit uncertain-write errors, credential redaction and strict response validation.
- Local HTTP regression tests, module distribution verification and runnable upload/key lifecycle examples.

- Reject explicitly empty upload-key scopes before dispatch; omitted scopes retain server defaults.
- Decode response models using exact JSON field names recursively, preventing case variants from overriding validated lifecycle, pagination, key or delivery data.
