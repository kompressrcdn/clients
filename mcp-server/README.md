# @kompressr/mcp-server

Kompressr tools for MCP agents: upload files, wait for processing, generate private links, paginate uploads and permanently delete explicit asset IDs. File operations use the separate `@kompressr/sdk` package. Applications can use that SDK directly without starting MCP.

Node.js 22.12+ and 24 are supported.

## Setup

[Create a Kompressr account](https://kompressr.com/signup) and select a plan with API upload access. In [Dashboard → Projects](https://kompressr.com/dashboard/projects), open the project and choose **API Keys**. Keep project/master keys on trusted machines; use scoped keys for individual application or agent runtimes. The project UUID is needed only for listing uploads.

Configure an MCP client to run the package:

```json
{
  "mcpServers": {
    "kompressr": {
      "command": "npx",
      "args": ["-y", "@kompressr/mcp-server@2.0.0"],
      "env": {
        "KOMPRESSR_API_KEY": "YOUR_PROJECT_OR_SCOPED_KEY",
        "KOMPRESSR_PROJECT_ID": "YOUR_PROJECT_UUID"
      }
    }
  }
}
```

`KOMPRESSR_PROJECT_ID` is required for upload listing; upload/status/signing/deletion need only the key. For source builds before publication, follow [CONTRIBUTING.md](https://github.com/kompressrcdn/clients/blob/main/CONTRIBUTING.md), then configure `node` with the absolute path to this package's built `dist/index.js`.

## Configuration and migration

| Setting | Meaning |
| --- | --- |
| `KOMPRESSR_API_KEY` | Opaque project/master or scoped key; API permissions remain authoritative |
| `KOMPRESSR_PROJECT_ID` | Project UUID, required by `list_assets` |
| `KOMPRESSR_API_URL` | Management origin, default `https://kompressr.com` |
| `KOMPRESSR_UPLOAD_BASE_URL` | Upload-body origin override |
| `KOMPRESSR_REMOTE_ALLOWED_HOSTS` | Comma-separated hostnames explicitly allowed to serve private/local remote-source addresses |

Production defaults to `https://kompressr.com` for management and `https://uploads.kompressr.com` for upload bodies. For another deployment, supply `KOMPRESSR_API_URL` and `KOMPRESSR_UPLOAD_BASE_URL` from private runtime configuration. Custom management origins use the same upload origin unless overridden. Origins must use HTTP(S) without credentials, paths, queries or fragments.

Saved configuration remains `~/.kompressr/config.json`:

```json
{
  "api_key": "YOUR_KEY",
  "project_id": "YOUR_PROJECT_UUID",
  "api_url": "https://kompressr.com",
  "upload_url": "https://uploads.kompressr.com"
}
```

Environment settings override saved values. A different environment key does not inherit the saved project or endpoint, which prevents mixing accounts; supply those explicitly for custom origins. A changed management origin re-derives uploads unless an upload override is provided. Old saved `https://api.kompressr.com` values migrate in memory to production. New saves use atomic replacement and permissions 0700 for the directory, 0600 for the file; existing files are not rewritten merely by loading. Keep keys and configuration out of source control.

## File workflow

1. Call `upload_asset` with exactly one `file_path` or `file_url`. Save the returned numeric `asset_id`.
2. Call `wait_for_asset` or `get_asset_status`. Acceptance and a pending URL do not mean the file is ready; use the current processed response only for active assets.
3. Share a public processed URL, or authorize the private recipient in your app and call `generate_private_url` for a fresh expiring link.
4. On wait timeout, resume with the saved ID. Do not upload again to recover from a polling timeout.

API uploads require an eligible paid plan. The free dashboard image trial does not grant API/MCP upload access. Formats, size, video quality and private delivery remain plan/project dependent. The SDK sends all multipart options before the file, as required by the streaming API.

## Tools

Missing/blank filenames in historical status/list records remain valid; listing displays “Unnamed file” without changing response metadata.

All file tools return readable text, a JSON text block and `structuredContent`; failures set `isError`. Numeric IDs must be positive safe integers (single-ID tools also accept numeric strings).

| Tool | Parameters and behavior |
| --- | --- |
| `upload_asset` | Exactly one `file_path` / `file_url`; optional `quality` (`480p`, `720p`, `1080p`, `4k`), `visibility` (`public`/`private`), `private_url_expires_in` (60–604800 seconds), `data` (up to five scalar fields; keys 64/string values 512 UTF-8 bytes, encoded multipart JSON 4096 bytes). Returns acceptance and `ready`. |
| `get_asset_status` | `asset_id`; processing, visibility, deletion state, byte sizes, savings and readiness. |
| `wait_for_asset` | `asset_id`, optional `timeout_ms` (1–120000, default 120000); bounded polling. Timeout/error retains the ID. MCP request cancellation stops the wait, not the server job. Private readiness requires a fresh signing call. |
| `list_assets` | Optional `page` (default 1), `limit` (1–100, default 20), `visibility`, `external_id`, `status` (`pending`, `processing`, `processed`, `failed`, `unprocessable`), `deletion_status` (`active`, `deleting`, `deleted`, `legacy_deleted`), string `data` filters. Lists uploads in the configured project and returns `next_page`. |
| `generate_private_url` | `asset_id`, optional `expires_in` (60–604800 seconds, default 3600), `variant` (`webp`/`avif`, default `webp`). Application must first authorize access. Expiry does not delete the asset. |
| `get_asset_deletion_status` | `asset_id`; processing/deletion state and recorded storage credits. Completed removal does not prove all caches are cleared. |
| `delete_asset` | `asset_id`; permanent deletion, no undo/cancellation. Acceptance starts background cleanup. Requires deletion permission. |
| `bulk_delete_assets` | `asset_ids` (1–100 explicit numeric IDs); per-item outcomes and counts. HTTP success can contain failed items. No delete-all selection. |
| `register` | `email`, `password` (minimum 8 characters); creates an account and sends verification email. Refuses a configured runtime. |
| `verify_email` | `token`; verifies email and saves credentials if issued. Refuses a configured runtime; never returns raw keys in tool output. Paid API access still required. |

Processing status and deletion status are separate. Permanent deletion removes files later; cached, downloaded and offline copies may remain. Retrying the same old ID cannot delete a replacement with a new ID. Bulk deletion preserves partial failure and does not automatically expand or retry a selection. `storage_credited_mb` is recorded storage credit in MB, not a cash refund. Other size fields are bytes.

Read tools carry read-only annotations; deletion tools carry destructive annotations. Annotations describe behavior; server authorization and the MCP client's approval controls enforce access.

## Keys, errors and remote files

Use a scoped key for one customer/agent runtime. The server enforces identity, allowed file types/visibility and action scopes. Default scopes exclude `delete`; provisioning must opt into it. Scoped keys cannot call platform administration or URL Prepend/source optimization. Provision identities and keys from your trusted backend with the SDK's `client.platform` group or the existing platform APIs. No master-key administration tools are added to MCP.

Safe GET requests retry network/429/502/503/504 failures at most twice within a 30-second request deadline and respect `Retry-After`. Uploads default to a 10-minute deadline; writes are never automatically replayed. Structured errors preserve `code`, `kind`, HTTP status and, where relevant, `assetId`/`mayHaveSucceeded`. A dispatched write interrupted or returning malformed JSON/data may have succeeded; inspect the outcome before repeating it. Arbitrary errors and raw gateway bodies are not exposed.

`file_url` downloads on the MCP machine, then uploads a local temporary file. MCP cancellation/disconnection, including stdin EOF, aborts the transfer and is checked again before starting the upload. Before dispatch no asset is created; after dispatch a server-accepted upload cannot be rolled back by client cancellation. It streams to disk with a 2 GiB transport ceiling, five-minute download deadline and at most five redirects. HTTPS cannot downgrade to HTTP. Numeric CIDR checks admit ordinary global IPv6 unicast and conservatively exclude IETF protocol, transition and documentation ranges, including their compressed forms. Each destination resolves to validated allowed addresses used for the connection; private/local destinations require exact hostnames in `KOMPRESSR_REMOTE_ALLOWED_HOSTS`. Redirect targets are checked again. Sources use no Kompressr credentials. Temporary files are restricted and cleaned up on success/failure. The transport ceiling does not override your plan or disk capacity; remote download and upload have separate deadlines. Server-side URL import is not part of this SDK/MCP integration.

See [CHANGELOG.md](CHANGELOG.md) and the [release guide](RELEASING.md). Local HTTP/protocol checks do not certify deployed authentication, processing or CDN behavior. The source verification commands use local fixtures and do not publish packages.
