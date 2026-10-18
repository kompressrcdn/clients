using System.Globalization;
using System.Net.Http.Headers;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;

namespace Kompressr.Sdk;

/// <summary>Async upload, delivery and asset lifecycle operations. Safe to reuse concurrently.</summary>
public sealed class KompressrClient
{
    private readonly Transport transport;
    private readonly string? projectId;
    public string ApiBaseUrl => transport.ApiBaseUrl;
    public string UploadBaseUrl => transport.UploadBaseUrl;
    public PlatformClient Platform { get; }
    public KompressrClient(ClientOptions options)
    {
        transport = new(options);
        projectId = options.ProjectId;
        Platform = new(transport);
    }

    public async Task<UploadAccepted> UploadFileAsync(string path, UploadOptions? options = null, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(path)) throw KompressrException.Invalid("Supply a regular file path.");
        using var form = Multipart(Path.GetFileName(path), options);
        if (cancellationToken.IsCancellationRequested) throw CancelledBeforeDispatch();
        var info = new FileInfo(path);
        if (!info.Exists || (info.Attributes & (FileAttributes.Directory | FileAttributes.Device)) != 0) throw KompressrException.Invalid("Supply an existing regular file path.");
        await using var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 64 * 1024, FileOptions.Asynchronous | FileOptions.SequentialScan);
        if (!file.CanSeek) throw KompressrException.Invalid("The upload source must be a seekable regular file.");
        using var content = new StreamContent(file, 64 * 1024);
        content.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        form.Add(content, "file", Path.GetFileName(path));
        return await transport.SendAsync("/api/upload", HttpMethod.Post, Validation.Accepted, options, cancellationToken, form, upload: true, recoverUploadId: true).ConfigureAwait(false);
    }
    public Task<UploadAccepted> UploadBytesAsync(ReadOnlyMemory<byte> bytes, string filename, UploadOptions? options = null, CancellationToken cancellationToken = default)
    {
        var form = Multipart(filename, options);
        try
        {
            if (cancellationToken.IsCancellationRequested) throw CancelledBeforeDispatch();
            // Snapshot before the asynchronous operation: callers may reuse their buffer afterwards.
            var content = new ByteArrayContent(bytes.ToArray());
            content.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
            form.Add(content, "file", Path.GetFileName(filename));
            return transport.SendAsync("/api/upload", HttpMethod.Post, Validation.Accepted, options, cancellationToken, form, upload: true, recoverUploadId: true);
        }
        catch { form.Dispose(); throw; }
    }
    private static MultipartFormDataContent Multipart(string filename, UploadOptions? options)
    {
        if (string.IsNullOrWhiteSpace(filename) || filename.Any(char.IsControl) || string.IsNullOrWhiteSpace(Path.GetFileName(filename)))
            throw KompressrException.Invalid("Supply a nonempty filename without control characters.");
        Validation.Text(filename, int.MaxValue);
        var form = new MultipartFormDataContent();
        try
        {
            if (options?.Visibility is { } visibility) form.Add(new StringContent(Validation.Choice(visibility, "public", "private")), "visibility");
            if (options?.Quality is { } quality) form.Add(new StringContent(Validation.Choice(quality, "480p", "720p", "1080p", "4k")), "kmp-quality");
            if (options?.PrivateUrlExpiresIn is { } ttl)
            {
                if (ttl is < 60 or > 604800) throw KompressrException.Invalid("Private URL lifetime must be from 60 to 604800 seconds.");
                form.Add(new StringContent(ttl.ToString(CultureInfo.InvariantCulture)), "private_url_expires_in");
            }
            if (options?.Data is { } data) form.Add(new StringContent(JsonSerializer.Serialize(Validation.Metadata(data), Validation.JsonOptions), Encoding.UTF8), "data");
            return form;
        }
        catch { form.Dispose(); throw; }
    }
    public Task<UploadAsset> GetUploadStatusAsync(long id, RequestOptions? options = null, CancellationToken cancellationToken = default)
    {
        Validation.Id(id);
        return transport.SendAsync($"/api/upload/{id}/status", HttpMethod.Get, body =>
        {
            var result = Validation.Upload(Validation.Data(body));
            if (result.Id != id) throw KompressrException.BadResponse();
            return result;
        }, options, cancellationToken);
    }
    public async Task<UploadAsset> WaitUntilReadyAsync(long id, WaitOptions? options = null, CancellationToken cancellationToken = default)
    {
        Validation.Id(id);
        var duration = Validation.Duration(options?.Timeout ?? TimeSpan.FromMinutes(2), "Timeout");
        var interval = Validation.Duration(options?.PollInterval ?? TimeSpan.FromSeconds(2), "PollInterval", 30000);
        using var timeout = new CancellationTokenSource(duration);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(timeout.Token, cancellationToken);
        try
        {
            while (true)
            {
                linked.Token.ThrowIfCancellationRequested();
                var asset = await GetUploadStatusAsync(id, cancellationToken: linked.Token).ConfigureAwait(false);
                linked.Token.ThrowIfCancellationRequested();
                if (asset.DeletionStatus != "active") throw new KompressrException("The asset is being deleted or has been deleted.", "processing", "ASSET_DELETED", assetId: id);
                if (asset.Status == "processed")
                {
                    if ((asset.Visibility == "public" && asset.CdnUrl is null) || (asset.Visibility == "private" && !asset.CanGeneratePrivateUrl)) throw KompressrException.BadResponse();
                    return asset;
                }
                if (asset.Status is not ("pending" or "processing")) throw new KompressrException("Asset processing did not complete successfully.", "processing", "PROCESSING_FAILED", assetId: id);
                var jitter = TimeSpan.FromMilliseconds(Random.Shared.NextDouble() * Math.Min(250, interval.TotalMilliseconds * 0.1));
                await Transport.DelayAsync(interval + jitter > TimeSpan.FromSeconds(30) ? TimeSpan.FromSeconds(30) : interval + jitter, linked.Token).ConfigureAwait(false);
            }
        }
        catch (Exception) when (linked.IsCancellationRequested)
        {
            bool cancelled = cancellationToken.IsCancellationRequested;
            throw new KompressrException(cancelled ? "Waiting cancelled; resume with the saved asset ID." : "Waiting timed out; resume with the saved asset ID.",
                cancelled ? "cancelled" : "timeout", cancelled ? "WAIT_CANCELLED" : "WAIT_TIMEOUT", assetId: id);
        }
        catch (KompressrException error) { throw error.Context(error.Status, id, false); }
    }
    public Task<PrivateUrl> GeneratePrivateUrlAsync(long id, PrivateUrlOptions? options = null, CancellationToken cancellationToken = default)
    {
        Validation.Id(id);
        options ??= new();
        if (options.ExpiresIn is < 60 or > 604800) throw KompressrException.Invalid("Private URL lifetime must be from 60 to 604800 seconds.");
        Validation.Choice(options.Variant, "webp", "avif");
        return transport.SendAsync($"/api/upload/{id}/private-url", HttpMethod.Post, body => Validation.SignedUrl(body, id), options, cancellationToken,
            Transport.Json(new { expires_in = options.ExpiresIn, variant = options.Variant }), assetId: id);
    }
    public Task<Page<UploadAsset>> ListUploadsAsync(UploadFilters? options = null, CancellationToken cancellationToken = default) => ListUploadsPageAsync(options ?? new(), null, cancellationToken);
    private Task<Page<UploadAsset>> ListUploadsPageAsync(UploadFilters options, int? page, CancellationToken cancellationToken)
    {
        var query = Pagination(options, page);
        var project = options.ProjectId ?? projectId ?? throw KompressrException.Invalid("Upload listing requires ProjectId.");
        query.Add(new("project_id", Validation.Uuid(project)));
        if (options.Visibility is { } visibility) query.Add(new("visibility", Validation.Choice(visibility, "public", "private")));
        if (options.DeletionStatus is { } deletion) query.Add(new("deletion_status", Validation.Choice(deletion, Validation.Deletions)));
        if (options.Status is { } status)
        {
            string value = status switch { "pending" => "1", "processing" => "2", "processed" => "3", "failed" => "4", "unprocessable" => "5", "1" or "2" or "3" or "4" or "5" or "6" => status, _ => throw KompressrException.Invalid("Unsupported processing status filter.") };
            query.Add(new("status", value));
        }
        if (options.ExternalId is { } external) query.Add(new("external_id", Validation.Text(external, 512, empty: true, trim: false)));
        if (options.Data is { } data)
        {
            var normalized = Validation.Metadata(data.ToDictionary(pair => pair.Key, pair => (object?)pair.Value, StringComparer.Ordinal));
            foreach (var (key, value) in normalized)
            {
                if (value is not string text) throw KompressrException.Invalid("Data filters must be strings.");
                query.Add(new("data." + key, text));
            }
        }
        return transport.SendAsync("/api/uploads?" + Query(query), HttpMethod.Get, body => Validation.Page(Validation.Success(body), Validation.Upload), options, cancellationToken);
    }
    public async IAsyncEnumerable<UploadAsset> IterateUploadsAsync(UploadFilters? options = null, [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        options ??= new();
        int next = options.Page;
        while (true)
        {
            var page = await ListUploadsPageAsync(options, next, cancellationToken).ConfigureAwait(false);
            if (page.PageNumber != next || page.Data.Count > page.Limit) throw KompressrException.BadResponse();
            foreach (var asset in page.Data)
            {
                if (cancellationToken.IsCancellationRequested) throw CancelledBeforeDispatch();
                yield return asset;
            }
            if (page.Data.Count == 0 || (long)page.PageNumber * page.Limit >= page.Total) yield break;
            if (next == int.MaxValue) throw KompressrException.BadResponse();
            next++;
        }
    }
    public Task<Page<AssetState>> ListAssetsAsync(AssetFilters? options = null, CancellationToken cancellationToken = default)
    {
        options ??= new();
        var query = Pagination(options);
        if (options.DeletionStatus is { } deletion) query.Add(new("deletion_status", Validation.Choice(deletion, Validation.Deletions)));
        return transport.SendAsync("/api/assets?" + Query(query), HttpMethod.Get, body => Validation.Page(body, Validation.Asset), options, cancellationToken);
    }
    public Task<AssetState> GetAssetAsync(long id, RequestOptions? options = null, CancellationToken cancellationToken = default) => AssetAsync(id, false, options, cancellationToken);
    public Task<AssetState> DeleteAssetAsync(long id, RequestOptions? options = null, CancellationToken cancellationToken = default) => AssetAsync(id, true, options, cancellationToken);
    private Task<AssetState> AssetAsync(long id, bool delete, RequestOptions? options, CancellationToken cancellationToken)
    {
        Validation.Id(id);
        return transport.SendAsync($"/api/assets/{id}", delete ? HttpMethod.Delete : HttpMethod.Get, body =>
        {
            var result = Validation.Asset(body);
            if (result.Id != id || (delete && result.DeletionStatus == "active")) throw KompressrException.BadResponse();
            return result;
        }, options, cancellationToken, assetId: delete ? id : null);
    }
    public Task<BulkDeletion> BulkDeleteAssetsAsync(IReadOnlyList<long> ids, RequestOptions? options = null, CancellationToken cancellationToken = default)
    {
        if (ids is null || ids.Count is < 1 or > 100) throw KompressrException.Invalid("Select from 1 to 100 explicit asset IDs.");
        long[] snapshot = ids.Select(Validation.Id).ToArray();
        long[] expected = snapshot.Distinct().ToArray();
        return transport.SendAsync("/api/assets/bulk-delete", HttpMethod.Post, body => Validation.Bulk(body, expected), options, cancellationToken, Transport.Json(new { asset_ids = snapshot }));
    }
    internal static List<KeyValuePair<string, string>> Pagination(PageOptions options, int? page = null) =>
        [new("page", Validation.Positive(page ?? options.Page, "Page").ToString(CultureInfo.InvariantCulture)), new("limit", Validation.Positive(options.Limit, "Limit", 100).ToString(CultureInfo.InvariantCulture))];
    internal static string Query(IEnumerable<KeyValuePair<string, string>> values) => string.Join("&", values.Select(pair => Uri.EscapeDataString(pair.Key) + "=" + Uri.EscapeDataString(pair.Value)));
    private static KompressrException CancelledBeforeDispatch() => new("Request cancelled.", "cancelled", "REQUEST_CANCELLED");
}
