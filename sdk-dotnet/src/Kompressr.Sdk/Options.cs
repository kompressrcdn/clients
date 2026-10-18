namespace Kompressr.Sdk;

public sealed class ClientOptions
{
    public required string ApiKey { get; init; }
    public string? ProjectId { get; init; }
    public string ApiBaseUrl { get; init; } = "https://kompressr.com";
    public string? UploadBaseUrl { get; init; }
    public TimeSpan RequestTimeout { get; init; } = TimeSpan.FromSeconds(30);
    public TimeSpan UploadTimeout { get; init; } = TimeSpan.FromMinutes(10);
    public int MaxReadRetries { get; init; } = 2;
}

public class RequestOptions
{
    public TimeSpan? Timeout { get; init; }
}
public sealed class UploadOptions : RequestOptions
{
    public string? Visibility { get; init; }
    public string? Quality { get; init; }
    public IReadOnlyDictionary<string, object?>? Data { get; init; }
    public int? PrivateUrlExpiresIn { get; init; }
}
public sealed class WaitOptions : RequestOptions
{
    public TimeSpan PollInterval { get; init; } = TimeSpan.FromSeconds(2);
}
public sealed class PrivateUrlOptions : RequestOptions
{
    public int ExpiresIn { get; init; } = 3600;
    public string Variant { get; init; } = "webp";
}
public class PageOptions : RequestOptions
{
    public int Page { get; init; } = 1;
    public int Limit { get; init; } = 20;
}
public sealed class UploadFilters : PageOptions
{
    public string? ProjectId { get; init; }
    public string? Visibility { get; init; }
    public string? ExternalId { get; init; }
    public IReadOnlyDictionary<string, string>? Data { get; init; }
    public string? Status { get; init; }
    public string? DeletionStatus { get; init; }
}
public sealed class AssetFilters : PageOptions
{
    public string? DeletionStatus { get; init; }
}
public sealed class CreateUserOptions
{
    public required string CustomerUserId { get; init; }
    public string? DisplayName { get; init; }
    public IReadOnlyDictionary<string, object?>? Metadata { get; init; }
}
public sealed class UpdateUserOptions
{
    public string? DisplayName { get; init; }
    public IReadOnlyDictionary<string, object?>? Metadata { get; init; }
}
public sealed class CreateKeyOptions
{
    public required string Name { get; init; }
    public IReadOnlyList<string>? Scopes { get; init; }
    public string? AllowedVisibility { get; init; }
    public IReadOnlyList<long>? AllowedAssetTypes { get; init; }
    public DateTimeOffset? ExpiresAt { get; init; }
}
