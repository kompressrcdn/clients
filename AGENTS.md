# Client engineering

Read README.md, CONTRIBUTING.md and the affected package reference before changing code. This is a public repository: keep documentation, fixtures, comments, commit messages and package artifacts suitable for public distribution. Use synthetic test addresses and credentials; configure private integrations outside this repository. Preserve unrelated work.

SDK and MCP have independent manifests, lockfiles and releases. Keep MCP's SDK dependency as a registry version. Run `node scripts/verify.mjs` for shared, contract or packaging changes; use package verification for isolated work. Refresh SDK integrity with `node scripts/update-sdk-integrity.mjs` after changing shipped SDK files. Preserve acceptance/readiness distinctions, cancellation, credential redaction and safe handling of ambiguous writes.

Write public READMEs for package users: installation, supported environments, examples and recovery. Keep publishing runbooks, publisher account setup, release readiness, review checkpoints and work logs outside this repository and its package archives. Use changelogs for versioned changes and contribution guides for public build/test instructions.

Keep instructions self-contained within this repository. Do not add operational handoffs, live resource inventories or machine-specific records. Push only when explicitly requested; publish or deploy only with maintainer authorization.

For additional language SDKs, read contracts/sdk-behavior.md and the package's API/parity reference. Keep changes inside the affected package unless shared integration is required. Run native verification and inspect the built distribution; a passing JS/MCP verifier does not verify another language. New package versions remain unpublished until an authorized registry release is confirmed.
