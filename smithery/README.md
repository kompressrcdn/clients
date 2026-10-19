# Install the Kompressr desktop extension

Download the `.mcpb` desktop extension from [Kompressr GitHub Releases](https://github.com/kompressrcdn/clients/releases). Install it in a desktop MCP client to upload files, wait for processing, get delivery links, list uploads and manage deletion.

**Local stdio** means your desktop application starts the Kompressr server as a process on your computer and talks to it through that process's input/output streams. The server then calls Kompressr over HTTPS. Keep the desktop application running while using its tools. The extension does not provide a hosted MCP URL for a web-only client.

## Before you start

- A Kompressr account with a paid plan and an API key from **Dashboard → Projects → API Keys**. For an individual agent, you can use a [scoped key](../guides/chatbot-integration.md#1-create-a-test-user) instead.
- The UUID of the **same project as the key**, shown on its API Keys page. Listing requires it; upload, status and signing do not.
- A current Claude Desktop installation. This bundle requires Node.js **22+**. Claude Desktop supplies a Node runtime; for another client that does not, install Node.js 22 or later.

## Install in a desktop client

The following walkthrough uses **Claude Desktop**. It follows Anthropic's [custom desktop extension instructions](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).

1. Open [Kompressr GitHub Releases](https://github.com/kompressrcdn/clients/releases), choose a **Kompressr MCP** release, and download its `kompressr-<version>.mcpb` file under **Assets**. Choose the desktop bundle rather than a source-code archive.

   Kompressr is also listed on [Smithery](https://smithery.ai/servers/kompressr/kompressr). Check the bundle version when downloading from a directory.
2. In Claude Desktop, open **Settings → Extensions → Advanced settings**. Under **Extension Developer**, choose **Install Extension…**, then select the downloaded file.
3. Review the installation prompt. Enter the full key in **Kompressr API key** and the matching UUID in **Project ID**. These are extension settings; do not paste the key into a conversation.
4. Finish installation. In a new chat, choose **+ → Connectors** and find Kompressr. Check that its ten tools are available, including `upload_asset`, `wait_for_asset` and `generate_private_url`.

Organization administrators can restrict custom extensions. If installation is disabled, ask your administrator to allow it. Claude's **Settings → Extensions → Kompressr** lets you review configuration; its **Developer** settings show connection status and logs. See the [official troubleshooting guide](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).

## Try a private upload

Choose a small, disposable PNG on your computer. Copy its **absolute path** and replace the placeholder in this prompt:

> Use Kompressr to upload the local file at `<absolute path to sample.png>` with private visibility. Keep the returned asset ID, wait for it to be ready, then generate a private URL valid for 3600 seconds. Show me the asset ID, link and expiry. Do not delete anything.

Review and approve the requested tool calls. The expected sequence is `upload_asset` → `wait_for_asset` → `generate_private_url`. Open the final URL and confirm the image loads. A scoped key needs `upload`, `status` and `private_url`, and must allow private uploads.

Next, ask: “List my Kompressr uploads.” You should see the file you just uploaded. If listing fails, check **Project ID** matches the key and the key includes `list`. A scoped key lists only its identity's files. Delete the disposable asset afterward through the dashboard or an explicitly approved deletion tool call with the required permission.

## If something fails

| Symptom | Check |
| --- | --- |
| Installed, but tools are missing | Restart Claude Desktop, check the extension configuration and inspect its connection logs. |
| Runtime fails to start | Check the Node version selected by the client meets 22+. Updating a separate terminal's Node does not necessarily update the desktop runtime. |
| File cannot be read | Use an existing absolute path on the machine running MCP and allow the necessary OS file access. A file attached to a remote chat is not automatically a local path. |
| Upload or signing denied | Check the plan, key scopes, allowed visibility and identity/key status. Reinstalling does not grant permissions. |
| Wait times out | Keep the asset ID and call `wait_for_asset` again. Do not upload the same file again just to wait longer. |
| Private link expired | Ask for a fresh URL for the saved asset ID. Expiry does not delete the file. |

## Limits and other clients

The process can read files allowed by your OS permissions; it has no directory allowlist. Use your host's approval controls and sandbox. A scoped key restricts Kompressr API access, not local file access. URL uploads download through this machine before being sent to Kompressr.

One MCP process uses one credential. See the [chatbot guide](../guides/chatbot-integration.md) for separate users. For a client supporting local stdio but not MCPB, use the [npm configuration](../mcp-server/README.md#setup). Clients accepting only HTTPS MCP URLs need a separately hosted integration or relay; there is no hosted endpoint supplied by this bundle.
