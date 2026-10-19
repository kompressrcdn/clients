# Changelog

## 2.0.3

- Explain the shared 100-upload, 30-day image trial in onboarding and tool descriptions. Use SDK 1.0.2 documentation updates; file operations and permissions remain enforced by the API.

## 2.0.2

- Add official MCP Registry metadata and downloadable desktop bundles through GitHub Releases.
- Keep the existing tools, configuration and SDK 1.0.1 behavior.

## 2.0.1

- Support Node.js 22.0 and later, including the Smithery bundle.
- Use SDK 1.0.1 fixes for empty scoped-key permissions and request/readiness timeouts under garbage collection.

## 2.0.0

- Accept ordinary public IPv4 download sources outside the protocol/documentation blocks while preserving DNS and redirect protections.

- Use `@kompressr/sdk` for file operations and require Node.js 22.12+.
- Add readiness waiting, deletion/progress tools, pagination/filtering and structured results.
- Support separate management/upload origins with production defaults and explicit custom overrides.
- Stream local/remote files with destination, DNS and redirect validation; private/local remote sources require an explicit hostname allowlist.
- Propagate cancellation and disconnection through download/upload; clean temporary files and preserve ambiguous write outcomes.
- Improve credential persistence, response validation, optional filename handling and packed-package verification.

### Migration from 1.x

Upgrade Node.js, review the configuration in README.md and wait for readiness before sharing a delivery URL. Scoped keys exclude deletion by default. SDK publication must precede an MCP release depending on it.
