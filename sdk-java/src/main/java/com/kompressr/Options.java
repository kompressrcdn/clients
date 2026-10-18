package com.kompressr;

import java.time.Duration;
import java.util.List;
import java.util.Map;

/** Per-operation option records. Do not mutate collection inputs during a call. Null optional values select defaults. */
public final class Options {
    private Options() {}
    public record Request(Duration timeout, CancellationToken cancellation) {
        public static final Request DEFAULT = new Request(null, null);
        public static Request timeout(Duration timeout) { return new Request(timeout, null); }
    }
    public record Upload(String visibility, String quality, Map<String, Object> data, Integer privateUrlExpiresIn) {
        public static final Upload DEFAULT = new Upload(null, null, null, null);
        public static Upload privateFile() { return new Upload("private", null, null, null); }
        public static Upload publicFile() { return new Upload("public", null, null, null); }
    }
    public record Wait(Duration timeout, Duration pollInterval, CancellationToken cancellation) {
        public static final Wait DEFAULT = new Wait(null, null, null);
    }
    public record Signing(Integer expiresIn, String variant) {
        public static final Signing DEFAULT = new Signing(null, null);
    }
    public record Pagination(Integer page, Integer limit) {
        public static final Pagination DEFAULT = new Pagination(null, null);
    }
    public record UploadFilters(String projectId, Integer page, Integer limit, String visibility,
            String status, String externalId, Map<String, String> data, String deletionStatus) {
        public static final UploadFilters DEFAULT = new UploadFilters(null, null, null, null, null, null, null, null);
        public UploadFilters withPage(int page) { return new UploadFilters(projectId, page, limit, visibility, status, externalId, data, deletionStatus); }
    }
    public record AssetFilters(Integer page, Integer limit, String deletionStatus) {
        public static final AssetFilters DEFAULT = new AssetFilters(null, null, null);
    }
    public record CreateUser(String customerUserId, String displayName, Map<String, Object> metadata) {}
    public record UpdateUser(String displayName, Map<String, Object> metadata) {}
    public record CreateKey(String name, List<String> scopes, String allowedVisibility,
            List<Integer> allowedAssetTypes, String expiresAt) {
        public CreateKey(String name) { this(name, null, null, null, null); }
    }
}
