using System.Text.Json;
namespace Kompressr.Sdk;

public class UploadAccepted
{
    public long Id { get; init; }
    public required string Status { get; init; }
    public required string DeletionStatus { get; init; }
    public string? DeletionRequestedAt { get; init; }
    public required string Visibility { get; init; }
    public string? OriginalName { get; init; }
    public long OriginalSize { get; init; }
    public required string AssetType { get; init; }
    public string? CdnUrl { get; init; }
    public string? CdnUrlAvif { get; init; }
    public string? PrivateUrl { get; init; }
    public string? PrivateUrlExpiresAt { get; init; }
    public IReadOnlyDictionary<string, JsonElement>? Data { get; init; }
    public string? ExternalId { get; init; }
    public IReadOnlyDictionary<string, string>? Options { get; init; }
    public string? Quality { get; init; }
    public string? Warning { get; init; }
}
public sealed class UploadAsset : UploadAccepted
{
    public long KompressdSize { get; init; }
    public double SavingsPercent { get; init; }
    public bool CanGeneratePrivateUrl { get; init; }
    public string? InputFormat { get; init; }
    public string? OutputFormat { get; init; }
    public string? CreatedAt { get; init; }
}
public sealed class PrivateUrl
{
    public long AssetId { get; init; }
    public required string Variant { get; init; }
    public required string Url { get; init; }
    public required string ExpiresAt { get; init; }
    public int ExpiresIn { get; init; }
}
public sealed class AssetState
{
    public long Id { get; init; }
    public required string ProjectId { get; init; }
    public long Kind { get; init; }
    public required string Source { get; init; }
    public long ProcessingStatus { get; init; }
    public required string DeletionStatus { get; init; }
    public string? DeletionRequestedAt { get; init; }
    public long StorageCreditedMb { get; init; }
    public string? AccountingStatus { get; init; }
    public AssetFailure? LastFailure { get; init; }
}
public sealed class AssetFailure
{
    public required string Code { get; init; }
    public required string Message { get; init; }
    public required string At { get; init; }
}
public class Page<T>
{
    public required IReadOnlyList<T> Data { get; init; }
    public int PageNumber { get; init; }
    public int Limit { get; init; }
    public long Total { get; init; }
}
public sealed class BulkDeletion
{
    public required IReadOnlyList<BulkDeletionItem> Results { get; init; }
    public required BulkDeletionCounts Counts { get; init; }
}
public sealed class BulkDeletionItem
{
    public long Id { get; init; }
    public int Status { get; init; }
    public bool Accepted { get; init; }
    public AssetState? State { get; init; }
    public string? Code { get; init; }
    public string? Error { get; init; }
}
public sealed class BulkDeletionCounts
{
    public int Total { get; init; }
    public int Accepted { get; init; }
    public int Failed { get; init; }
}
public sealed class ProjectUser
{
    public required string Id { get; init; }
    public required string ProjectId { get; init; }
    public required string CustomerUserId { get; init; }
    public string? DisplayName { get; init; }
    public required string Status { get; init; }
    public IReadOnlyDictionary<string, JsonElement>? Metadata { get; init; }
    public long? AssetCount { get; init; }
    public long? StorageBytes { get; init; }
    public long? ActiveKeyCount { get; init; }
    public long? BandwidthBytesCurrentPeriod { get; init; }
    public long? RequestsCurrentPeriod { get; init; }
    public string? LastSeenAt { get; init; }
    public string? LastUploadAt { get; init; }
    public string? LastKeyUsedAt { get; init; }
    public string? CreatedAt { get; init; }
}
public sealed class ProjectUserPage : Page<ProjectUser>
{
    public long ProjectActiveCount { get; init; }
    public long OrgActiveCount { get; init; }
    public UsagePeriod? UsagePeriod { get; init; }
}
public sealed class UsagePeriod
{
    public required string Start { get; init; }
    public required string End { get; init; }
}
public sealed class CreatedUser
{
    public bool Created { get; init; }
    public required ProjectUser ProjectUser { get; init; }
}
public sealed class UploadKey
{
    public required string Id { get; init; }
    public required string KeyId { get; init; }
    public required string ProjectId { get; init; }
    public required string ProjectUserId { get; init; }
    public required string Name { get; init; }
    public required IReadOnlyList<string> Scopes { get; init; }
    public required string AllowedVisibility { get; init; }
    public IReadOnlyList<long>? AllowedAssetTypes { get; init; }
    public string? ExpiresAt { get; init; }
    public string? RevokedAt { get; init; }
    public string? LastUsedAt { get; init; }
    public string? CreatedAt { get; init; }
}
public sealed class IssuedKey
{
    public required string Id { get; init; }
    public required string KeyId { get; init; }
    public required string ApiKey { get; init; }
    public UploadKey? UploadKey { get; init; }
}
