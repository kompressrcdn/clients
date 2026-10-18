package com.kompressr;

import java.util.LinkedHashMap;
import java.util.Map;

/** Safe structured failure. Cancellation does not roll back accepted writes. */
public final class KompressrException extends RuntimeException {
    private final String kind, code;
    private final Integer status;
    private final Long retryAfterMs, assetId;
    private final boolean mayHaveSucceeded;

    KompressrException(String message, String kind, String code, Integer status,
                       Long retryAfterMs, Long assetId, boolean mayHaveSucceeded) {
        super(message);
        this.kind = kind; this.code = code; this.status = status;
        this.retryAfterMs = retryAfterMs; this.assetId = assetId;
        this.mayHaveSucceeded = mayHaveSucceeded;
    }
    public String kind() { return kind; }
    public String code() { return code; }
    public Integer status() { return status; }
    public Long retryAfterMs() { return retryAfterMs; }
    public Long assetId() { return assetId; }
    public boolean mayHaveSucceeded() { return mayHaveSucceeded; }
    public Map<String, Object> details() {
        var result = new LinkedHashMap<String, Object>();
        result.put("message", getMessage()); result.put("kind", kind); result.put("code", code);
        if (status != null) result.put("status", status);
        if (retryAfterMs != null) result.put("retryAfterMs", retryAfterMs);
        if (assetId != null) result.put("assetId", assetId);
        result.put("mayHaveSucceeded", mayHaveSucceeded);
        return java.util.Collections.unmodifiableMap(result);
    }
    KompressrException context(Integer status, Long id, boolean ambiguous) {
        return new KompressrException(getMessage(), kind, code, status, retryAfterMs, id, ambiguous);
    }
    static KompressrException invalid(String message) {
        return new KompressrException(message, "validation", "INVALID_ARGUMENT", null, null, null, false);
    }
    static KompressrException response() {
        return new KompressrException("The API returned an invalid response.", "invalid_response", "INVALID_RESPONSE", null, null, null, false);
    }
    static String safe(String message, String secret) {
        if (message == null) return "Kompressr request failed.";
        String safe = secret == null || secret.isEmpty() ? message : message.replace(secret, "[redacted]");
        safe = safe.replaceAll("(?i)Bearer\\s+\\S+", "Bearer [redacted]")
            .replaceAll("(?i)https?://[^\\s<>\"']+", "[URL redacted]")
            .replaceAll("(?i)\\b(?:api_key|password|token|secret|signature)\\s*[=:]\\s*\\S+", "[credential redacted]");
        return safe.substring(0, Math.min(500, safe.length()));
    }
}
