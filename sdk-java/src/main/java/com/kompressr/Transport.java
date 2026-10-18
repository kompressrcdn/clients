package com.kompressr;

import com.fasterxml.jackson.databind.JsonNode;
import org.apache.hc.client5.http.classic.methods.HttpUriRequestBase;
import org.apache.hc.client5.http.DnsResolver;
import org.apache.hc.client5.http.SystemDefaultDnsResolver;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManagerBuilder;
import org.apache.hc.client5.http.impl.ChainElement;
import org.apache.hc.core5.io.CloseMode;
import org.apache.hc.client5.http.config.RequestConfig;
import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.core5.http.HttpEntity;
import org.apache.hc.core5.http.io.entity.ByteArrayEntity;
import org.apache.hc.core5.http.ContentType;
import org.apache.hc.core5.util.Timeout;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.URI;
import java.time.Duration;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Function;

final class Transport implements AutoCloseable {
    // A bounded worker pool keeps the caller deadline independent of JVM DNS and
    // provider I/O that may ignore interruption. Exhaustion fails instead of queuing forever.
    static final ThreadPoolExecutor IO = new ThreadPoolExecutor(0, 64, 30, TimeUnit.SECONDS,
        new SynchronousQueue<>(), action -> { var t = new Thread(action, "kompressr-http"); t.setDaemon(true); return t; });
    private record Deadline(long nanos, Options.Request options) {}
    private static final ThreadLocal<Deadline> ACTIVE = new ThreadLocal<>();
    static final ScheduledThreadPoolExecutor TIMER;
    static {
        TIMER = new ScheduledThreadPoolExecutor(1, action -> { var t = new Thread(action, "kompressr-deadlines"); t.setDaemon(true); return t; });
        TIMER.setRemoveOnCancelPolicy(true);
    }
    final String apiBaseUrl, uploadBaseUrl;
    final long requestTimeout, uploadTimeout;
    private final String key;
    private final int retries;
    private final CloseableHttpClient http;
    private volatile boolean closed;

    Transport(KompressrClient.Builder builder) {
        Validation.require(builder.apiKey != null && !builder.apiKey.isBlank() && !builder.apiKey.matches("(?s).*[\\r\\n].*"), "Supply a nonempty API key on your trusted backend.");
        key = builder.apiKey; apiBaseUrl = origin(builder.apiBaseUrl == null ? "https://kompressr.com" : builder.apiBaseUrl);
        uploadBaseUrl = origin(builder.uploadBaseUrl == null ? apiBaseUrl.equals("https://kompressr.com") ? "https://uploads.kompressr.com" : apiBaseUrl : builder.uploadBaseUrl);
        requestTimeout = Validation.millis(builder.requestTimeout, 30_000, Integer.MAX_VALUE);
        uploadTimeout = Validation.millis(builder.uploadTimeout, 600_000, Integer.MAX_VALUE);
        Validation.require(builder.maxReadRetries >= 0 && builder.maxReadRetries <= 5, "maxReadRetries must be between zero and five."); retries = builder.maxReadRetries;
        DnsResolver resolver = builder.dnsResolver == null ? SystemDefaultDnsResolver.INSTANCE : builder.dnsResolver;
        DnsResolver guardedResolver = new DnsResolver() {
            private void check() throws java.net.UnknownHostException {
                Deadline active = ACTIVE.get();
                if (active != null && (System.nanoTime() >= active.nanos() || cancelled(active.options()))) throw new java.net.UnknownHostException("Request deadline or cancellation reached.");
            }
            @Override public java.net.InetAddress[] resolve(String host) throws java.net.UnknownHostException {
                check(); var result = resolver.resolve(host); check(); return result;
            }
            @Override public String resolveCanonicalHostname(String host) throws java.net.UnknownHostException {
                check(); var result = resolver.resolveCanonicalHostname(host); check(); return result;
            }
        };
        var manager = PoolingHttpClientConnectionManagerBuilder.create().setDnsResolver(guardedResolver).build();
        http = HttpClients.custom().setConnectionManager(manager).disableAutomaticRetries().disableRedirectHandling().disableCookieManagement().disableAuthCaching()
            .addExecInterceptorBefore(ChainElement.MAIN_TRANSPORT.name(), "kompressr-deadline", (request, scope, chain) -> {
                checkActiveDeadline(); return chain.proceed(request, scope);
            }).build();
    }
    static String origin(String input) {
        try {
            var uri = new URI(input);
            Validation.require(("https".equalsIgnoreCase(uri.getScheme()) || "http".equalsIgnoreCase(uri.getScheme())) && uri.getHost() != null && uri.getUserInfo() == null && uri.getQuery() == null && uri.getFragment() == null && (uri.getPath().isEmpty() || uri.getPath().equals("/")), "Base URL must be an HTTP(S) origin without credentials, path, query or fragment.");
            String scheme = uri.getScheme().toLowerCase(java.util.Locale.ROOT), host = uri.getHost().toLowerCase(java.util.Locale.ROOT);
            int port = uri.getPort(); Validation.require(port >= -1 && port <= 65535 && port != 0, "Invalid origin port.");
            if ((scheme.equals("https") && port == 443) || (scheme.equals("http") && port == 80)) port = -1;
            return new URI(scheme, null, host, port, null, null, null).toString();
        } catch (java.net.URISyntaxException | NullPointerException e) { throw KompressrException.invalid("Base URL must be an absolute HTTP(S) origin."); }
    }
    static HttpEntity json(Object body) { return body == null ? null : new ByteArrayEntity(Validation.json(body), ContentType.APPLICATION_JSON); }
    static Options.Request options(Options.Request options) { return options == null ? Options.Request.DEFAULT : options; }
    static boolean cancelled(Options.Request options) { return Thread.currentThread().isInterrupted() || options.cancellation() != null && options.cancellation().isCancelled(); }
    static KompressrException stopped(boolean cancelled, Integer status, Long id, boolean ambiguous) {
        return new KompressrException(cancelled ? "Request cancelled." : "Request timed out; inspect the outcome before retrying a write.", cancelled ? "cancelled" : "timeout", cancelled ? "REQUEST_CANCELLED" : "REQUEST_TIMEOUT", status, null, id, ambiguous);
    }
    static void pause(long millis, long deadline, Options.Request options) {
        long end = System.nanoTime() + Math.min(millis, Integer.MAX_VALUE) * 1_000_000;
        while (System.nanoTime() < end) {
            if (cancelled(options)) throw stopped(true, null, null, false);
            if (System.nanoTime() >= deadline) throw stopped(false, null, null, false);
            long remain = Math.min(end - System.nanoTime(), deadline - System.nanoTime());
            try { TimeUnit.NANOSECONDS.sleep(Math.min(10_000_000, Math.max(1, remain))); }
            catch (InterruptedException e) { Thread.currentThread().interrupt(); throw stopped(true, null, null, false); }
        }
    }
    <T> T request(String method, String path, HttpEntity body, Options.Request requested,
                  boolean upload, Long assetId, boolean recoverId, Function<JsonNode, T> parse) {
        Options.Request options = options(requested);
        long timeout = Validation.millis(options.timeout(), upload ? uploadTimeout : requestTimeout, Integer.MAX_VALUE);
        long deadline = System.nanoTime() + timeout * 1_000_000;
        boolean read = method.equals("GET"), dispatched = false;
        Long knownId = assetId;
        for (int attempt = 0; ; attempt++) {
            if (cancelled(options)) throw stopped(true, null, knownId, dispatched && !read);
            if (System.nanoTime() >= deadline) throw stopped(false, null, knownId, dispatched && !read);
            Validation.require(!closed, "Client is closed.");
            var request = new HttpUriRequestBase(method, URI.create((upload ? uploadBaseUrl : apiBaseUrl) + path));
            request.setHeader("Authorization", "Bearer " + key); request.setHeader("Accept", "application/json");
            if (body != null) request.setEntity(body);
            long remaining = Math.max(1, (deadline - System.nanoTime() + 999_999) / 1_000_000);
            request.setConfig(RequestConfig.custom().setConnectionRequestTimeout(Timeout.ofMilliseconds(remaining)).setResponseTimeout(Timeout.ofMilliseconds(remaining)).build());
            AtomicInteger status = new AtomicInteger(0);
            AtomicReference<Long> recovered = new AtomicReference<>(knownId);
            Thread caller = Thread.currentThread();
            AutoCloseable registration = options.cancellation() == null ? () -> {} : options.cancellation().register(request::cancel);
            var watchdog = TIMER.scheduleAtFixedRate(() -> {
                if (System.nanoTime() >= deadline || caller.isInterrupted()) request.cancel();
            }, 1, 5, TimeUnit.MILLISECONDS);
            KompressrException failure;
            try {
                if (cancelled(options)) throw stopped(true, null, knownId, dispatched && !read);
                if (System.nanoTime() >= deadline) throw stopped(false, null, knownId, dispatched && !read);
                Future<T> running = IO.submit(() -> {
                    ACTIVE.set(new Deadline(deadline, options));
                    try {
                        checkActiveDeadline();
                        return http.execute(request, response -> {
                    int code = response.getCode(); status.set(code); boolean ok = code >= 200 && code < 300;
                    JsonNode root = null;
                    try {
                        var entity = response.getEntity();
                        if (entity == null) throw KompressrException.response();
                        try (var stream = entity.getContent(); var bytes = new ByteArrayOutputStream()) {
                            byte[] buffer = new byte[8192]; int count;
                            while ((count = stream.read(buffer)) != -1) {
                                if (bytes.size() + count > 2 * 1024 * 1024) { request.cancel(); throw KompressrException.response(); }
                                bytes.write(buffer, 0, count);
                            }
                            try { root = Validation.JSON.readTree(bytes.toByteArray()); }
                            catch (IOException e) { throw KompressrException.response(); }
                        }
                    } catch (KompressrException e) { if (ok) throw e; }
                    if (recoverId && ok && root != null && root.path("success").isBoolean() && root.path("success").booleanValue()) {
                        var id = root.path("data").get("asset_id");
                        if (id != null && id.isIntegralNumber() && id.canConvertToLong() && id.longValue() > 0 && id.longValue() <= Validation.MAX_SAFE) recovered.set(id.longValue());
                    }
                    if (!ok || root != null && root.path("success").isBoolean() && !root.path("success").booleanValue()) {
                        String message = root != null && root.path("error").isTextual() ? root.get("error").textValue() : "Kompressr returned HTTP " + code + ".";
                        String errorCode = root != null && root.path("code").isTextual() ? root.get("code").textValue() : "API_ERROR";
                        String header = response.getFirstHeader("Retry-After") == null ? null : response.getFirstHeader("Retry-After").getValue();
                        throw new KompressrException(KompressrException.safe(message, key), "api", KompressrException.safe(errorCode, key), code, retryAfter(header, root), recovered.get(), !read && (ok || code >= 500 || code >= 300 && code < 400));
                    }
                    try { return parse.apply(root); }
                    catch (KompressrException e) { throw e; }
                    catch (RuntimeException e) { throw KompressrException.response(); }
                        });
                    } finally { ACTIVE.remove(); }
                });
                dispatched = true;
                T result = await(running, request, deadline, options);
                if (cancelled(options)) throw stopped(true, status.get() == 0 ? null : status.get(), recovered.get(), !read);
                if (System.nanoTime() >= deadline) throw stopped(false, status.get() == 0 ? null : status.get(), recovered.get(), !read);
                return result;
            } catch (Exception error) {
                knownId = recovered.get(); Integer receivedStatus = status.get() == 0 ? null : status.get();
                if (cancelled(options)) throw stopped(true, receivedStatus, knownId, dispatched && !read);
                if (System.nanoTime() >= deadline) throw stopped(false, receivedStatus, knownId, dispatched && !read);
                failure = error instanceof KompressrException e ? e : new KompressrException("Unable to reach Kompressr. Check the endpoint and connection.", "network", "NETWORK_ERROR", receivedStatus, null, knownId, dispatched && !read);
                if (failure.kind().equals("invalid_response")) failure = failure.context(receivedStatus, knownId, dispatched && !read);
            } finally {
                watchdog.cancel(false);
                try { registration.close(); } catch (Exception ignored) { /* Local cancellation registration has no I/O. */ }
            }
            boolean transientFailure = failure.kind().equals("network") || failure.kind().equals("api") && java.util.Set.of(429, 502, 503, 504).contains(failure.status());
            if (!read || !transientFailure || attempt >= retries) throw failure;
            long backoff = Math.min(30_000, 250L * (1L << attempt) + ThreadLocalRandom.current().nextLong(100));
            try { pause(Math.max(backoff, failure.retryAfterMs() == null ? 0 : failure.retryAfterMs()), deadline, options); }
            catch (KompressrException e) { throw e.context(failure.status(), knownId, false); }
        }
    }
    private static void checkActiveDeadline() throws java.io.InterruptedIOException {
        Deadline active = ACTIVE.get();
        if (active != null && (System.nanoTime() >= active.nanos() || cancelled(active.options()))) throw new java.io.InterruptedIOException("Request deadline or cancellation reached.");
    }
    private static <T> T await(Future<T> running, HttpUriRequestBase request, long deadline, Options.Request options) throws Exception {
        try {
            while (true) {
                if (cancelled(options)) throw stopped(true, null, null, false);
                long remaining = deadline - System.nanoTime();
                if (remaining <= 0) throw stopped(false, null, null, false);
                try { return running.get(Math.min(remaining, 10_000_000), TimeUnit.NANOSECONDS); }
                catch (TimeoutException pending) { /* Recheck the total deadline and cancellation. */ }
                catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); throw stopped(true, null, null, false); }
                catch (ExecutionException failure) {
                    if (failure.getCause() instanceof Exception cause) throw cause;
                    throw new IOException("HTTP execution failed.");
                }
            }
        } finally {
            if (!running.isDone()) { request.cancel(); running.cancel(true); }
        }
    }
    private static Long retryAfter(String header, JsonNode body) {
        if (header != null) {
            try { double seconds = Double.parseDouble(header); if (Double.isFinite(seconds) && seconds >= 0) return (long)Math.min(Long.MAX_VALUE, Math.ceil(seconds * 1000)); }
            catch (NumberFormatException ignored) { }
            try { return Math.max(0, ZonedDateTime.parse(header, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli() - System.currentTimeMillis()); }
            catch (java.time.DateTimeException ignored) { }
        }
        if (body != null && body.path("retry_after").isNumber()) { double n = body.get("retry_after").doubleValue(); if (Double.isFinite(n) && n >= 0) return (long)Math.min(Long.MAX_VALUE, Math.ceil(n * 1000)); }
        return null;
    }
    @Override public void close() { closed = true; http.close(CloseMode.IMMEDIATE); }
}
