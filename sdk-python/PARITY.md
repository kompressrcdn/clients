# Behavior and verification map

Baseline: JS SDK 1.0.0 and the shared API contract. `tests/test_sdk.py` uses real loopback HTTP servers and synthetic credentials. The lifecycle fixture is copied from `contracts/fixtures/file-lifecycle.json` so source distributions can test independently.

| JS surface / guarantee | Python surface | Regression evidence in `tests/test_sdk.py` |
| --- | --- | --- |
| uploadFile / uploadBytes / uploadBlob | upload_file / upload_bytes / upload_stream | real_file_multipart_separate_origins_and_polling; bytes_view_boundaries_and_snapshot; stream_reads_are_bounded_and_caller_retains_ownership; large_file_streaming_has_bounded_memory (32 MiB file, under 8 MiB traced allocations) |
| getUploadStatus / waitUntilReady | get_upload_status / wait_until_ready | private_lifecycle_and_signing; optional_original_name; terminal_processing_states_with_url; readiness_requires_active_correct_delivery |
| generatePrivateUrl | generate_private_url | private_lifecycle_and_signing; mutations_invalid_json_and_incomplete_shapes_keep_ambiguity |
| listUploads / iterateUploads | list_uploads / iterate_uploads | pagination_filters_lazy_progression; invalid_pagination_and_empty_stop |
| listAssets / getAsset / deleteAsset / bulkDeleteAssets | list_assets / get_asset / delete_asset / bulk_delete_assets | asset_listing_needs_no_project; deletion_states_and_per_item_bulk_results; mismatched_single_asset_response_retains_requested_id |
| All nine platform methods | Same names in snake_case on platform | platform_all_routes_one_time_secrets_and_no_delete_default; platform_explicit_restrictions_and_counter_validation; empty_scopes_rejected_while_omission_keeps_defaults; empty_scopes_rejected_before_async_dispatch |
| Total request and waiting budgets | timeout seconds | slow_response_body_has_total_request_deadline; slow_body_wait_deadline_preserves_id; slow_write_deadline_ambiguity_and_no_replay; retry_after_never_shortened_and_deadline_includes_delay |
| Slow DNS, resolver saturation and TLS origins | Bounded shared DNS workers; sequential deadline-aware address fallback | tests/test_dns.py: sync_dns_timeout_returns_before_os_lookup_finishes_without_late_write; asyncio_run_exits_before_blocked_dns_finishes; dns_capacity_is_bounded_and_waiters_are_cancellable; stalled_first_address_leaves_time_for_healthy_fallback; https_keeps_original_host_sni_and_certificate_validation |
| Cancellation before/after dispatch | CancellationToken and asyncio task cancellation | pre_cancel_sends_nothing; cancel_during_write_retains_sync_metadata; native_task_cancel_keeps_cancelled_semantics_and_write_context; native_wait_cancel_has_wait_code |
| No blind write replay | Structured may_have_succeeded and asset_id | network_read_retries_but_writes_do_not; mutations_invalid_json_and_incomplete_shapes_keep_ambiguity (all eleven mutation families, broken/incomplete responses); unsafe_upload_ids_are_never_recovered |
| Retry permissions and bounds | GET-only retries, no key substitution | eligible_read_retries_and_bounded_attempts; permission_and_non_retryable_errors_preserve_scope |
| Retry metadata through interruptions | Preserve known delay; clear at the next attempt | retry_delay_survives_deadline_and_token_cancellation; native_cancellation_retains_retry_delay; new_attempt_clears_previous_retry_metadata |
| Credential isolation | Redirect refusal, redacted structured errors | redirects_never_follow_or_leak_credentials; error_redaction_and_html_exclusion |
| Input and response validation | Strict typed results and validation errors | invalid_inputs_rejected_before_network; response_size_limit_and_json_nonfinite; compression_bomb_is_rejected_before_expansion; compressed_responses_are_rejected_with_write_context; identity_response_and_compressed_http_error_metadata; readiness_requires_active_correct_delivery |
| Installable distribution | Wheel and sdist, py.typed | scripts/verify.py installs a fresh consumer, checks types and repeats the HTTP suite |

Test method names have the `test_` prefix. Parameterized scenarios use unittest subtests, so a test count does not equal the number of cases.

## Intentional Python differences

- Python uses snake_case methods/options and typed dictionaries. All deadlines and polling intervals use seconds; URL lifetimes remain integer seconds and retry metadata remains milliseconds.
- Both sync and asyncio clients are provided. The sync adapter cannot be used inside an already running asyncio event loop. Native task cancellation remains a subclass of `asyncio.CancelledError`; cooperative cancellation tokens yield `KompressrError`.
- Python has no Blob. `upload_stream` accepts standard regular binary files and BytesIO, rewinds to zero and retains caller ownership. Custom readers/subclasses, pipes and sockets are rejected before reading; arbitrary source code must not block the cancellation loop. File reads are bounded but ordinary filesystem operations can block at the operating-system level. `upload_file` opens/closes its own regular file.
- Mutable bytes/memoryview inputs are snapshotted when the async operation begins executing. Merely creating a coroutine does not execute it. Keep source files unchanged until the upload completes.
- DNS uses at most eight daemon workers; blocked OS lookups retain slots until completion while cancelled callers return promptly. Live connections are capped at 64. Address fallback is sequential, sharing the remaining deadline among remaining addresses, so fallback can be slower than Happy Eyeballs. Admission waiting is part of the request budget.
- Request timeout options allow fractional seconds. Integer IDs and lifetimes reject Python booleans/floats; asset IDs retain the JS safe-integer ceiling. API keys require printable ASCII. Expiry input requires an explicit timezone. Filename validation rejects all control characters.
- Optional response fields receive stricter validation when present (quality, warning, key timestamps and permitted asset types). Future incompatible shapes fail visibly rather than entering typed results.
- HTTP pools live for one operation and all its retries, then close. This simplifies sync/async ownership and cross-thread use but does not reuse connections between separate operations. Environment proxy settings and caller-supplied HTTP transports are not supported.

The suite establishes wire behavior against controlled HTTP fixtures. It does not establish current account entitlements, production scope enforcement, service availability or publishing ownership. Those are separate live/release checks.
