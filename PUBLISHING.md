# Publishing Kompressr clients

Release each package independently. Commands in this guide run from the clients repository root unless a package guide says otherwise.

| Package | Release version | Registry and instructions |
| --- | --- | --- |
| JavaScript / TypeScript | `1.0.1` | npm: `@kompressr/sdk`; follow the steps below |
| MCP server | `2.0.1` | npm: `@kompressr/mcp-server`; publish after the JS SDK |
| Python | `0.1.0` | [PyPI: `kompressr-sdk`](sdk-python/PUBLISHING.md) |
| Go | `0.1.0` | [Go module: `github.com/kompressrcdn/clients/sdk-go`](sdk-go/PUBLISHING.md) |
| Java | `0.1.0` | [Maven Central: `com.kompressr:kompressr-sdk`](sdk-java/PUBLISHING.md) |
| C# / .NET | `0.1.0` | [NuGet: `Kompressr.Sdk`](sdk-dotnet/PUBLISHING.md) |
| PHP | `0.1.0` | [Packagist: `kompressr/sdk`](sdk-php/PUBLISHING.md) |
| Ruby | `0.1.0` | [RubyGems: `kompressr-sdk`](sdk-ruby/PUBLISHING.md) |
| Desktop MCP bundle | `2.0.1` | [Smithery: `kompressr/kompressr`](smithery/PUBLISHING.md); publish after npm MCP |

## Common release requirements

Use a reviewed, committed source revision. Push that revision before creating public source tags or announcing links to new documentation. Review `git status` first so the release does not accidentally include unrelated work. Go tags and the PHP split include committed files only.

Confirm publisher access to each registry. A GitHub organization does not grant registry ownership, and a missing package name is not a reservation. Java needs a verified `com.kompressr` namespace plus a GPG key. PHP needs a package-only public mirror with `composer.json` at its root. Their guides include setup and release commands.

Run each package's native verifier and inspect the produced distribution. All-package setup and verification are in [CONTRIBUTING.md](CONTRIBUTING.md). Complete a disposable-project check for public/private upload, saved-ID readiness, delivery, signing, scope denial and deletion before announcing availability. Keep credentials and run results outside the repository. Tests against local fixtures do not establish production authorization.

Finish README content and changelogs before packing. Public READMEs describe installation and use; release evidence belongs in the release record. Never replace an existing published version or move its tag. If a publish request times out, check the registry for that exact version before retrying.

## Prepare a release

Use Node.js 24 for release tooling; the published packages support Node.js 22 and later. Confirm npm scope/package access, version availability and two-factor authentication. GitHub organization membership does not grant npm publish access. Published versions cannot be reused.

```sh
npm login --registry=https://registry.npmjs.org
npm whoami --registry=https://registry.npmjs.org
npm view @kompressr/sdk versions dist-tags --json
npm view @kompressr/mcp-server versions dist-tags --json
```

Update changed package versions, lock roots and changelogs. MCP's SDK dependency, registry URL and integrity must identify the exact SDK release. Keep registry dependencies in release metadata. Require the full Node CI matrix to pass. Use Node 24 for local release verification:

```sh
npm --prefix sdk-js ci --ignore-scripts
node scripts/update-sdk-integrity.mjs
node scripts/verify.mjs
```

Review dependency audits, public content and package contents. Complete authenticated upload → readiness → delivery, private signing, scoped permissions/revocation, pagination, deletion/reupload and recorded-credit checks in a dedicated test project. Configure management/upload origins and credentials outside source control. Preserve release evidence privately; local fixtures do not certify a deployed service.

## Pack and inspect

Run these blocks from the repository root in one shell. `KOMPRESSR_RELEASE_DIR` is a temporary output directory for the exact tarballs you inspect and upload; it is not an application setting or secret. Keep it until registry verification is complete:

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

Record package versions, source revision and checksums in release notes. Use package tags such as `sdk-js-v1.0.1` and `mcp-server-v2.0.1`. Do not edit an already published artifact; shipped-file changes require a new version.

CI verifies packages and does not publish. Pushes, GitHub releases and package publication follow maintainer authorization. If a release fails, stop promotion and use an unused version for corrections. Restore a prior dist-tag or pin a compatible version for rollback; accepted uploads/deletions cannot be undone by rolling back a package.

## Additional language releases

Each native SDK has its own release procedure. These packages do not depend on npm publication and can be released independently after verification.

| Package | Registry coordinate | Release guide |
| --- | --- | --- |
| Python | PyPI `kompressr-sdk` | [Python publishing](sdk-python/PUBLISHING.md) |
| Go | `github.com/kompressrcdn/clients/sdk-go` | [Go publishing](sdk-go/PUBLISHING.md) |
| Java | Maven Central `com.kompressr:kompressr-sdk` | [Java publishing](sdk-java/PUBLISHING.md) |
| C# / .NET | NuGet `Kompressr.Sdk` | [.NET publishing](sdk-dotnet/PUBLISHING.md) |
| PHP | Packagist `kompressr/sdk` | [PHP publishing](sdk-php/PUBLISHING.md) |
| Ruby | RubyGems `kompressr-sdk` | [Ruby publishing](sdk-ruby/PUBLISHING.md) |

Run the affected package's complete native verifier, inspect its distribution, and finish authenticated acceptance checks before publishing it. The shared archive checker accepts wheels, JARs, NuGet packages, Ruby gems and tar/ZIP distributions:

```sh
node scripts/check-distribution.mjs PATH_TO_ARCHIVE
```

This check needs Node.js and Python 3, rejects unsafe archive entries, and scans every member for public-content violations without extracting files. For gems it also scans archive headers and decompresses the nested package metadata and payload within fixed limits. It accepts the ordinary tar/gzip format produced by RubyGems; extended tar headers, optional gzip metadata and trailing payloads are rejected. It supplements the package's native installation/consumer tests. Inspect generated files as well as the repository; ignored build directories are not a guarantee that their contents are publishable.

Java requires verification of the `com.kompressr` Maven namespace. Go releases use the module-specific tag prefix `sdk-go/v`; publishing another package must not create a Go release accidentally. Packagist expects `composer.json` at the VCS repository root, so PHP publication uses a package-only release mirror described in its guide. Implementation remains in this repository; creating or pushing a release mirror is a maintainer release action.

After each release, install that exact version from its public registry in a clean application, compare artifact checksums where the registry exposes archives, and repeat the dedicated-project lifecycle. Retain the previously verified release for application pinning; corrections use a new version rather than replacing a published artifact.

Official npm references: [publishing](https://docs.npmjs.com/cli/v11/commands/npm-publish/), [distribution tags](https://docs.npmjs.com/cli/v11/commands/npm-dist-tag/).
