package com.kompressr;

import java.util.List;
import java.util.Map;

/** Validated response records. Optional fields are null; links and issued keys are secrets. */
public final class Models {
    private Models() {}
    public record UploadAccepted(long id, String status, String deletionStatus, String visibility,
        String originalName, long originalSize, String assetType, String deletionRequestedAt,
        String cdnUrl, String cdnUrlAvif, String privateUrl, String privateUrlExpiresAt,
        Map<String, Object> data, String externalId, Map<String, String> options, String quality, String warning) {
        @Override public String toString() { return "UploadAccepted[id=" + id + ", status=" + status + "]"; }
    }
    public record UploadAsset(long id, String status, String deletionStatus, String visibility,
        String originalName, long originalSize, String assetType, String deletionRequestedAt,
        String cdnUrl, String cdnUrlAvif, String privateUrl, String privateUrlExpiresAt,
        Map<String, Object> data, String externalId, Map<String, String> options, String quality, String warning,
        long kompressdSize, double savingsPercent, boolean canGeneratePrivateUrl,
        String inputFormat, String outputFormat, String createdAt) {
        @Override public String toString() { return "UploadAsset[id=" + id + ", status=" + status + "]"; }
    }
    public record PrivateUrl(long assetId, String variant, String privateUrl, String expiresAt, int expiresIn) {
        @Override public String toString() { return "PrivateUrl[assetId=" + assetId + ", variant=" + variant + "]"; }
    }
    public record Page<T>(List<T> data, long page, long limit, long total) {
        public Page { data = List.copyOf(data); }
    }
    public record Failure(String code, String message, String at) {}
    public record AssetState(long id, String projectId, long kind, String source, long processingStatus,
        String deletionStatus, long storageCreditedMb, String deletionRequestedAt,
        String accountingStatus, Failure lastFailure) {}
    public record BulkItem(long id, int status, boolean accepted, AssetState state, String code, String error) {}
    public record Counts(int total, int accepted, int failed) {}
    public record BulkDeletion(List<BulkItem> results, Counts counts) {
        public BulkDeletion { results = List.copyOf(results); }
    }
    public record ProjectUser(String id, String projectId, String customerUserId, String displayName,
        String status, Map<String, Object> metadata, Long assetCount, Long storageBytes, Long activeKeyCount,
        Long bandwidthBytesCurrentPeriod, Long requestsCurrentPeriod, String lastSeenAt,
        String lastUploadAt, String lastKeyUsedAt, String createdAt) {}
    public record UsagePeriod(String start, String end) {}
    public record ProjectUserPage(List<ProjectUser> data, long page, long limit, long total,
        long projectActiveCount, long orgActiveCount, UsagePeriod usagePeriod) {
        public ProjectUserPage { data = List.copyOf(data); }
    }
    public record UploadKey(String id, String keyId, String projectId, String projectUserId,
        String name, List<String> scopes, String allowedVisibility, List<Integer> allowedAssetTypes,
        String expiresAt, String revokedAt, String lastUsedAt, String createdAt) {
        public UploadKey { scopes = List.copyOf(scopes); if (allowedAssetTypes != null) allowedAssetTypes = List.copyOf(allowedAssetTypes); }
    }
    public record IssuedKey(String id, String keyId, String apiKey, UploadKey uploadKey) {
        @Override public String toString() { return "IssuedKey[id=" + id + ", keyId=" + keyId + ", apiKey=[redacted]]"; }
    }
}
