# Kompressr MCP and agent workflows

Use MCP when an agent host should call Kompressr file tools. Use an SDK/custom HTTP adapter when your application backend owns the workflow. This integration skill works without MCP; MCP does not automatically configure your application's file handling.

## Install and configure

The server is a local Node.js process using **stdio**: the host starts it and exchanges protocol messages through standard input/output. It makes outbound HTTPS API calls to Kompressr. It is not a hosted HTTP MCP endpoint, and the website/API origin is not an MCP server URL.

Requires Node.js 22+. A typical host configuration supporting `mcpServers` is:

```json
{
  "mcpServers": {
    "kompressr": {
      "command": "npx",
      "args": ["-y", "@kompressr/mcp-server@2.0.3"],
      "env": {
        "KOMPRESSR_API_KEY": "YOUR_SCOPED_API_KEY",
        "KOMPRESSR_PROJECT_ID": "YOUR_PROJECT_UUID"
      }
    }
  }
}
```

The placeholders are replaced through your host's private configuration/secret mechanism. Do not commit real keys. Host config layout can differ; follow its current documentation. The project ID is needed for upload listing. Prefer a restricted scoped key for an agent where your plan supports it. `npx`/Node must be on the host application's PATH.

For compatible desktop hosts, the [GitHub releases](https://github.com/kompressrcdn/clients/releases) contain an `.mcpb` extension bundle. Follow the [desktop setup guide](https://github.com/kompressrcdn/clients/blob/main/smithery/README.md) and enter your own credentials. Bundled dependencies do not make a local stdio server a remote connector.

Registry identity: `com.kompressr/kompressr`. npm package identity: `@kompressr/mcp-server`. Neither changes the application's Kompressr project/key.

## Tool families

| Tools | Purpose |
| --- | --- |
| `register`, `verify_email` | Account onboarding; verified accounts can upload images within the active free trial or paid-plan limits |
| `upload_asset` | Upload a supported file; preserve its returned asset ID |
| `get_asset_status`, `wait_for_asset` | Check/wait for processing before delivery |
| `list_assets` | List uploads accessible to the configured identity/project |
| `generate_private_url` | Explicitly sign a private ready asset |
| `delete_asset`, `bulk_delete_assets` | Permanently delete explicitly selected authorized assets |
| `get_asset_deletion_status` | Inspect cleanup progress |

Use the host's discovered tool schema for exact arguments; do not invent parameters from SDK method names. The MCP `list_assets` tool follows its own documented upload-list behavior; do not assume it is identical to the raw managed-asset endpoint with a similar name.

## Isolation and verification

One server process loads one credential. A shared chatbot backend should normally select a user-bound SDK/API client per request. Separate users needing distinct MCP credentials require separate processes and appropriate filesystem isolation; a prompt claiming a different user does not change the server's credential.

The process can access files allowed by its host environment. Only expose the files and permissions the intended agent needs. Keep keys out of model context. Permission denials must remain denials; do not switch to a project key to make an agent tool call succeed.

Verify tool discovery in a real host, then an authorized disposable upload → wait → public/private delivery → listing → explicit deletion. Test a restricted key as well. Protocol tests and registry publication do not prove desktop installation or production-account behavior.

Authoritative configuration, input modes and tool details: [MCP README](https://github.com/kompressrcdn/clients/blob/main/mcp-server/README.md).
