# Publish the Smithery bundle

These instructions are for maintainers. To use the published server, follow [desktop installation](README.md).

## Build from the published npm release

Run from the repository root using the manifest and MCP lockfile for the release. Finish the npm package verification and publication described in [PUBLISHING.md](../PUBLISHING.md) first. The bundle uses the compiled npm artifact and locked production dependencies; it does not rebuild the released program.

```sh
KOMPRESSR_SMITHERY_DIR="$(mktemp -d)"
mkdir "$KOMPRESSR_SMITHERY_DIR/bundle"
npm pack @kompressr/mcp-server@2.0.0 --ignore-scripts --pack-destination "$KOMPRESSR_SMITHERY_DIR"
tar -xzf "$KOMPRESSR_SMITHERY_DIR/kompressr-mcp-server-2.0.0.tgz" -C "$KOMPRESSR_SMITHERY_DIR/bundle" --strip-components=1
cp mcp-server/package-lock.json "$KOMPRESSR_SMITHERY_DIR/bundle/package-lock.json"
npm --prefix "$KOMPRESSR_SMITHERY_DIR/bundle" ci --omit=dev --ignore-scripts
cp smithery/manifest.json smithery/.mcpbignore "$KOMPRESSR_SMITHERY_DIR/bundle/"
npx --yes @anthropic-ai/mcpb@2.1.2 validate "$KOMPRESSR_SMITHERY_DIR/bundle/manifest.json"
npx --yes @anthropic-ai/mcpb@2.1.2 pack "$KOMPRESSR_SMITHERY_DIR/bundle" "$KOMPRESSR_SMITHERY_DIR/kompressr-2.0.0.mcpb"
sha256sum "$KOMPRESSR_SMITHERY_DIR/kompressr-2.0.0.mcpb"
```

For future releases, update the package version, matching lockfile, manifest version/tool metadata and output filename together. Keep the npm and bundle versions aligned. Preserve third-party licenses. Do not pack the source checkout or include development tooling. The ignore file excludes dependency tests, local configuration and nested artifacts; MCPB also excludes lockfiles and TypeScript declarations during packing.

## Verify the archive

Extract the final `.mcpb` into a new directory and inspect every archived file. Confirm runtime files match the reviewed npm artifacts. Scan dependency files too: secret scanners may skip `node_modules` by default. Review dependency audit results and retain licenses. Compare the bundled dependency versions with the MCP lockfile.

Validate the manifest and its resolved launch configuration: required API key, optional empty project ID, sensitive-field handling, absolute entry point and production origins. Start the extracted runtime from a different working directory on Node 22 and 24. Confirm server name `kompressr`, the intended version and all ten tools with correct annotations.

Exercise local and URL uploads, multipart options, acceptance/readiness, private signing, listing/pagination, single and mixed bulk deletion, permission errors, request cancellation and temporary-file cleanup through real stdio and local HTTP fixtures. These fixtures verify package integration, not a deployed service.

Install through an MCPB-capable application to verify its configuration UI and runtime selection. In a dedicated live project, verify upload → readiness → actual delivery, private signing, listing, permission denials and deletion progress. Use only disposable assets. Never publish test credentials or signed URLs. Inspect the actual bundle downloaded from Smithery and repeat its installation smoke test.

`mcpb validate` validates the manifest. `mcpb verify` verifies a bundle signature. Neither command establishes runtime or service correctness. Record any client/OS or live checks deferred by the release owner.

## Publish

Smithery CLI 1.2.0 forwards the manifest's tool summaries directly into its release card, but the publishing API requires full tool input schemas. That CLI path fails validation for this valid MCPB manifest. `publish.mjs` uses the documented multipart release API with `release-payload.json`, whose full tool schemas and annotations were captured from the released runtime. It authenticates through `SMITHERY_API_KEY` or the existing Smithery CLI login without printing the credential. It requires `unzip` and Node.js 22.12+.

Regenerate the release payload from the exact runtime's initialization and `tools/list` responses when releasing a new version; keep its configuration schema aligned with the manifest. The helper checks version and tool-summary agreement but does not replace runtime or archive verification. `--check` validates local inputs without authentication or publication. If a write times out, inspect Smithery releases before retrying; the helper does not replay writes.

```sh
npx --yes smithery@1.2.0 auth login
npx --yes smithery@1.2.0 namespace list
node smithery/publish.mjs "$KOMPRESSR_SMITHERY_DIR/kompressr-2.0.0.mcpb" kompressr/kompressr --check
node smithery/publish.mjs "$KOMPRESSR_SMITHERY_DIR/kompressr-2.0.0.mcpb" kompressr/kompressr
```

Use a namespace owned by the publishing account. Check the resulting listing, metadata, configuration fields, version and downloadable artifact. Compare the downloaded archive with the artifact you tested. Complete the listing's Settings → Verification checklist when available; publication alone does not establish official-vendor verification.

The bundle does not expose an HTTPS MCP endpoint. Clients requiring a remote URL need a separate hosted integration or a relay. Smithery Uplink is an optional relay whose availability depends on its host process and network connection.

References: [Smithery publishing](https://smithery.ai/docs/build/publish), [release API](https://smithery.ai/docs/api-reference/servers/publish-a-server), [MCPB manifest](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md), [MCPB CLI](https://github.com/modelcontextprotocol/mcpb/blob/main/CLI.md), [Smithery Uplink](https://smithery.ai/docs/use/uplink).
