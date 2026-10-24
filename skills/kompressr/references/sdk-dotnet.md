# C# and .NET

.NET 8+. Use in ASP.NET Core, workers and console applications. Browser-hosted Blazor WebAssembly is not a trusted place for project credentials; call a backend.

```sh
dotnet add package Kompressr.Sdk --version 0.1.1
```

Integration helper; provide an async persistence callback that commits the ID:

```csharp
using Kompressr.Sdk;

public static class Attachments
{
    public static async Task<string?> UploadPublicAsync(
        KompressrClient files, string path, Func<long, Task> saveAssetId)
    {
        var accepted = await files.UploadFileAsync(path,
            new UploadOptions { Visibility = "public" });
        await saveAssetId(accepted.Id);
        var ready = await files.WaitUntilReadyAsync(accepted.Id);
        return ready.CdnUrl;
    }
}
```

Create with `new KompressrClient(new ClientOptions { ApiKey = ... })`, loading the secret from server configuration. Reuse the client; it supports concurrent calls and requires no persistent-connection disposal. [Runnable examples](https://github.com/kompressrcdn/clients/blob/main/sdk-dotnet/examples/Program.cs) cover additional flows.

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
