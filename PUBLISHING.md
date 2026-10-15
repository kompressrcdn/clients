# Publishing Kompressr clients

Each package has an independent version, lockfile and release. Extend this guide with native tooling and registry steps when another SDK is implemented.

| Folder | Package | Current version | Order |
| --- | --- | --- | --- |
| `sdk-js` | `@kompressr/sdk` | `1.0.0` | First |
| `mcp-server` | `@kompressr/mcp-server` | `2.0.0` | After its SDK dependency |

## Prepare a release

Use Node.js 22.12+ or 24. Confirm npm scope/package access, version availability and two-factor authentication. GitHub organization membership does not grant npm publish access. Published versions cannot be reused.

```sh
npm login --registry=https://registry.npmjs.org
npm whoami --registry=https://registry.npmjs.org
npm view @kompressr/sdk versions dist-tags --json
npm view @kompressr/mcp-server versions dist-tags --json
```

Update changed package versions, lock roots and changelogs. MCP's SDK dependency, registry URL and integrity must identify the exact SDK release. Keep registry dependencies in release metadata. Run verification on both supported Node lines:

```sh
npm --prefix sdk-js ci --ignore-scripts
node scripts/update-sdk-integrity.mjs
node scripts/verify.mjs
```

Review dependency audits, public content and package contents. Complete authenticated upload → readiness → delivery, private signing, scoped permissions/revocation, pagination, deletion/reupload and recorded-credit checks in a dedicated test project. Configure management/upload origins and credentials outside source control. Preserve release evidence privately; local fixtures do not certify a deployed service.

## Pack and inspect

Finish shipped content before packing. Run these blocks from the repository root in one shell:

```sh
KOMPRESSR_RELEASE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kompressr-release.XXXXXX")"
KOMPRESSR_SDK_VERSION="$(node -p 'JSON.parse(require("node:fs").readFileSync("sdk-js/package.json")).version')"
KOMPRESSR_MCP_VERSION="$(node -p 'JSON.parse(require("node:fs").readFileSync("mcp-server/package.json")).version')"
(cd sdk-js && npm pack --ignore-scripts --json --pack-destination "$KOMPRESSR_RELEASE_DIR" > "$KOMPRESSR_RELEASE_DIR/sdk-pack.json")
(cd mcp-server && npm pack --ignore-scripts --json --pack-destination "$KOMPRESSR_RELEASE_DIR" > "$KOMPRESSR_RELEASE_DIR/mcp-pack.json")
KOMPRESSR_SDK_TARBALL="$KOMPRESSR_RELEASE_DIR/kompressr-sdk-$KOMPRESSR_SDK_VERSION.tgz"
KOMPRESSR_MCP_TARBALL="$KOMPRESSR_RELEASE_DIR/kompressr-mcp-server-$KOMPRESSR_MCP_VERSION.tgz"
npm publish "$KOMPRESSR_SDK_TARBALL" --dry-run --access public --tag next
npm publish "$KOMPRESSR_MCP_TARBALL" --dry-run --access public --tag next
```

Review each artifact's files, version, manifest and integrity. Include runtime outputs, declarations, licenses and public documentation; exclude credentials, local configuration, internal records and test sources. Package verification inspects every shipped file. Reverify and repack after any shipped-file edit; SDK edits also require refreshing MCP's recorded SDK integrity.

## Publish SDK first

```sh
npm publish "$KOMPRESSR_SDK_TARBALL" --access public --tag next
npm view "@kompressr/sdk@$KOMPRESSR_SDK_VERSION" version dist.integrity --json
(cd mcp-server && npm ci --ignore-scripts && npm run verify)
```

Compare registry integrity with the packed SDK metadata and MCP's lock. If publication times out, inspect that exact registry version before retrying. Stop on mismatches. If registry metadata requires a lock refresh, use `npm install --package-lock-only --ignore-scripts`, inspect changes and repeat verification. Repack MCP if its shipped files change.

## Publish MCP and verify installation

```sh
npm publish "$KOMPRESSR_MCP_TARBALL" --access public --tag next
npm view "@kompressr/mcp-server@$KOMPRESSR_MCP_VERSION" version dependencies dist.integrity --json
KOMPRESSR_CANARY_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kompressr-canary.XXXXXX")"
(cd "$KOMPRESSR_CANARY_DIR" && npm init -y && npm install --ignore-scripts "@kompressr/sdk@$KOMPRESSR_SDK_VERSION" "@kompressr/mcp-server@$KOMPRESSR_MCP_VERSION")
(cd "$KOMPRESSR_CANARY_DIR" && node --input-type=module -e 'import {KompressrClient} from "@kompressr/sdk"; console.log(new KompressrClient({apiKey:"import-check-only"}).apiBaseUrl)')
(cd "$KOMPRESSR_CANARY_DIR" && node -e 'console.log(typeof require("@kompressr/sdk").KompressrClient)')
```

Run the installed SDK example and MCP handshake/tools, then repeat the authenticated lifecycle with registry-installed packages and private test configuration. Verify exact installed versions and preserve useful error codes without exposing credentials or signed URLs. Import checks alone do not verify processing or deletion.

## Promote and record

Manifests default to `next`. After acceptance, promote the actual verified versions:

```sh
npm dist-tag add "@kompressr/sdk@$KOMPRESSR_SDK_VERSION" latest
npm dist-tag add "@kompressr/mcp-server@$KOMPRESSR_MCP_VERSION" latest
```

Record package versions, source revision and checksums in release notes. Use package tags such as `sdk-js-v1.0.0` and `mcp-server-v2.0.0`. Update the root README's release status after publication. Do not edit an already published artifact; shipped-file changes require a new version.

CI verifies packages and does not publish. Pushes, GitHub releases and package publication follow maintainer authorization. If a release fails, stop promotion and use an unused version for corrections. Restore a prior dist-tag or pin a compatible version for rollback; accepted uploads/deletions cannot be undone by rolling back a package.

## Future SDKs

Add each implemented SDK's registry name, supported runtime, publish access, native verification/pack/publish commands, installation checks and rollback procedure. Preserve independent releases; do not assume every language uses npm.
