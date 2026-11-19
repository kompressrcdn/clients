# C# and .NET

.NET 8+. Use in ASP.NET Core, workers and console applications. Browser-hosted Blazor WebAssembly is not a trusted place for project credentials; call a backend.

```sh
dotnet add package Kompressr.Sdk --version 0.2.0
```

Finish helper; the caller already holds the accepted ID. Provide an async persistence callback that commits the ID:

```csharp
using Kompressr.Sdk;

public static class Attachments
{
    public static async Task<string?> FinishPublicUploadAsync(
        KompressrClient files, long assetId, Func<long, Task> saveAssetId)
    {
        await saveAssetId(assetId);
        var ready = await files.WaitUntilReadyAsync(assetId);
        return ready.CdnUrl;
    }
}
```

In the caller, upload once and retain `accepted` before finishing:

```csharp
var accepted = await files.UploadFileAsync(path,
    new UploadOptions { Visibility = "public" });
var url = await Attachments.FinishPublicUploadAsync(files, accepted.Id, saveAssetId);
```

If finishing fails or is cancelled, the caller still has `accepted.Id` and the
original exception. Retry only finishing after recovery; see
[durable recovery](sdks.md#pattern-used-in-the-language-recipes).

Create with `new KompressrClient(new ClientOptions { ApiKey = ... })`, loading the secret from server configuration. Reuse the client; it supports concurrent calls and requires no persistent-connection disposal. [Runnable examples](https://github.com/kompressrcdn/clients/blob/main/sdk-dotnet/examples/Program.cs) cover additional flows.

## Upload without optimization

For original-byte storage, replace the caller's upload call above with:

```csharp
var accepted = await files.UploadFileAsync(path,
    new UploadOptions { Visibility = "public", Passthrough = true });
```

`Passthrough` is nullable: null omits the option, false preserves optimization. The option also applies to `UploadBytesAsync`. Keep the caller's receipt and the finish step. Follow [upload modes](uploads.md) for eligibility, confirmation, immediate readiness and private signing.

## Methods and shapes

Public results use `Id` and `CdnUrl`. Private upload: `new UploadOptions { Visibility = "private" }`, persist/wait, then `GeneratePrivateUrlAsync(id, new PrivateUrlOptions { ExpiresIn = 3600 })`. Return `link.Url` only to an authorized recipient.

File families: `UploadFileAsync`, `UploadBytesAsync`, `GetUploadStatusAsync`, `WaitUntilReadyAsync`, `GeneratePrivateUrlAsync`, `ListUploadsAsync`, `IterateUploadsAsync`, `ListAssetsAsync`, `GetAssetAsync`, `DeleteAssetAsync`, `BulkDeleteAssetsAsync`. Use `await foreach` for upload iteration. Upload listing needs `UploadFilters.ProjectId` or configured project ID. Platform operations are under `client.Platform`.

## Application details

- Timeouts use `TimeSpan`; signing `ExpiresIn` uses seconds. Pass the operation's final `CancellationToken` where appropriate.
- `KompressrException` carries `Kind`, `Code`, `Status`, `RetryAfter`, `AssetId`, `MayHaveSucceeded`. Preserve recovery state on timeout/cancellation; accepted server work continues.
- `UploadFileAsync` requires a trusted regular local path. Arbitrary streams, pipes and devices are unsupported. Portable file attributes cannot identify every Unix special file; validate the source in your application.
- Adapt ASP.NET `IFormFile` to a bounded byte array or a validated regular temporary file. Keep it alive until upload finishes; move durable work to a job when needed.
- `bulk.Results` contains per-item `Accepted` values. HTTP-level success does not mean every requested file was deleted.

[Full API](https://github.com/kompressrcdn/clients/blob/main/sdk-dotnet/API.md) · [Guide](https://github.com/kompressrcdn/clients/blob/main/sdk-dotnet/README.md)
