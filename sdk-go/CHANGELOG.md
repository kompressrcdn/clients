# Changelog

## 0.1.0

- Support Go 1.24 and later.
- Initial Go SDK for the complete Kompressr file and platform APIs.
- Streaming uploads, typed responses, lazy listing, bounded readiness waits and context cancellation.
- Safe read retry policy, explicit uncertain-write errors, credential redaction and strict response validation.
- Local HTTP regression tests, module distribution verification and runnable upload/key lifecycle examples.

- Reject explicitly empty upload-key scopes before dispatch; omitted scopes retain server defaults.
- Decode response models using exact JSON field names recursively, preventing case variants from overriding validated lifecycle, pagination, key or delivery data.
