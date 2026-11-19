# Go

Go 1.24+. Standard-library runtime dependencies; compatible with ordinary Go HTTP frameworks, jobs and CLI programs.

```sh
go get github.com/kompressrcdn/clients/sdk-go@v0.2.0
```

Finish helper; the caller constructs a client with `kompressr.New(kompressr.Config{APIKey: ...})`, retains the accepted ID and supplies durable persistence:

```go
package attachments

import (
    "context"
    kompressr "github.com/kompressrcdn/clients/sdk-go"
)

func FinishPublicUpload(ctx context.Context, files *kompressr.Client, assetID int64,
    saveAssetID func(int64) error) (string, error) {
    if err := saveAssetID(assetID); err != nil { return "", err }
    ready, err := files.WaitUntilReady(ctx, assetID, kompressr.WaitOptions{})
    if err != nil { return "", err }
    return ready.CDNURL, nil
}
```

In the caller, upload once:

```go
accepted, err := files.UploadFile(ctx, path,
    kompressr.UploadOptions{Visibility: kompressr.Public})
```

Handle `err` before using `accepted`. On success, retain `accepted.ID` and call
`FinishPublicUpload(ctx, files, accepted.ID, saveAssetID)`. If finishing fails, the
caller still has the ID and original error. Retry only finishing after recovery;
see [durable recovery](sdks.md#pattern-used-in-the-language-recipes).

For a CLI example, run `go run ./examples/upload -file ./image.png -show-url` from the source `sdk-go` directory; `-resume ID` resumes without reupload. See [examples](https://github.com/kompressrcdn/clients/tree/main/sdk-go/examples).

## Upload without optimization

For original-byte storage, replace the caller's upload call above with:

```go
original := true
accepted, err := files.UploadFile(ctx, path,
    kompressr.UploadOptions{Visibility: kompressr.Public, Passthrough: &original})
```

`Passthrough` is a `*bool`: use nil for omission, or a pointer to false for ordinary optimization. Keep the error handling before using `accepted`, the caller's receipt and the finish step. Follow [upload modes](uploads.md) for eligibility, confirmation, immediate readiness and private signing.

## Methods and shapes

Every HTTP operation takes `context.Context` first and a typed options value last. Use native `time.Duration` values. `UploadAccepted.ID` is the recovery ID; `UploadAsset.CDNURL` is public delivery. `GeneratePrivateURL(ctx, id, kompressr.PrivateURLOptions{})` returns `PrivateURL.PrivateURL`; sign only after private readiness and app authorization.

File methods: `UploadFile`, `UploadBytes`, `UploadReader`, `GetUploadStatus`, `WaitUntilReady`, `GeneratePrivateURL`, `ListUploads`, `IterateUploads`, `ListAssets`, `GetAsset`, `DeleteAsset`, `BulkDeleteAssets`. Upload listing needs `Config.ProjectID` or `UploadFilters.ProjectID`. Most methods return `(result, error)`; the iterator yields `(asset, error)` pairs.

`files.Platform` provides user/key administration with typed options. Keep project credentials on the backend. Nil `Scopes` uses defaults; an explicit empty slice is rejected. `AllowedAssetTypes` has different semantics: omitted/empty means all supported types.

## Application details

- `UploadReader` owns its `io.ReadCloser`, closes it on all return paths and requires an exact size. Its `Close` must unblock `Read`. Do not pass an unbounded reader.
- Config origins: `APIBaseURL`, `UploadBaseURL`. Reuse clients concurrently and call `CloseIdleConnections` when finished.
- Inspect errors with `errors.As` into `*kompressr.Error`: `Code`, `Status`, `AssetID`, `RetryAfter`, `MayHaveSucceeded`. Context cancellation does not cancel accepted service processing.
- The API models use JS-safe positive IDs even though the Go type is `int64`. Preserve the service-provided ID.

[Full API](https://github.com/kompressrcdn/clients/blob/main/sdk-go/API.md) · [Guide](https://github.com/kompressrcdn/clients/blob/main/sdk-go/README.md)
