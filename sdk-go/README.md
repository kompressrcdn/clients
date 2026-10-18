# Kompressr for Go

Upload, optimize and manage files from a Go backend. This module also provisions application users and their scoped upload keys.

Requires Go 1.24 or newer. The SDK uses only the standard library and works with any Go HTTP framework, background worker or command-line application.

## Install

```sh
go get github.com/kompressrcdn/clients/sdk-go@v0.1.0
```

## Upload a file

Create a Kompressr account, select a plan with API upload access, and copy a project's key from **Dashboard → Projects → API Keys**. Keep it on your backend. Set `KOMPRESSR_API_KEY` through your environment or secret manager; do not put it in source control.

```go
package main

import (
    "context"
    "log"
    "os"

    kompressr "github.com/kompressrcdn/clients/sdk-go"
)

func main() {
    files, err := kompressr.New(kompressr.Config{
        APIKey: os.Getenv("KOMPRESSR_API_KEY"),
    })
    if err != nil { log.Fatal(err) }
    defer files.CloseIdleConnections()

    ctx := context.Background()
    accepted, err := files.UploadFile(ctx, "image.png", kompressr.UploadOptions{
        Visibility: kompressr.Public,
    })
    if err != nil { log.Fatal(err) }

    // Persist accepted.ID in your application before waiting.
    log.Printf("accepted asset %d", accepted.ID)
    ready, err := files.WaitUntilReady(ctx, accepted.ID, kompressr.WaitOptions{})
    if err != nil { log.Fatal(err) }
    log.Printf("public delivery: %s", ready.CDNURL)
}
```

`UploadFile` streams a regular file. `UploadBytes` snapshots a byte slice. `UploadReader` accepts a size and an `io.ReadCloser`, takes ownership, and closes it on every return path. It sends exactly the declared number of bytes; a short source fails. A custom reader's `Close` must unblock `Read`.

## Runnable examples

Clone the repository and run these commands from `sdk-go/`:

```sh
go run ./examples/upload -file ./image.png -show-url
```

Expected output starts with an accepted asset ID, followed by readiness and a public delivery URL. Save that ID: acceptance means processing has started, not that the URL is ready.

For a private upload:

```sh
go run ./examples/upload -file ./image.png -private -show-url
```

Private links grant access and expire. The command prints a link only with `-show-url`; avoid collecting that output in routine logs. If waiting times out, resume the same asset instead of uploading again:

```sh
go run ./examples/upload -resume 42 -show-url
```

Replace `42` with the saved ID. The example obtains a fresh signed link for a ready private asset.

## Credentials and separate users

A regular project key grants project authority. A scoped key limits actions and files to its associated application user, as enforced by the API. Use either key in `Config.APIKey`; the SDK never falls back to a more powerful credential. Upload listing also needs the project UUID through `Config.ProjectID` or `UploadFilters.ProjectID`.

Scoped keys require a project and plan supporting Platform/AI users. Check the current [pricing page](https://kompressr.com/pricing#file-support). Your backend must derive the customer identity from its authenticated session, store issued keys securely, and authorize access to each conversation or asset. An SDK cannot establish those application relationships.

The [platform example](https://github.com/kompressrcdn/clients/blob/main/sdk-go/examples/platform/main.go) creates a private-only scoped key, excluding delete permission, and saves the one-time credential to a new private file:

```sh
go run ./examples/platform -customer customer-123 -out /secure/location/runtime-key.json
```

Use a project credential for that command. It prints the project-user UUID and key-record UUID; keep those for rotation and revocation. Supply them explicitly:

```sh
go run ./examples/platform -action rotate -user USER_UUID -key KEY_RECORD_UUID -out /secure/location/replacement-key.json
go run ./examples/platform -action revoke -user USER_UUID -key KEY_RECORD_UUID
```

Replace the placeholders. Rotation returns a new one-time secret; distribute it securely to the intended runtime. Suspending a user revokes keys without deleting files; reactivating does not restore revoked keys. See the [chatbot guide](https://github.com/kompressrcdn/clients/blob/main/guides/chatbot-integration.md) for the application flow and [API reference](https://github.com/kompressrcdn/clients/blob/main/sdk-go/API.md) for every method.

## Errors, deadlines and recovery

Every method takes a `context.Context`. Default management and upload deadlines are 30 seconds and 10 minutes; readiness waiting defaults to two minutes. Request budgets include response bodies, read retries and retry delays. Cancel a context to stop waiting or an in-flight request; this does not roll back server work.

```go
var failure *kompressr.Error
if errors.As(err, &failure) {
    if failure.AssetID != 0 {
        // Save it; resume GetUploadStatus or inspect GetAsset as appropriate.
    }
    if failure.MayHaveSucceeded {
        // Inspect the write outcome before deciding whether to repeat it.
    }
}
```

Import the standard `errors` package for that snippet. `errors.Is(err, context.Canceled)` and `errors.Is(err, context.DeadlineExceeded)` work as well. Error messages redact credentials and URLs; successful private links and issued keys are still sensitive data.

Only eligible GET network failures and HTTP 429/502/503/504 are retried, at most twice by default, within the original deadline. `Retry-After` is respected. Uploading, signing, deletion and all platform writes are never automatically repeated. Save an accepted ID before polling. If an interrupted upload has no recoverable ID, inspect the project's uploads before deciding what to do; there is no automatic recovery lookup or deduplication promise.

Deletion acceptance means cleanup is scheduled. Inspect `GetAsset` for completion and storage credits. `BulkDeleteAssets` preserves each success or failure, even when the overall HTTP request succeeds.

## Development

```sh
go run ./scripts/verify.go
```

This builds examples, runs `go vet` and race-enabled tests, creates a module ZIP, and installs it into an isolated consumer through a local file proxy. Tests use synthetic local HTTP servers; they do not prove live plan entitlements or production credentials. See [behavior parity](https://github.com/kompressrcdn/clients/blob/main/sdk-go/PARITY.md), [contributing](https://github.com/kompressrcdn/clients/blob/main/sdk-go/CONTRIBUTING.md) and [releasing](https://github.com/kompressrcdn/clients/blob/main/sdk-go/PUBLISHING.md).

[MIT license](https://github.com/kompressrcdn/clients/blob/main/sdk-go/LICENSE). Report bugs in the [clients repository](https://github.com/kompressrcdn/clients/issues); see the repository's [security policy](https://github.com/kompressrcdn/clients/blob/main/SECURITY.md) for private reports.
