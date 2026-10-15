# Contributing

Use Node.js 22.12+ or 24. Each package has its own manifest, lockfile and release. Build and test from a checkout; no live account or additional service repository is required.

```sh
npm --prefix sdk-js ci --ignore-scripts
node scripts/verify.mjs
```

The root verifier checks public content and the contract snapshot, builds/tests the SDK, installs its packed artifact into MCP with locked dependencies, and verifies MCP. Local HTTP/stdio fixtures cover uploads, readiness, signing, deletion, errors and cancellation. CI runs this flow on Node 22 and 24.

For SDK-only work, run `npm --prefix sdk-js run verify`. For MCP-only work, run `npm --prefix mcp-server run install:local-sdk` followed by `npm --prefix mcp-server run verify`. Repeat installation after SDK changes. The helper supplies the local SDK without changing MCP's registry dependency or lockfile.

After editing files shipped in the SDK, run `node scripts/update-sdk-integrity.mjs` and then the root verifier. This refreshes only MCP's expected SDK artifact checksum. Do not commit tarballs, workspace links or filesystem release dependencies.

Keep usage examples, public types, response validation and the [shared contract](contracts/README.md) aligned. Preserve bounded waits, per-item bulk outcomes, credential redaction and the distinction between accepted and completed work. Add regressions for changed behavior; never automatically replay ambiguous writes.

All tracked content and release artifacts are public. Use reserved example domains and synthetic identities in tests; use local HTTP servers for integration fixtures. Keep live endpoint overrides, credentials, resource inventories and operational reports outside this repository. `node scripts/check-public-content.mjs` checks the source tree; package verification also checks every shipped file.

See package contribution notes for memory checks and [PUBLISHING.md](PUBLISHING.md) for releases. Report bugs through [issues](https://github.com/kompressrcdn/clients/issues) and security concerns through [SECURITY.md](SECURITY.md).
