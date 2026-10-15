# SDK development

Use a checkout of [kompressrcdn/clients](https://github.com/kompressrcdn/clients) with Node.js 22.12+ or 24. From `sdk-js`:

```sh
npm ci --ignore-scripts
npm run verify
```

Verification builds ESM/CommonJS outputs, checks TypeScript, runs local HTTP regressions and validates installed package imports, declarations and executable examples. It requires no live account.

From the repository root, run `node scripts/update-sdk-integrity.mjs` after editing shipped SDK files, then `node scripts/verify.mjs`. The root verifier also checks the MCP integration with the packed SDK. Each package keeps its own lockfile and registry dependency.

After building, optional memory checks are `node scripts/verify-large-file.mjs` for a file-backed upload and `node --expose-gc scripts/verify-bytes-memory.mjs` for bytes-input allocation. Both use local fixtures; neither is a service load test.

Keep examples, public types and API.md aligned with behavior. Use synthetic credentials and reserved example domains. See the [repository contribution guide](https://github.com/kompressrcdn/clients/blob/main/CONTRIBUTING.md) and [publishing guide](https://github.com/kompressrcdn/clients/blob/main/PUBLISHING.md).
