# Contributing to the Go SDK

Read the repository contribution guide and [behavior matrix](PARITY.md). Use Go 1.24 or newer; this module has no external dependencies. Keep examples and fixtures synthetic and public-safe.

```sh
go run ./scripts/verify.go
```

The verifier runs builds, vet and race tests, then generates a versioned module ZIP and installs it through an isolated local file proxy. A clean consumer imports the installed module without a replace directive and exercises a real local HTTP upload/readiness flow. Module checksum service checks are disabled only for this synthetic local proxy; normal published consumers use the usual Go proxy/checksum defaults. Tests binding loopback ports require an environment that permits local networking.

For focused development:

```sh
gofmt -w *.go examples/*/*.go scripts/verify.go
go test -race ./...
go vet ./...
```

The module contains a self-contained lifecycle fixture; tests compare it with the shared repository fixture when the latter is available. Set `KOMPRESSR_VERIFY_ARTIFACT_DIR` to an output directory outside the module to retain the exact verified ZIP for artifact scans. The verifier rejects unexpected file extensions and symlinks in its distribution inventory. Keep generated binaries, profiles and credentials outside the module directory. Shared root CI/content checks are maintained separately.

## Transport rationale

The official [`net/http` documentation](https://pkg.go.dev/net/http#Transport) explains transport retries on reused connections. The HTTP/2 implementation can also retry certain stream failures. The SDK's mutations therefore use a cloned transport restricted to HTTP/1 with keep-alives disabled, no `GetBody`, no idempotency headers and no redirects. Even empty-body POST and DELETE requests use fresh connections. This prevents the HTTP library from silently repeating a mutation beyond the SDK's policy. The client remains reusable and concurrent; closing response bodies and disabling write connection reuse avoids accumulating idle write connections.

Read requests can reuse a separate transport. [`NewRequestWithContext`](https://pkg.go.dev/net/http#NewRequestWithContext) applies cancellation to obtaining a connection, sending, and reading the response. The SDK keeps one total deadline across attempts and retry waits. The native transport and caller-provided dialing/reader implementations must honor context/close contracts; arbitrary third-party `RoundTripper` implementations are intentionally not accepted.

Multipart headers, fields and the closing boundary are small buffers. File bytes flow through a sized reader directly to the request; there is no multipart producer goroutine or complete-file buffering. `UploadReader` owns its source and closes it on success, validation failure, timeout and cancellation. `UploadBytes` snapshots the selected slice; callers must not race that copy by modifying it concurrently.

When fixing behavior, test customer-visible recovery as well as the first request. Keep mutation response parsing inside the ambiguity boundary. Do not expose raw response bodies, signed links or API keys through error messages. Document actual local evidence separately from live service checks.
