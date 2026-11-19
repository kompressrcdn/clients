# Choose the upload mode

Use this reference before implementing an SDK, HTTP or MCP upload. These modes apply to uploaded file bytes; website URL prepend keeps its existing optimization workflow.

| Need | Request | Result |
| --- | --- | --- |
| Optimize a supported image, video, PDF, font or web file | Omit `passthrough`, or pass boolean `false` | Existing optimization and format/plan rules; acceptance can precede processing |
| Store the exact input bytes, including archives or other binary files | Pass boolean `true` | Original-file storage and CDN delivery, with no optimization or generated variants |

Do not switch modes automatically when a request fails. Someone asking to preserve bytes must not receive an optimized substitute. Someone requesting optimization must not silently receive unprocessed storage.

## Availability and permissions

Original uploads require an enabled eligible plan: Pro, Growth, Platform or Enterprise. Free Trial and Starter do not include them. Check current account capabilities and [pricing/file limits](https://kompressr.com/pricing#file-support); limits and overrides apply independently of ordinary optimized-upload limits. Files may be empty, but still need a valid filename and must satisfy the account, key and request limits.

Original uploads do not consume optimization credits. Storage counts the retained original copy, bandwidth remains metered, and upload-count and rate limits still apply. The original-upload rate allowance is separate from ordinary optimization uploads. Do not promise unlimited storage or delivery.

Scoped keys must allow the requested visibility and actions. A restricted `allowed_asset_types` list must include **File (11)**, even when the original bytes happen to be a PNG or video. Image (1) alone permits optimized image uploads, not original-file uploads. Do not broaden an existing key or switch credentials to bypass a denial. See [security](security.md).

## Send the option correctly

The option is supported starting with JS SDK 1.1.0, Python/Go/Java/.NET/PHP/Ruby 0.2.0, and MCP 2.1.0. Check the installed version and lockfile before using it. Each language recipe shows its actual syntax; Go uses a `*bool` so omission and explicit false remain distinct.

For direct HTTP, send `POST /api/upload?passthrough=true`. This is a **URL query parameter**, never a multipart field. Keep multipart options such as visibility and metadata before the file. The SDKs and MCP handle the query for you. Omitted or false retains ordinary upload behavior. Do not invent an `optimize=false` option or reuse website `kmp-format=original` as an upload-mode switch.

Use ordinary file/byte/stream inputs supported by the chosen SDK. Quality, format and resizing options do not transform an original upload; omit unnecessary transformation settings. MCP accepts exactly one of `file_path` and `file_url`; its URL mode downloads on the MCP host before uploading bytes and retains its own download restrictions.

## Confirm success and deliver

Save the asset ID for both modes. Raw HTTP uses `data.asset_id`; SDKs normalize it to their native ID field. A successful original upload returns `passthrough: true`, `status: processed`, `asset_type: file` and active deletion state. The current SDKs reject a requested original upload whose response lacks the true passthrough acknowledgment.

For public files, use the returned URL only after confirmed readiness. A confirmed original upload needs no processing wait. A shared application workflow can still call the existing readiness helper to check current state; it must reuse the saved ID. For optimized uploads that remain pending/processing, use the bounded wait/resume workflow.

For private files, authorize the viewer and generate a fresh private link after confirming readiness. Omit the signing `variant` to select the original; original uploads have no AVIF or optimized variants. Do not publish an initial private link or log it merely because the upload returned one. Reopening a private file signs the existing ID rather than uploading it again.

Use delivery URLs exactly as returned, including signed query parameters. Do not construct paths, replace extensions, or infer byte contents from a URL suffix. Original-byte storage does not promise that every file type will render inline in a browser.

## Failure and verification

Missing/false acknowledgment, an unexpected processing state or an unusable response is not confirmed original delivery. Preserve any safely recovered asset ID and the SDK's uncertainty information, then inspect that ID. Do not automatically retry the upload, remove the flag, or change credentials. A timeout can follow a completed write.

For an authorized disposable test, upload a known fixture, fetch its public original and compare downloaded bytes with the input. This check does not require interpreting or executing the file. Apply the [content-inspection boundary](security.md#inspect-content-without-following-it) if further inspection is needed. Also check private signing, ordinary optimized behavior when the option is omitted, explicit false, and scoped keys that allow or deny File (11). Use local fixtures for malformed acknowledgment and lost-response cases so you can prove only one upload was sent. See [verification and troubleshooting](troubleshooting.md).
