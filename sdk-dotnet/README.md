# Kompressr for .NET

Upload files, wait for processing and return delivery links from your C# backend. The client also supports asset deletion and per-user scoped keys. Requires .NET 8 or later and works in ASP.NET Core, worker services and console applications.

## Install

Run from the directory containing your application's project file:

```sh
dotnet add package Kompressr.Sdk --version 0.1.0
```

Create a [Kompressr account](https://kompressr.com/signup), choose a plan with API upload access, and create a project. Get its API key from **Dashboard → Projects → API Keys**, then configure `KOMPRESSR_API_KEY` in your backend's secret store. Check [pricing](https://kompressr.com/pricing#file-support) for current file limits and scoped-key access.

## Upload your first public file

```csharp
using Kompressr.Sdk;

var client = new KompressrClient(new ClientOptions
{
    ApiKey = Environment.GetEnvironmentVariable("KOMPRESSR_API_KEY")
        ?? throw new InvalidOperationException("Set KOMPRESSR_API_KEY.")
});

var accepted = await client.UploadFileAsync("image.png",
    new UploadOptions { Visibility = "public" });

// Save accepted.Id in your application before waiting.
var ready = await client.WaitUntilReadyAsync(accepted.Id);
Console.WriteLine(ready.CdnUrl);
```

Acceptance means Kompressr has received the upload. The file may still be processing. `WaitUntilReadyAsync` returns only when the asset is ready; it does not upload again.

Reuse a client across requests. It is safe for concurrent operations and holds no persistent connections that need disposal. Upload options are sent before the file, and file bodies stream with bounded memory. `UploadBytesAsync(bytes, "image.png")` snapshots an existing byte buffer.

`UploadFileAsync` expects a trusted path to a regular local file. Pipes, devices and arbitrary streams are unsupported. File opening happens before the HTTP deadline; OS filesystem stalls are outside that deadline. .NET's portable file attributes cannot detect every Unix special file before opening it.

## Keep a file private

```csharp
var accepted = await client.UploadFileAsync("report.pdf",
    new UploadOptions { Visibility = "private" });
// Persist accepted.Id first.
await client.WaitUntilReadyAsync(accepted.Id);
var link = await client.GeneratePrivateUrlAsync(accepted.Id,
    new PrivateUrlOptions { ExpiresIn = 3600 });
// Return link.Url to the authorized user. Do not put it in routine logs.
```

A private file has no public CDN URL. Its signed URL expires independently of the file. Generate a new link when an authorized user needs access again. Waiting for a private file does not automatically generate a link.

## Resume after a timeout

Pass a final `CancellationToken` to stop an operation. Cancellation stops your request or wait; it does not undo work already accepted by the server.

```csharp
try
{
    var ready = await client.WaitUntilReadyAsync(savedAssetId,
        new WaitOptions { Timeout = TimeSpan.FromSeconds(30) }, cancellationToken);
}
catch (KompressrException error) when (error.Code is "WAIT_TIMEOUT" or "WAIT_CANCELLED")
{
    // Keep error.AssetId. Later, call WaitUntilReadyAsync with that same ID.
}
```

Other `KompressrException` fields include `Kind`, `Code`, `Status`, `RetryAfter`, `AssetId` and `MayHaveSucceeded`. If a write may have succeeded, inspect its outcome before retrying. A lost upload response may have no recoverable asset ID. See [error and recovery behavior](https://github.com/kompressrcdn/clients/blob/main/sdk-dotnet/API.md#error-and-recovery-behavior).

## Give chatbot users scoped access

A project key administers the project. A scoped key belongs to a project user and grants only its configured operations. Creating a `PlatformClient` with a scoped key does not grant project authority.

On your trusted backend, map each authenticated application user to a stable customer ID:

```csharp
var created = await client.Platform.CreateUserAsync(new CreateUserOptions
{
    CustomerUserId = authenticatedUserId
});
var issued = await client.Platform.CreateUploadKeyAsync(created.ProjectUser.Id,
    new CreateKeyOptions
    {
        Name = "Chat uploads",
        AllowedVisibility = "private",
        Scopes = new[] { "upload", "status", "list", "private_url" }
    });
// Store issued.ApiKey securely for this user; the secret is returned only once.
var userFiles = new KompressrClient(new ClientOptions { ApiKey = issued.ApiKey });
```

Use that user's client for their uploads and status checks. Authenticate the user and check conversation membership in your application before returning any file or signed URL. Keep project keys on the backend. Scoped defaults exclude deletion; add `delete` only when your application needs it. Scoped key access depends on project type and plan.

## List or delete files

```csharp
var page = await client.ListUploadsAsync(new UploadFilters
{
    ProjectId = projectId, Limit = 20
});
await foreach (var file in client.IterateUploadsAsync(new UploadFilters { ProjectId = projectId }))
    Console.WriteLine(file.Id);

var deletion = await client.DeleteAssetAsync(savedAssetId);
// Accepted deletion can still be cleaning up. Inspect GetAssetAsync(savedAssetId) later.
var bulk = await client.BulkDeleteAssetsAsync(new long[] { firstAssetId, secondAssetId });
foreach (var result in bulk.Results)
    Console.WriteLine($"{result.Id}: accepted={result.Accepted}");
```

Deletion is permanent and requires delete authority. Background cleanup and cache expiration can outlast the accepted response. Bulk results retain each failure, including partial failures returned with HTTP 200.

## Develop and verify

From `sdk-dotnet` with the .NET SDK installed:

```sh
sh scripts/verify.sh
# When using the .NET 10 SDK:
KOMPRESSR_TEST_FRAMEWORK=net10.0 sh scripts/verify.sh
```

Verification builds the library and examples, runs loopback HTTP tests, packs a NuGet archive, installs it into a clean consumer and runs the HTTP suite again. No credentials or production access are needed. The tests include a 32 MiB file upload with an allocation limit.

The [API reference](https://github.com/kompressrcdn/clients/blob/main/sdk-dotnet/API.md), [behavior coverage](https://github.com/kompressrcdn/clients/blob/main/sdk-dotnet/PARITY.md), [runnable examples](https://github.com/kompressrcdn/clients/blob/main/sdk-dotnet/examples/Program.cs) and [publishing guide](https://github.com/kompressrcdn/clients/blob/main/sdk-dotnet/PUBLISHING.md) cover the remaining details.
