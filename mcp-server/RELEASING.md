# Releasing the MCP server

Follow the [clients publishing guide](https://github.com/kompressrcdn/clients/blob/main/PUBLISHING.md). MCP has its own version and requires the SDK version declared in package.json. Publish that SDK first, verify MCP installation against its registry lock, then publish the verified MCP tarball.

Before SDK publication, root verification uses a packed local SDK while keeping the release dependency and other locked versions unchanged. After publication, run `npm ci --ignore-scripts` and `npm run verify` in this package directory to verify standalone installation.

Check Node.js 22/24, tool schemas, cancellation, upload/readiness, private signing and deletion. Keep authenticated service configuration and credentials outside this repository. Registry canaries and authenticated lifecycle checks supplement local fixtures. Rollback selects a compatible package version or registry tag; it cannot undo accepted file operations.
