# Troubleshooting and verification

Start with the failing stage: setup, upload acceptance, processing, delivery, authorization or cleanup. Preserve the asset ID and safe error code/status. Never paste API secrets, signed URLs or raw key-issuance responses into public diagnostics.

## Diagnose by symptom

| Symptom | Check and next action |
| --- | --- |
| SDK/package not found | Verify the official package coordinate and supported runtime. If no compatible official SDK exists, use the [custom HTTP blueprint](custom-integration.md), not a guessed package |
| Constructor/runtime failure | Check language minimum, PHP cURL DNS support, Ruby MRI/OpenSSL, Node server runtime and package dependencies |
| 401 | Full current key, correct environment and intended API origin; do not print the key |
| 403 | Plan access, active project/identity, scopes, visibility/type policy and endpoint authority |
| Cross-user asset returns 404 | Treat as possible intended isolation; inspect app owner mapping, never fall back to master automatically |
| Upload URL exists but returns 404 | Check processing on the saved ID; acceptance can precede delivery |
| Pending beyond the caller's wait | Keep ID, schedule another check; investigate plan/processing status; do not reupload merely because waiting timed out |
| Failed/unprocessable | Inspect supported format/content, plan limits and safe service error; do not relabel as ready |
| Processed response lacks public URL/private readiness | Invalid response; preserve ID and investigate rather than fabricate a URL |
| Private link expires or returns not found | Reauthorize viewer, check asset state and request a fresh link; do not edit expiry/signature |
| Image/format/size differs from expectation | Actual response content type, browser negotiation, generated variants, exact plan and supported `kmp-` controls |
| 429 / processing allowance reached | Honor retry delay, back off within deadline and inspect usage/plan. A processing allowance is not solved by rapid retries |
| Large file fails | Application proxy/body limits, regular-file input, request deadline, type/size/duration limits and credential policy |
| Lost or malformed upload response | Preserve uncertainty and any safely returned ID; reconcile instead of automatic replay |
| Browser CORS failure | Confirm intended backend-mediated versus direct scoped flow; CORS changes do not establish auth or plan access |
| URL prepend fails | Exact project/domain verification, reachable source URL, full unencoded original URL and preserved source query |
| Website appears unchanged | First-request fallback/cache state, actual requested URLs and production build; compare repeated delivery and returned bytes |
| Broken scripts/fonts after prefixing | Emitted paths, relative references, module/font CORS, CSP, integrity hashes and double optimization |
| Some bulk deletions failed under HTTP 200 | Inspect each result/code and retry only the intended unresolved selection |
| File still accessible after deletion | Cleanup state versus edge/browser/downloaded copies; URL-prepend origin may regenerate content |
| Reactivated identity still denied | Old revoked keys stay revoked; provision a new authorized key |

## Acceptance checks for an upload integration

Use a test project and files the user has authorized. Local fixtures can test adapter behavior without live credentials; deployed permission/processing checks require the real service.

1. Install from the package registry in the supported runtime, or compile the custom adapter using its actual HTTP library.
2. Upload one supported public test file. Confirm exactly one upload request and persist the numeric ID before waiting.
3. Verify pending is not presented as successful delivery. After readiness, open the current URL and inspect the file.
4. Exercise a short wait timeout and resume using the same ID. Check that no duplicate upload occurs.
5. Upload privately, wait, authorize and sign. Confirm no public URL is exposed. Reopen through a newly signed link after the previous one expires.
6. List through the correct project/identity and page through enough records to exercise pagination where relevant.
7. With explicit deletion authority, delete selected disposable files and inspect cleanup progress. Preserve any partial bulk failures.
8. For multi-user apps, run the two-identity isolation checks in [security](security.md), including denied actions and app conversation membership.

For custom HTTP, additionally test multipart order, response envelopes, bounded bodies, retry deadlines, cancellation and ambiguous writes from the [adapter contract cases](custom-integration.md).

## Acceptance checks for an existing website

1. Verify the source domain/project, then prefix one representative asset.
2. Confirm both original and prefixed URLs fetch the intended content. Inspect first and subsequent requests separately.
3. Check actual MIME type, bytes, image dimensions/appearance, fonts and relevant PDF/video/script behavior.
4. Test the production build's relative assets, lazy chunks, CSP/CORS and integrity requirements.
5. Confirm normal pages/API/navigation still use their intended endpoints.
6. Compare representative performance and usage against the original route. Expand gradually and retain a configuration rollback.

## Moving an existing application

Keep original asset ownership records and URLs during a trial rollout. Choose public/private classification before migration. Map old application records to new asset IDs only after verified acceptance; do not replace every URL with an unready acceptance URL.

A URL-prepend rollout keeps the source host. An upload migration moves bytes into a separate storage workflow and needs an explicit transfer/resume plan. There is no implied server-side import-by-URL endpoint or automatic database migration. Do not crawl third-party/private sources without the user's authorization.

For rollback, restore the application's previous URL/configuration path and stop new writes to the changed route. Separately decide what to do with existing uploaded assets; rollback does not imply permission to delete them.

## Reporting and support

Report the installed version/runtime, operation, safe error code/status, approximate time and whether a request may have succeeded. Include only non-sensitive reproduction material. Keep a private asset ID/project reference for support if needed; do not post live secrets or signed links.

Use [GitHub issues](https://github.com/kompressrcdn/clients/issues) for reproducible client defects and the repository's [security policy](https://github.com/kompressrcdn/clients/blob/main/SECURITY.md) for sensitive reports. [Kompressr contact](https://kompressr.com/contact) covers account/service questions. Distinguish what was reviewed, tested locally and verified with an actual account.
