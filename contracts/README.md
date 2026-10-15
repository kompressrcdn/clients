# Public API contract and examples

`kompressr-api.yaml` is the reviewed public HTTP contract used by these clients. [source.json](source.json) records its contract version, snapshot identifier and SHA-256. The documented default servers are the production management and upload origins; custom integrations configure their own origins explicitly.

`fixtures/file-lifecycle.json` contains synthetic upload acceptance, processed status, deletion acceptance and mixed bulk results. SDK and MCP tests consume these shared records.

```sh
node scripts/verify-contract.mjs
```

When updating a contract, review the HTTP behavior, replace the snapshot, update its version/checksum and adjust types, validation, examples and affected tests together. The checksum check establishes snapshot consistency; it is not complete OpenAPI schema validation. Root verification tests the shared examples without live credentials.
