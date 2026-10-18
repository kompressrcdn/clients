package com.kompressr;

import org.apache.hc.client5.http.entity.mime.MultipartEntityBuilder;
import org.apache.hc.core5.http.ContentType;
import org.apache.hc.core5.http.HttpEntity;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static com.kompressr.Models.*;

/** Thread-safe synchronous client. Close it when its owning application shuts down. */
public final class KompressrClient implements AutoCloseable {
    private final Transport transport;
    private final String projectId;
    private final PlatformClient platform;
    private KompressrClient(Builder builder) {
        transport = new Transport(builder); projectId = builder.projectId; platform = new PlatformClient(transport);
    }
    public static Builder builder(String apiKey) { return new Builder(apiKey); }
    public static final class Builder {
        final String apiKey;
        String projectId, apiBaseUrl, uploadBaseUrl;
        Duration requestTimeout, uploadTimeout;
        int maxReadRetries = 2;
        org.apache.hc.client5.http.DnsResolver dnsResolver;
        private Builder(String apiKey) { this.apiKey = apiKey; }
        public Builder projectId(String value) { projectId = value; return this; }
        public Builder apiBaseUrl(String value) { apiBaseUrl = value; return this; }
        public Builder uploadBaseUrl(String value) { uploadBaseUrl = value; return this; }
        public Builder requestTimeout(Duration value) { requestTimeout = value; return this; }
        public Builder uploadTimeout(Duration value) { uploadTimeout = value; return this; }
        public Builder maxReadRetries(int value) { maxReadRetries = value; return this; }
        public KompressrClient build() { return new KompressrClient(this); }
    }
    public String apiBaseUrl() { return transport.apiBaseUrl; }
    public String uploadBaseUrl() { return transport.uploadBaseUrl; }
    public PlatformClient platform() { return platform; }
    public UploadAccepted uploadFile(Path path) throws IOException { return uploadFile(path, Options.Upload.DEFAULT, Options.Request.DEFAULT); }
    public UploadAccepted uploadFile(Path path, Options.Upload options) throws IOException { return uploadFile(path, options, Options.Request.DEFAULT); }
    public UploadAccepted uploadFile(Path path, Options.Upload options, Options.Request request) throws IOException {
        Validation.require(path != null && path.getFileName() != null, "Supply a file path.");
        if (!Files.isRegularFile(path) || !Files.isReadable(path)) throw new IOException("Upload file is not a readable regular file.");
        var multipart = multipart(path.getFileName().toString(), options);
        multipart.addBinaryBody("file", path.toFile(), ContentType.APPLICATION_OCTET_STREAM, filename(path.getFileName().toString()));
        return upload(multipart.build(), request);
    }
    public UploadAccepted uploadBytes(byte[] bytes, String filename) { return uploadBytes(bytes, filename, Options.Upload.DEFAULT, Options.Request.DEFAULT); }
    public UploadAccepted uploadBytes(byte[] bytes, String filename, Options.Upload options) { return uploadBytes(bytes, filename, options, Options.Request.DEFAULT); }
    public UploadAccepted uploadBytes(byte[] bytes, String filename, Options.Upload options, Options.Request request) {
        Validation.require(bytes != null, "Supply upload bytes.");
        var multipart = multipart(filename, options);
        multipart.addBinaryBody("file", bytes.clone(), ContentType.APPLICATION_OCTET_STREAM, filename(filename));
        return upload(multipart.build(), request);
    }
    private UploadAccepted upload(HttpEntity body, Options.Request request) {
        return transport.request("POST", "/api/upload", body, request, true, null, true, Validation::accepted);
    }
    private static String filename(String value) {
        Validation.require(value != null && !value.isBlank() && value.chars().noneMatch(c -> c < 32 || c == 127), "Supply a nonempty filename without control characters.");
        String name = value.substring(Math.max(value.lastIndexOf('/'), value.lastIndexOf('\\')) + 1);
        Validation.require(!name.isBlank(), "Supply a filename."); return name;
    }
    private static MultipartEntityBuilder multipart(String filename, Options.Upload supplied) {
        filename(filename); Options.Upload o = supplied == null ? Options.Upload.DEFAULT : supplied;
        var builder = MultipartEntityBuilder.create().setCharset(StandardCharsets.UTF_8);
        if (o.visibility() != null) builder.addTextBody("visibility", Validation.choice(o.visibility(), "public", "private"), ContentType.TEXT_PLAIN.withCharset(StandardCharsets.UTF_8));
        if (o.quality() != null) builder.addTextBody("kmp-quality", Validation.choice(o.quality(), "480p", "720p", "1080p", "4k"), ContentType.TEXT_PLAIN);
        if (o.privateUrlExpiresIn() != null) builder.addTextBody("private_url_expires_in", String.valueOf(ttl(o.privateUrlExpiresIn())), ContentType.TEXT_PLAIN);
        if (o.data() != null) builder.addTextBody("data", new String(Validation.json(Validation.metadata(o.data(), 4096)), StandardCharsets.UTF_8), ContentType.TEXT_PLAIN.withCharset(StandardCharsets.UTF_8));
        return builder;
    }
    static int ttl(Integer seconds) { int value = Validation.positive(seconds, 3600, 604800); Validation.require(value >= 60, "Private URL lifetime must be 60–604800 seconds."); return value; }
    public UploadAsset getUploadStatus(long id) { return getUploadStatus(id, Options.Request.DEFAULT); }
    public UploadAsset getUploadStatus(long id, Options.Request request) {
        Validation.id(id);
        return transport.request("GET", "/api/upload/" + id + "/status", null, request, false, null, false, root -> {
            var result = Validation.uploadAsset(Validation.data(root)); Validation.shape(result.id() == id); return result;
        });
    }
    public UploadAsset waitUntilReady(long id) { return waitUntilReady(id, Options.Wait.DEFAULT); }
    public UploadAsset waitUntilReady(long id, Options.Wait supplied) {
        Validation.id(id); Options.Wait options = supplied == null ? Options.Wait.DEFAULT : supplied;
        long timeout = Validation.millis(options.timeout(), 120_000, Integer.MAX_VALUE);
        long interval = Validation.millis(options.pollInterval(), 2000, 30_000);
        long deadline = System.nanoTime() + timeout * 1_000_000;
        var request = new Options.Request(null, options.cancellation());
        try {
            while (true) {
                if (Transport.cancelled(request)) throw Transport.stopped(true, null, id, false);
                long remaining = (deadline - System.nanoTime()) / 1_000_000;
                if (remaining <= 0) throw Transport.stopped(false, null, id, false);
                var result = getUploadStatus(id, new Options.Request(Duration.ofMillis(Math.min(remaining, transport.requestTimeout)), options.cancellation()));
                if (System.nanoTime() >= deadline) throw Transport.stopped(false, null, id, false);
                if (!result.deletionStatus().equals("active")) throw new KompressrException("The asset is being deleted or has been deleted.", "processing", "ASSET_DELETED", null, null, id, false);
                if (result.status().equals("processed")) {
                    Validation.shape(result.visibility().equals("public") ? result.cdnUrl() != null : result.canGeneratePrivateUrl()); return result;
                }
                if (!result.status().equals("pending") && !result.status().equals("processing")) throw new KompressrException("Asset processing ended with status " + result.status() + ".", "processing", "PROCESSING_FAILED", null, null, id, false);
                Transport.pause(Math.min(30_000, interval + java.util.concurrent.ThreadLocalRandom.current().nextLong(Math.max(1, Math.min(interval / 10, 250)))), deadline, request);
            }
        } catch (KompressrException e) {
            if (Transport.cancelled(request) || System.nanoTime() >= deadline - 1_000_000) {
                boolean cancelled = Transport.cancelled(request);
                throw new KompressrException("Waiting stopped; resume status checks with the saved asset ID.", cancelled ? "cancelled" : "timeout", cancelled ? "WAIT_CANCELLED" : "WAIT_TIMEOUT", e.status(), e.retryAfterMs(), id, false);
            }
            throw e.context(e.status(), id, false);
        }
    }
    public PrivateUrl generatePrivateUrl(long id) { return generatePrivateUrl(id, Options.Signing.DEFAULT, Options.Request.DEFAULT); }
    public PrivateUrl generatePrivateUrl(long id, Options.Signing options) { return generatePrivateUrl(id, options, Options.Request.DEFAULT); }
    public PrivateUrl generatePrivateUrl(long id, Options.Signing supplied, Options.Request request) {
        Validation.id(id); var options = supplied == null ? Options.Signing.DEFAULT : supplied;
        var body = Map.of("expires_in", ttl(options.expiresIn()), "variant", Validation.choice(options.variant() == null ? "webp" : options.variant(), "webp", "avif"));
        return transport.request("POST", "/api/upload/" + id + "/private-url", Transport.json(body), request, false, id, false, root -> {
            var result = Validation.privateUrl(Validation.data(root)); Validation.shape(result.assetId() == id); return result;
        });
    }
    static LinkedHashMap<String, String> pagination(Integer page, Integer limit) {
        var result = new LinkedHashMap<String, String>(); result.put("page", String.valueOf(Validation.positive(page, 1, Integer.MAX_VALUE))); result.put("limit", String.valueOf(Validation.positive(limit, 20, 100))); return result;
    }
    static String query(Map<String, String> params) {
        var join = new StringJoiner("&"); params.forEach((k, v) -> join.add(URLEncoder.encode(k, StandardCharsets.UTF_8) + "=" + URLEncoder.encode(v, StandardCharsets.UTF_8))); return join.toString();
    }
    static void deletionFilter(Map<String, String> params, String deletion) { if (deletion != null) params.put("deletion_status", Validation.choice(deletion, "active", "deleting", "deleted", "legacy_deleted")); }
    public Page<UploadAsset> listUploads() { return listUploads(Options.UploadFilters.DEFAULT, Options.Request.DEFAULT); }
    public Page<UploadAsset> listUploads(Options.UploadFilters options) { return listUploads(options, Options.Request.DEFAULT); }
    public Page<UploadAsset> listUploads(Options.UploadFilters supplied, Options.Request request) {
        var o = supplied == null ? Options.UploadFilters.DEFAULT : supplied;
        var params = pagination(o.page(), o.limit()); params.put("project_id", Validation.uuid(o.projectId() == null ? projectId : o.projectId()));
        if (o.visibility() != null) params.put("visibility", Validation.choice(o.visibility(), "public", "private"));
        deletionFilter(params, o.deletionStatus());
        if (o.status() != null) { String status = Map.of("pending", "1", "processing", "2", "processed", "3", "failed", "4", "unprocessable", "5").getOrDefault(o.status(), o.status()); params.put("status", Validation.choice(status, "1", "2", "3", "4", "5", "6")); }
        if (o.externalId() != null) { Validation.require(Validation.bytes(o.externalId()) <= 512, "externalId exceeds 512 UTF-8 bytes."); params.put("external_id", o.externalId()); }
        if (o.data() != null) Validation.metadata(o.data(), 4096).forEach((key, value) -> { Validation.require(value instanceof String, "Data filter values must be strings."); params.put("data." + key, (String)value); });
        return transport.request("GET", "/api/uploads?" + query(params), null, request, false, null, false, root -> Validation.page(Validation.success(root), "data", Validation::uploadAsset));
    }
    public Iterable<UploadAsset> iterateUploads() { return iterateUploads(Options.UploadFilters.DEFAULT, Options.Request.DEFAULT); }
    public Iterable<UploadAsset> iterateUploads(Options.UploadFilters options) { return iterateUploads(options, Options.Request.DEFAULT); }
    public Iterable<UploadAsset> iterateUploads(Options.UploadFilters supplied, Options.Request request) {
        var options = supplied == null ? Options.UploadFilters.DEFAULT : supplied;
        return () -> new Iterator<>() {
            private Iterator<UploadAsset> rows = Collections.emptyIterator();
            private int nextPage = Validation.positive(options.page(), 1, Integer.MAX_VALUE);
            private boolean done;
            @Override public boolean hasNext() {
                if (Transport.cancelled(Transport.options(request))) throw Transport.stopped(true, null, null, false);
                if (rows.hasNext()) return true;
                if (done) return false;
                var page = listUploads(options.withPage(nextPage), request);
                Validation.shape(page.page() == nextPage && page.data().size() <= page.limit());
                rows = page.data().iterator(); done = page.data().isEmpty() || page.page() >= (page.total() + page.limit() - 1) / page.limit();
                if (!done) { Validation.shape(nextPage < Integer.MAX_VALUE); nextPage++; }
                return rows.hasNext();
            }
            @Override public UploadAsset next() { if (!hasNext()) throw new NoSuchElementException(); return rows.next(); }
        };
    }
    public Page<AssetState> listAssets() { return listAssets(Options.AssetFilters.DEFAULT, Options.Request.DEFAULT); }
    public Page<AssetState> listAssets(Options.AssetFilters options) { return listAssets(options, Options.Request.DEFAULT); }
    public Page<AssetState> listAssets(Options.AssetFilters supplied, Options.Request request) {
        var o = supplied == null ? Options.AssetFilters.DEFAULT : supplied;
        var params = pagination(o.page(), o.limit()); deletionFilter(params, o.deletionStatus());
        return transport.request("GET", "/api/assets?" + query(params), null, request, false, null, false, root -> Validation.page(root, "data", Validation::state));
    }
    public AssetState getAsset(long id) { return getAsset(id, Options.Request.DEFAULT); }
    public AssetState getAsset(long id, Options.Request request) {
        Validation.id(id); return transport.request("GET", "/api/assets/" + id, null, request, false, null, false, root -> { var state = Validation.state(root); Validation.shape(state.id() == id); return state; });
    }
    public AssetState deleteAsset(long id) { return deleteAsset(id, Options.Request.DEFAULT); }
    public AssetState deleteAsset(long id, Options.Request request) {
        Validation.id(id); return transport.request("DELETE", "/api/assets/" + id, null, request, false, id, false, root -> { var state = Validation.state(root); Validation.shape(state.id() == id && !state.deletionStatus().equals("active")); return state; });
    }
    public BulkDeletion bulkDeleteAssets(List<Long> ids) { return bulkDeleteAssets(ids, Options.Request.DEFAULT); }
    public BulkDeletion bulkDeleteAssets(List<Long> ids, Options.Request request) {
        Validation.require(ids != null && !ids.isEmpty() && ids.size() <= 100, "Select 1–100 explicit asset IDs.");
        for (Long id : ids) { Validation.require(id != null, "Use a valid asset ID."); Validation.id(id); }
        var snapshot = List.copyOf(ids); var expected = new ArrayList<>(new LinkedHashSet<>(snapshot));
        return transport.request("POST", "/api/assets/bulk-delete", Transport.json(Map.of("asset_ids", snapshot)), request, false, null, false, root -> Validation.bulk(root, expected));
    }
    @Override public void close() { transport.close(); }
}
