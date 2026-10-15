# SDK engineering

Follow the root AGENTS.md and read README.md, API.md and CONTRIBUTING.md. Run `npm run verify` for SDK changes. After changing shipped contents, refresh the SDK checksum and run the root verifier for MCP integration.

Keep runtime dependencies minimal, ESM/CommonJS exports and declarations working, and secrets/private URLs out of errors. Preserve bounded waiting, cancellation and write ambiguity. Use local HTTP fixtures or reserved example domains in tests.
