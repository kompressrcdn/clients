# Direct HTTP API

Use HTTP directly for unsupported SDK languages/runtimes, an explicit developer preference or an HTTP-based automation tool. For application code, read the [custom integration blueprint](custom-integration.md) as well; curl demonstrates the contract but does not implement durable recovery, user authentication or a complete client.

## Origins and authentication

- File bodies: `https://uploads.kompressr.com/api/upload`.
- Status, signing, listing, deletion and identity/key administration: `https://kompressr.com/api/...`.
- Authenticated API calls: `Authorization: Bearer KEY_ID.SECRET` using the complete issued key.
- CDN URLs deliver files; they are not management API endpoints. Preserve signed delivery URLs unchanged.

Use a trusted backend and HTTPS. Do not follow an API redirect with credentials or use automatic POST retry middleware. Keep keys out of URL query strings. The examples below assume POSIX shell, curl and jq, with `KOMPRESSR_API_KEY` already configured securely. Do not enable shell tracing.

## 1. Upload once and save acceptance

Use a small supported image named `image.png` in the current directory. This example requests public delivery intentionally. The directory is private local test storage; use your application database for durable production state.

```sh
: "${KOMPRESSR_API_KEY:?Configure the key in your environment first}"
umask 077
KOMPRESSR_RECEIPT_DIR="$(mktemp -d)"
curl --fail-with-body --silent --show-error --max-time 600 \
  'https://uploads.kompressr.com/api/upload' \
  -H "Authorization: Bearer $KOMPRESSR_API_KEY" \
  --form 'visibility=public' \
  --form 'data={"external_id":"example-image-1"}' \
  --form 'file=@image.png' \
  --output "$KOMPRESSR_RECEIPT_DIR/accepted.json"
```

Stop if curl fails. A dispatched upload can still have succeeded; inspect any valid returned asset ID or reconcile before sending it again. Do not add `--retry` to this write.

**Send every option before `file`.** Options after the file part are not read. Let the HTTP library generate the multipart boundary; do not manually set a bare `Content-Type: multipart/form-data` header.

| Multipart field | Meaning |
| --- | --- |
| `file` | Required binary file part, last |
| `visibility` | `public` or `private`; send explicitly |
| `data` | JSON object, at most five scalar fields; 4,096 encoded UTF-8 bytes maximum |
| `private_url_expires_in` | Optional initial private-link TTL, 60–604,800 seconds |
| `kmp-quality` | Video quality: `480p`, `720p`, `1080p`, `4k`, subject to plan |

Acceptance is a JSON envelope with `success: true` and `data.asset_id`. Validate that shape before using the ID:

```sh
KOMPRESSR_ASSET_ID="$(jq -er '
  select(.success == true) | .data.asset_id |
  select(type == "number") |
  select(. > 0 and . <= 9007199254740991 and . == floor)
' "$KOMPRESSR_RECEIPT_DIR/accepted.json")"
```

If jq fails, stop; do not proceed with an empty ID. Save the ID before waiting. An acceptance URL does not establish readiness. `external_id` is correlation metadata, not a deduplication or authorization guarantee.

## 2. Check readiness on the same ID

```sh
curl --fail-with-body --silent --show-error --max-time 30 \
  "https://kompressr.com/api/upload/$KOMPRESSR_ASSET_ID/status" \
  -H "Authorization: Bearer $KOMPRESSR_API_KEY" \
  --output "$KOMPRESSR_RECEIPT_DIR/status.json"
jq '.data | {id, status, visibility, deletion_status, can_generate_private_url}' \
  "$KOMPRESSR_RECEIPT_DIR/status.json"
```

Validate `success: true`, the expected ID and required data fields. Pending/processing means check again later. A public result is ready only with `status=processed`, active deletion state and a valid current `cdn_url`. Private readiness requires processed/active plus `can_generate_private_url=true`. Failed, unprocessable, unknown or deleted states terminate the wait with an error. Do not let an unknown state poll forever.

An application should poll about every two seconds with a finite total deadline, respecting read retry delays. On timeout keep the ID and resume later. The [blueprint](custom-integration.md) describes how to implement this in the developer's language.

## 3. Sign a private asset

For a separate private upload, send `visibility=private` in step 1, then persist/wait. After authorizing the recipient, sign that private asset:

```sh
curl --fail-with-body --silent --show-error --max-time 30 \
  "https://kompressr.com/api/upload/$KOMPRESSR_ASSET_ID/private-url" \
  -H "Authorization: Bearer $KOMPRESSR_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"expires_in":3600}' \
  --output "$KOMPRESSR_RECEIPT_DIR/private-link.json"
```

The successful envelope contains `data.private_url`, `expires_at`, `expires_in`, `asset_id` and `variant`. Return the link to the authorized caller; keep the response file/logs private. Default TTL is 3,600 seconds, supported range 60–604,800. Optional `variant` is `webp` or `avif`; request AVIF only when that private image variant exists. A pending file can return 409. Signing a public file is not its delivery path.

## Listing and management

| Method and path | Purpose / response |
| --- | --- |
| `GET /api/uploads?project_id=UUID&page=1&limit=20` | Upload records: `success`, `data` array, `page`, `limit`, `total` |
| `GET /api/assets?page=1&limit=20` | Managed assets in key scope: `data` array and pagination; project inferred from key |
| `GET /api/assets/{id}` | Asset/deletion state directly, without a `success/data` wrapper |
| `DELETE /api/assets/{id}` | Permanent deletion; 202 accepted or 200 already complete, state directly |
| `POST /api/assets/bulk-delete` | Body `{"asset_ids":[123,124]}`; per-item `results` and `counts` directly |

IDs above are illustrative, not a selection to execute. Delete only the user's explicit authorized assets. Bulk input is 1–100 positive IDs and up to 8,192 body bytes; inspect each `accepted` result even when HTTP status is 200. Check deletion progress through asset detail.

Upload filters include visibility, numeric processing status, `external_id` and scalar `data.{key}` filters. Both lists support `deletion_status=active|deleting|deleted|legacy_deleted`. Pages start at 1; maximum page size is 100. Use an HTTP query builder for scalar values rather than concatenating user input. Do not send an upload project's UUID from a different tenant to widen a scoped key's access.

## Platform API

Requires the project/master key, an eligible project and scoped-key plan. Paths are relative to `https://kompressr.com`:

| Method and path | Purpose |
| --- | --- |
| `GET /api/platform/project-users` | Paginated `project_users` |
| `POST /api/platform/project-users` | Create/find by stable `customer_user_id`; optional display name/metadata |
| `PATCH /api/platform/project-users/{user}` | Update display name/metadata |
| `POST /api/platform/project-users/{user}/suspend` | Suspend identity and revoke keys; files remain |
| `POST /api/platform/project-users/{user}/reactivate` | Reactivate identity; old secrets remain revoked |
| `GET /api/platform/project-users/{user}/upload-keys` | Key records; no raw secrets |
| `POST /api/platform/project-users/{user}/upload-keys` | Issue one-time secret; requires `name` |
| `POST /api/platform/project-users/{user}/upload-keys/{key}/rotate` | Replace secret; securely store the one-time response |
| `POST /api/platform/project-users/{user}/upload-keys/{key}/revoke` | Revoke key |

Create/find user body: `{"customer_user_id":"customer-123","display_name":"Example customer"}`. Derive the actual customer ID from your authenticated application session. Response: `success`, `created`, `project_user`; 201 means newly created and 200 can mean existing.

Example private-only key policy: `{"name":"Chat files","scopes":["upload","status","list","private_url"],"allowed_visibility":"private"}`. The response contains one-time `api_key` plus management identifiers; do not print it or expose it to the model. Nonempty `scopes` replaces defaults. **Reject an explicit empty scopes list before sending: the API treats it as defaults, not no permissions.** Omitted/empty `allowed_asset_types` separately means all supported types. Use the documented numeric asset-type identifiers when restricting types, never guessed file-name enums.

### Restrict file families

`allowed_asset_types` uses these numeric identifiers, also used by managed-asset `kind`:

| ID | File family |
| --- | --- |
| 1 | Images |
| 2 | PDF |
| 3 | Video |
| 4 | CSS |
| 5 | JavaScript |
| 6 | Fonts |
| 7 | SVG |
| 8 | HTML |
| 9 | JSON |
| 10 | XML |

For example, add `"allowed_asset_types":[1,2]` to the key policy to allow images and PDFs. SVG is a separate family. This policy narrows the key; it does not grant formats excluded by the subscription. It selects families, not individual filename extensions. If filtering produces no allowed families, do not issue the key: sending `[]` would allow all supported types.

## Errors and complete schemas

Handle non-2xx statuses and failed envelopes even under HTTP 200. Preserve safe codes/status/retry delay without logging raw credential/private-link responses. A 401/403 is not fixed by automatic retries or switching to a stronger key. A 404 can mean missing or outside scope. A write timeout may follow acceptance.

Endpoint-specific shapes, errors and fields: [OpenAPI contract](https://github.com/kompressrcdn/clients/blob/main/contracts/kompressr-api.yaml). [Recovery](lifecycle.md) and [custom client behavior](custom-integration.md) apply equally to raw HTTP.
