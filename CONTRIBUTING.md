# Contributing

Each package has its own manifest and release. Build and test from a checkout; no live account or additional service repository is required. Use Node.js 24 for development tooling and shared repository checks. The published JS SDK and MCP packages support Node.js 22 and later. Python 3.11+ reads native distribution archives for the shared public-content scanner; neither is a runtime dependency of the other language SDKs.

## JS SDK and MCP

```sh
npm --prefix sdk-js ci --ignore-scripts
node scripts/verify.mjs
```

The root verifier checks public content and the contract snapshot, builds/tests the SDK, installs its packed artifact into MCP with locked dependencies, and verifies MCP. Local HTTP/stdio fixtures cover uploads, readiness, signing, deletion, errors and cancellation. CI installs development dependencies with Node 24, then runs the complete source and installed-consumer suites on Node 22.0.0 and the latest patches of Node 22–26. This keeps the test tools’ installation requirements separate from the packages’ runtime requirements.

For SDK-only work, run `npm --prefix sdk-js run verify`. For MCP-only work, run `npm --prefix mcp-server run install:local-sdk` followed by `npm --prefix mcp-server run verify`. Repeat installation after SDK changes. The helper supplies the local SDK without changing MCP's registry dependency or lockfile.

After editing files shipped in the SDK, run `node scripts/update-sdk-integrity.mjs` and then the root verifier. This refreshes only MCP's expected SDK artifact checksum. Do not commit tarballs, workspace links or filesystem release dependencies.

## Additional SDKs

Install the toolchain for the package you are changing, then use its native verifier. These commands build a distribution and exercise an isolated installed consumer as well as the source tests.

| Package | Toolchain | Native verification from the package directory |
| --- | --- | --- |
| [Python](sdk-python/README.md) | Python 3.11+; install `python -m pip install -e '.[dev]'` in a virtual environment | `python scripts/verify.py` |
| [Go](sdk-go/README.md) | Go 1.24+ | `go run ./scripts/verify.go` |
| [Java](sdk-java/README.md) | JDK 17+, Maven 3.9+ | `sh scripts/verify.sh` |
| [C#/.NET](sdk-dotnet/README.md) | .NET SDK 8+ | `sh scripts/verify.sh` |
| [PHP](sdk-php/README.md) | 64-bit PHP 8.1+, cURL with asynchronous DNS, Composer 2 | `php scripts/verify.php` |
| [Ruby](sdk-ruby/README.md) | MRI Ruby 3.2+, RubyGems and Bundler; run `bundle install` | `ruby scripts/verify.rb` |

The PHP verifier also needs standard Phar support, `proc_open` and permission to open loopback test sockets. Its TAR distribution check does not require the ZIP extension.

From the repository root, `node scripts/verify-all.mjs python go` runs selected packages and scans their actual distributions. With no arguments it requires and verifies every package; missing tools fail visibly. The `node` target covers the JS SDK and MCP together. Set `KOMPRESSR_PYTHON` to a Python executable when the default `python3` is not your development environment.

CI covers Node 22.0.0 and 22–26, Python 3.11–3.15, Go 1.24–1.27, Java 17/21, .NET 8/10, PHP 8.1–8.5 and MRI Ruby 3.2/3.3/3.4/4.0. It uses local HTTP fixtures and does not publish packages or call a live Kompressr account. See each package's `PARITY.md` for behavior coverage and native API differences. A passing JS check does not verify another language package.

The supported minimums are compatibility commitments: raise a minimum only in a major package release, with a migration note. Add newly released stable runtime lines to CI before claiming support for them. Prefer the latest patch of a supported runtime line; SDK compatibility does not extend the runtime vendor’s security-maintenance period.

Keep usage examples, public types, response validation and the [shared contract](contracts/README.md) aligned. The [SDK behavior reference](contracts/sdk-behavior.md) records the common guarantees. Preserve bounded waits, per-item bulk outcomes, credential redaction and the distinction between accepted and completed work. Add regressions for changed behavior; never automatically replay ambiguous writes.

All tracked content and release artifacts are public. Use reserved example domains and synthetic identities in tests; use local HTTP servers for integration fixtures. Keep live endpoint overrides, credentials, resource inventories and operational reports outside this repository. `node scripts/check-public-content.mjs` checks the source tree; package verification also checks every shipped file.

See package contribution notes for memory checks. Report bugs through [issues](https://github.com/kompressrcdn/clients/issues) and security concerns through [SECURITY.md](SECURITY.md).
