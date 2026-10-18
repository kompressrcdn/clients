package com.kompressr;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.core.JsonParser;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;
import java.util.function.Function;
import static com.kompressr.Models.*;

final class Validation {
    static final long MAX_SAFE = 9_007_199_254_740_991L;
    static final Set<String> SCOPES = Set.of("upload", "status", "list", "private_url", "delete");
    static final ObjectMapper JSON = new ObjectMapper().enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
        .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION);
    static void require(boolean condition, String message) { if (!condition) throw KompressrException.invalid(message); }
    static void shape(boolean condition) { if (!condition) throw KompressrException.response(); }
    static long id(long value) { require(value > 0 && value <= MAX_SAFE, "Use a positive safe integer asset ID."); return value; }
    static String uuid(String value) {
        require(value != null && value.matches("(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), "Use a UUID identifier."); return value;
    }
    static int positive(Integer value, int fallback, int max) { int v = value == null ? fallback : value; require(v > 0 && v <= max, "Value must be a positive integer within the supported range."); return v; }
    static long millis(Duration duration, long fallback, long max) {
        if (duration == null) return fallback;
        long value;
        try { value = duration.toMillis(); } catch (ArithmeticException e) { throw KompressrException.invalid("Invalid timeout."); }
        require(value > 0 && value <= max && duration.equals(Duration.ofMillis(value)), "Duration must be a positive whole number of milliseconds within the supported range."); return value;
    }
    static String choice(String value, String... allowed) { require(value != null && Arrays.asList(allowed).contains(value), "Unsupported option."); return value; }
    static int bytes(String value) { return value.getBytes(StandardCharsets.UTF_8).length; }
    static String textInput(String value, int maximum, boolean allowEmpty) {
        require(value != null && (allowEmpty || !value.isBlank()) && bytes(value.trim()) <= maximum, "Text exceeds the supported UTF-8 length or is empty."); return value;
    }
    static Map<String, Object> metadata(Map<String, ?> value, int maximum) {
        require(value != null && value.size() <= 5, "Customer data supports at most five scalar fields.");
        var result = new LinkedHashMap<String, Object>();
        for (var entry : value.entrySet()) {
            require(entry.getKey() != null, "Invalid data key.");
            String key = entry.getKey().trim(); Object v = entry.getValue();
            require(!key.isEmpty() && bytes(key) <= 64 && !result.containsKey(key), "Data keys must be unique and contain 1–64 UTF-8 bytes.");
            boolean valid = v == null || v instanceof Boolean || (v instanceof String s && bytes(s) <= 512)
                || (v instanceof Number n && Double.isFinite(n.doubleValue()));
            require(valid, "Data values must be finite scalar values; strings support 512 UTF-8 bytes.");
            result.put(key, v);
        }
        require(json(result).length <= maximum, "Encoded customer data exceeds the supported limit.");
        return Collections.unmodifiableMap(result);
    }
    static byte[] json(Object value) { try { return JSON.writeValueAsBytes(value); } catch (Exception e) { throw KompressrException.invalid("Value cannot be encoded as JSON."); } }
    static JsonNode object(JsonNode n) { shape(n != null && n.isObject()); return n; }
    static JsonNode success(JsonNode n) { object(n); shape(n.path("success").isBoolean() && n.path("success").booleanValue()); return n; }
    static JsonNode data(JsonNode n) { return object(success(n).get("data")); }
    static String string(JsonNode n) { shape(n != null && n.isTextual() && !n.textValue().isBlank()); return n.textValue(); }
    static String str(JsonNode n, String name) { return string(n.get(name)); }
    static String optional(JsonNode n, String name) { JsonNode v = n.get(name); if (v == null) return null; shape(v.isTextual()); return v.textValue(); }
    static String nullable(JsonNode n, String name) { return n.path(name).isNull() ? null : optional(n, name); }
    static long number(JsonNode n) { shape(n != null && n.isIntegralNumber() && n.canConvertToLong()); long v = n.longValue(); shape(v >= -MAX_SAFE && v <= MAX_SAFE); return v; }
    static long num(JsonNode n, String name) { return number(n.get(name)); }
    static long nonnegative(JsonNode n, String name) { long v = num(n, name); shape(v >= 0); return v; }
    static Long optionalNum(JsonNode n, String name) { return n.has(name) ? nonnegative(n, name) : null; }
    static long positiveResponse(JsonNode n, String name) { long v = num(n, name); shape(v > 0); return v; }
    static String enumResponse(JsonNode n, String name, String... values) { String s = str(n, name); shape(Arrays.asList(values).contains(s)); return s; }
    static boolean bool(JsonNode n, String name) { shape(n.path(name).isBoolean()); return n.get(name).booleanValue(); }
    static String deletion(JsonNode n) { return enumResponse(n, "deletion_status", "active", "deleting", "deleted", "legacy_deleted"); }
    static String delivery(JsonNode n, String name) {
        String value = optional(n, name); if (value == null) return null;
        try { var uri = new java.net.URI(value); shape(("https".equalsIgnoreCase(uri.getScheme()) || "http".equalsIgnoreCase(uri.getScheme())) && uri.getHost() != null && uri.getUserInfo() == null); }
        catch (java.net.URISyntaxException e) { throw KompressrException.response(); }
        return value;
    }
    static Map<String, Object> responseMetadata(JsonNode n, String name) {
        JsonNode value = n.get(name); if (value == null) return null; object(value);
        Map<String, Object> result = new LinkedHashMap<>();
        value.fields().forEachRemaining(e -> {
            var v = e.getValue(); shape(v.isNull() || v.isTextual() || v.isBoolean() || v.isNumber());
            result.put(e.getKey(), v.isNull() ? null : v.isTextual() ? v.textValue() : v.isBoolean() ? v.booleanValue() : v.numberValue());
        });
        try { return metadata(result, 8192); } catch (KompressrException e) { throw KompressrException.response(); }
    }
    static Map<String, String> stringMap(JsonNode n, String name) {
        if (!n.has(name)) return null;
        object(n.get(name)); var result = new LinkedHashMap<String, String>();
        n.get(name).fields().forEachRemaining(e -> { shape(e.getValue().isTextual()); result.put(e.getKey(), e.getValue().textValue()); });
        return Collections.unmodifiableMap(result);
    }
    static UploadAccepted upload(JsonNode n, boolean accepted) {
        object(n); long id = positiveResponse(n, accepted ? "asset_id" : "id");
        String status = enumResponse(n, "status", "pending", "processing", "processed", "failed", "unprocessable", "unknown");
        String visibility = enumResponse(n, "visibility", "public", "private"), deletion = deletion(n);
        String cdn = delivery(n, "cdn_url"), avif = delivery(n, "cdn_url_avif"), privateUrl = delivery(n, "private_url");
        shape(!visibility.equals("private") || (cdn == null && avif == null));
        shape(deletion.equals("active") || (cdn == null && avif == null && privateUrl == null));
        return new UploadAccepted(id, status, deletion, visibility,
            accepted ? str(n, "original_name") : optional(n, "original_name"), nonnegative(n, "original_size"), str(n, "asset_type"),
            optional(n, "deletion_requested_at"), cdn, avif, privateUrl, optional(n, "private_url_expires_at"), responseMetadata(n, "data"),
            optional(n, "external_id"), stringMap(n, "options"), optional(n, "quality"), optional(n, "warning"));
    }
    static UploadAccepted accepted(JsonNode root) {
        JsonNode n = data(root).deepCopy();
        if (root.path("warning").isTextual()) ((com.fasterxml.jackson.databind.node.ObjectNode)n).put("warning", root.get("warning").textValue());
        return upload(n, true);
    }
    static UploadAsset uploadAsset(JsonNode n) {
        var u = upload(n, false); var savings = n.get("savings_percent"); shape(savings != null && savings.isNumber() && Double.isFinite(savings.doubleValue()));
        return new UploadAsset(u.id(), u.status(), u.deletionStatus(), u.visibility(), u.originalName(), u.originalSize(), u.assetType(),
            u.deletionRequestedAt(), u.cdnUrl(), u.cdnUrlAvif(), u.privateUrl(), u.privateUrlExpiresAt(), u.data(), u.externalId(), u.options(), u.quality(), u.warning(),
            nonnegative(n, "kompressd_size"), savings.doubleValue(), bool(n, "can_generate_private_url"), optional(n, "input_format"), optional(n, "output_format"), optional(n, "created_at"));
    }
    static PrivateUrl privateUrl(JsonNode n) {
        object(n); long ttl = num(n, "expires_in"); shape(ttl >= 60 && ttl <= 604800);
        String url = delivery(n, "private_url"); shape(url != null);
        return new PrivateUrl(positiveResponse(n, "asset_id"), enumResponse(n, "variant", "webp", "avif"), url, str(n, "expires_at"), (int)ttl);
    }
    static AssetState state(JsonNode n) {
        object(n); String accounting = n.has("accounting_status") ? enumResponse(n, "accounting_status", "pending", "settled", "unavailable") : null;
        Failure failure = null;
        if (n.has("last_failure")) { var f = object(n.get("last_failure")); failure = new Failure(str(f, "code"), str(f, "message"), str(f, "at")); }
        return new AssetState(positiveResponse(n, "id"), str(n, "project_id"), positiveResponse(n, "kind"), enumResponse(n, "source", "upload", "origin"), num(n, "processing_status"), deletion(n), nonnegative(n, "storage_credited_mb"), optional(n, "deletion_requested_at"), accounting, failure);
    }
    static <T> Page<T> page(JsonNode n, String key, Function<JsonNode, T> parse) {
        object(n); shape(n.path(key).isArray()); var rows = new ArrayList<T>();
        n.get(key).forEach(row -> rows.add(parse.apply(row)));
        return new Page<>(rows, positiveResponse(n, "page"), positiveResponse(n, "limit"), nonnegative(n, "total"));
    }
    static BulkDeletion bulk(JsonNode n, List<Long> expected) {
        object(n); shape(n.path("results").isArray() && n.get("results").size() == expected.size());
        var rows = new ArrayList<BulkItem>(); int accepted = 0;
        for (int i = 0; i < expected.size(); i++) {
            var row = object(n.get("results").get(i)); long id = num(row, "id"), status = num(row, "status");
            shape(id == expected.get(i) && status >= 100 && status <= 599); boolean ok = bool(row, "accepted");
            AssetState state = ok ? state(row.get("state")) : null;
            if (ok) { shape((status == 200 || status == 202) && state.id() == id && !state.deletionStatus().equals("active")); accepted++; }
            else { shape(status >= 400); str(row, "error"); }
            rows.add(new BulkItem(id, (int)status, ok, state, optional(row, "code"), optional(row, "error")));
        }
        var counts = object(n.get("counts")); shape(num(counts, "total") == rows.size() && num(counts, "accepted") == accepted && num(counts, "failed") == rows.size() - accepted);
        return new BulkDeletion(rows, new Counts(rows.size(), accepted, rows.size() - accepted));
    }
    static ProjectUser user(JsonNode n) {
        object(n);
        return new ProjectUser(str(n, "id"), str(n, "project_id"), str(n, "customer_user_id"), optional(n, "display_name"), enumResponse(n, "status", "active", "suspended"), responseMetadata(n, "metadata"),
            optionalNum(n, "asset_count"), optionalNum(n, "storage_bytes"), optionalNum(n, "active_key_count"), optionalNum(n, "bandwidth_bytes_current_period"), optionalNum(n, "requests_current_period"),
            optional(n, "last_seen_at"), optional(n, "last_upload_at"), optional(n, "last_key_used_at"), optional(n, "created_at"));
    }
    static UploadKey key(JsonNode n) {
        object(n); shape(n.path("scopes").isArray()); var scopes = new ArrayList<String>();
        n.get("scopes").forEach(v -> { var s = string(v); shape(SCOPES.contains(s)); scopes.add(s); });
        List<Integer> types = null;
        if (n.has("allowed_asset_types")) { shape(n.get("allowed_asset_types").isArray()); types = new ArrayList<>(); for (var t : n.get("allowed_asset_types")) { long v = number(t); shape(v > 0 && v <= Integer.MAX_VALUE); types.add((int)v); } }
        return new UploadKey(str(n, "id"), str(n, "key_id"), str(n, "project_id"), str(n, "project_user_id"), str(n, "name"), scopes,
            enumResponse(n, "allowed_visibility", "public", "private", "both"), types, nullable(n, "expires_at"), nullable(n, "revoked_at"), nullable(n, "last_used_at"), optional(n, "created_at"));
    }
    static IssuedKey issued(JsonNode n) { success(n); return new IssuedKey(str(n, "id"), str(n, "key_id"), str(n, "api_key"), n.has("upload_key") ? key(n.get("upload_key")) : null); }
}
