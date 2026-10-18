# Publishing the Go SDK

Go distributes this SDK as a module from the public clients repository. The module path is `github.com/kompressrcdn/clients/sdk-go`; it requires no separate package registry account.

1. Review the complete package and root public-content checks. Run `go run ./scripts/verify.go` from `sdk-go/` on supported Go versions. Complete the agreed live lifecycle and scoped-permission checks separately using a dedicated test project.
2. Update `Version` in `types.go`, the verifier's version constant, changelog and documentation together. Keep `go.mod`'s Go version aligned with tested minimum support. Review all committed module files; Go releases include source, tests and documentation, not an allowlisted binary archive.
3. Commit and push the reviewed source only with maintainer authorization. Use a tag prefixed by the module's repository subdirectory. From the repository root, for the first authorized release:

   ```sh
   git tag -a sdk-go/v0.1.0 -m 'Release Kompressr Go SDK v0.1.0'
   git push origin sdk-go/v0.1.0
   ```

   Verify the target commit before tagging. Published versions are immutable; fix errors with a new version rather than moving a tag.

4. From a clean temporary consumer with no replace directives, verify public distribution:

   ```sh
   release_check=$(mktemp -d)
   cd "$release_check"
   export GOMODCACHE="$release_check/modcache"
   export GOPROXY=https://proxy.golang.org
   export GOSUMDB=sum.golang.org
   export GOPRIVATE=
   export GONOPROXY=
   export GONOSUMDB=
   go mod init example.test/kompressr-release-check
   go get github.com/kompressrcdn/clients/sdk-go@v0.1.0
   go mod download -json github.com/kompressrcdn/clients/sdk-go@v0.1.0
   go list -m all
   ```

   Confirm the downloaded version and checksums, build the quick start, then perform the agreed live acceptance checks. Do not describe a local ZIP fixture as published-registry verification.

A major version 2 or later also needs the `/v2` module-path suffix and corresponding import changes. See the official [module version numbering](https://go.dev/doc/modules/version-numbers) and [module publishing](https://go.dev/doc/modules/publishing) guides.
