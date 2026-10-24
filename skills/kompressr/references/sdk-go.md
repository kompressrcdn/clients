# Go

Go 1.24+. Standard-library runtime dependencies; compatible with ordinary Go HTTP frameworks, jobs and CLI programs.

```sh
go get github.com/kompressrcdn/clients/sdk-go@v0.1.1
```

Integration helper; the caller constructs a client with `kompressr.New(kompressr.Config{APIKey: ...})` and supplies durable persistence:

```go
package attachments

import (
    "context"
    kompressr "github.com/kompressrcdn/clients/sdk-go"
)

func UploadPublic(ctx context.Context, files *kompressr.Client, path string,
    saveAssetID func(int64) error) (string, error) {
    accepted, err := files.UploadFile(ctx, path,
        kompressr.UploadOptions{Visibility: kompressr.Public})
    if err != nil { return "", err }
    if err := saveAssetID(accepted.ID); err != nil { return "", err }
    ready, err := files.WaitUntilReady(ctx, accepted.ID, kompressr.WaitOptions{})
    if err != nil { return "", err }
    return ready.CDNURL, nil
}
```

Retain the accepted ID if persistence itself fails; do not replay the upload helper as a generic job retry. For a CLI example, run `go run ./examples/upload -file ./image.png -show-url` from the source `sdk-go` directory; `-resume ID` resumes without reupload. See [examples](https://github.com/kompressrcdn/clients/tree/main/sdk-go/examples).

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
