package com.kompressr;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import java.io.*;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.Consumer;
import java.util.stream.Stream;
import static org.junit.jupiter.api.Assertions.*;

class ClientTest {
    static final String PROJECT = "660e8400-e29b-41d4-a716-446655440001", USER = "660e8400-e29b-41d4-a716-446655440002", KEY = "660e8400-e29b-41d4-a716-446655440003";
    static final String SECRET = "fixture-credential";
    HttpServer server;
    ExecutorService executor;
    String origin;
    AtomicReference<Throwable> serverFailure;
    interface Handler { void handle(HttpExchange exchange) throws Exception; }
    void serve(Handler handler) throws IOException {
        serverFailure = new AtomicReference<>(); executor = Executors.newCachedThreadPool();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(executor);
        server.createContext("/", exchange -> { try { handler.handle(exchange); } catch (Throwable failure) { serverFailure.compareAndSet(null, failure); exchange.close(); } });
        server.start(); origin = "http://127.0.0.1:" + server.getAddress().getPort();
    }
    @AfterEach void stop() throws Exception { if (server != null) server.stop(0); if (executor != null) { executor.shutdownNow(); executor.awaitTermination(2, TimeUnit.SECONDS); } if (serverFailure != null && serverFailure.get() instanceof AssertionError e) throw e; }
    KompressrClient client() { return KompressrClient.builder(SECRET).apiBaseUrl(origin).projectId(PROJECT).maxReadRetries(0).build(); }
    static JsonNode fixture(String name) throws Exception { try (var stream = ClientTest.class.getResourceAsStream("/file-lifecycle.json")) { return Validation.JSON.readTree(stream).get(name).deepCopy(); } }
    static ObjectNode obj(String text) throws Exception { return (ObjectNode)Validation.JSON.readTree(text); }
    static ObjectNode accepted() throws Exception { return (ObjectNode)fixture("accepted"); }
    static ObjectNode processed() throws Exception { return (ObjectNode)fixture("processed"); }
    static ObjectNode state() throws Exception { return (ObjectNode)fixture("deletionAccepted"); }
    static ObjectNode user() throws Exception { return obj("{\"id\":\"" + USER + "\",\"project_id\":\"" + PROJECT + "\",\"customer_user_id\":\"customer-one\",\"status\":\"active\"}"); }
    static ObjectNode key() throws Exception { return obj("{\"id\":\"" + KEY + "\",\"key_id\":\"key-record\",\"project_id\":\"" + PROJECT + "\",\"project_user_id\":\"" + USER + "\",\"name\":\"Chat\",\"scopes\":[\"upload\",\"status\",\"list\",\"private_url\"],\"allowed_visibility\":\"private\",\"allowed_asset_types\":[],\"expires_at\":null}"); }
    static Map<String, Object> envelope(Object data) { return Map.of("success", true, "data", data); }
    static void send(HttpExchange x, int status, Object body) throws Exception { sendRaw(x, status, Validation.JSON.writeValueAsBytes(body)); }
    static void sendRaw(HttpExchange x, int status, byte[] bytes) throws Exception { x.getResponseHeaders().set("Content-Type", "application/json"); x.sendResponseHeaders(status, bytes.length); try (var stream = x.getResponseBody()) { stream.write(bytes); } }
    static void drain(HttpExchange x) throws IOException { x.getRequestBody().transferTo(OutputStream.nullOutputStream()); }
    @Test void fixtureCopyMatchesSharedContract() throws Exception {
        var shared = Path.of("../contracts/fixtures/file-lifecycle.json");
        if (Files.exists(shared)) try (var in = ClientTest.class.getResourceAsStream("/file-lifecycle.json")) { assertArrayEquals(Files.readAllBytes(shared), in.readAllBytes()); }
    }
    @Test void publicFileLifecycleUsesRealMultipartAndCustomOrigins() throws Exception {
        var requests = new ArrayList<String>();
        serve(x -> {
            assertEquals("Bearer " + SECRET, x.getRequestHeaders().getFirst("Authorization")); requests.add(x.getRequestMethod() + " " + x.getRequestURI().getPath());
            if (x.getRequestURI().getPath().equals("/api/upload")) {
                String body = new String(x.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                assertTrue(body.indexOf("name=\"visibility\"") < body.indexOf("name=\"file\""));
                assertTrue(body.indexOf("name=\"data\"") < body.indexOf("name=\"file\""));
                assertTrue(body.contains("synthetic-file-body")); send(x, 202, envelope(accepted()));
            } else send(x, 200, envelope(processed()));
        });
        Path path = Files.createTempFile("fixture", ".png"); Files.writeString(path, "synthetic-file-body");
        try (var client = client()) {
            assertEquals(origin, client.uploadBaseUrl());
            var result = client.uploadFile(path, new Options.Upload("public", "720p", Map.of("customer", "one"), 600));
            assertEquals(42, result.id()); assertEquals("processing", result.status());
            assertEquals("https://cdn.example/ready.webp", client.waitUntilReady(result.id()).cdnUrl());
            assertEquals(List.of("POST /api/upload", "GET /api/upload/42/status"), requests);
        } finally { Files.delete(path); }
    }
    @Test void bytesSendSelectedContent() throws Exception {
        AtomicInteger calls = new AtomicInteger();
        serve(x -> { String body = new String(x.getRequestBody().readAllBytes(), StandardCharsets.UTF_8); assertTrue(body.contains("payload")); calls.incrementAndGet(); send(x, 200, envelope(accepted())); });
        try (var client = client()) {
            client.uploadBytes("payload".getBytes(), "folder/picture.png");
            assertEquals(1, calls.get());
        }
    }
    @Test void privateReadinessAndFreshSigning() throws Exception {
        AtomicInteger polls = new AtomicInteger();
        serve(x -> {
            if (x.getRequestMethod().equals("POST")) {
                var body = Validation.JSON.readTree(x.getRequestBody()); assertEquals(900, body.get("expires_in").intValue()); assertEquals("avif", body.get("variant").textValue());
                send(x, 200, envelope(Map.of("asset_id", 42, "variant", "avif", "private_url", "https://cdn.example/private?signature=fixture", "expires_at", "2030-01-01T00:00:00Z", "expires_in", 900)));
            } else { var asset = processed(); asset.remove(List.of("cdn_url", "original_name")); asset.put("visibility", "private").put("can_generate_private_url", true); if (polls.getAndIncrement() == 0) asset.put("status", "processing"); send(x, 200, envelope(asset)); }
        });
        try (var client = client()) {
            assertNull(client.waitUntilReady(42, new Options.Wait(Duration.ofSeconds(2), Duration.ofMillis(1), null)).originalName());
            var signed = client.generatePrivateUrl(42, new Options.Signing(900, "avif"), null); assertEquals(42, signed.assetId()); assertFalse(signed.toString().contains("signature")); assertEquals(2, polls.get());
        }
    }
    @Test void listsAreFilteredAndLazyWithIndividualBulkOutcomes() throws Exception {
        AtomicInteger pages = new AtomicInteger();
        serve(x -> {
            String path = x.getRequestURI().getPath();
            if (path.equals("/api/uploads")) {
                int page = pages.incrementAndGet(); String q = x.getRequestURI().getQuery(); assertTrue(q.contains("project_id=" + PROJECT)); assertTrue(q.contains("status=3")); assertTrue(q.contains("data.chat=one")); assertTrue(q.contains("deletion_status=active"));
                send(x, 200, Map.of("success", true, "data", List.of(processed().put("id", 41 + page)), "page", page, "limit", 1, "total", 2));
            } else if (path.equals("/api/assets/bulk-delete")) { assertEquals("[42,43,42]", Validation.JSON.readTree(x.getRequestBody()).get("asset_ids").toString()); send(x, 200, fixture("bulkDeletion")); }
            else if (path.equals("/api/assets")) send(x, 200, Map.of("data", List.of(state()), "page", 1, "limit", 20, "total", 1));
            else { drain(x); send(x, 202, state()); }
        });
        try (var client = client()) {
            var iterator = client.iterateUploads(new Options.UploadFilters(null, 1, 1, "public", "processed", "example", Map.of("chat", "one"), "active"), null).iterator();
            assertEquals(0, pages.get()); assertEquals(42, iterator.next().id()); assertEquals(1, pages.get()); assertEquals(43, iterator.next().id()); assertFalse(iterator.hasNext());
            assertEquals("deleting", client.deleteAsset(42).deletionStatus()); assertEquals(42, client.getAsset(42).id()); assertEquals(1, client.listAssets().total());
            var bulk = client.bulkDeleteAssets(List.of(42L, 43L, 42L)); assertEquals(2, bulk.results().size()); assertFalse(bulk.results().get(1).accepted()); assertEquals(1, bulk.counts().failed());
        }
    }
    @Test void allNinePlatformMethodsUseAuthorityAndDefaultNonDestructiveScopes() throws Exception {
        AtomicInteger count = new AtomicInteger();
        serve(x -> {
            count.incrementAndGet(); String method = x.getRequestMethod(), path = x.getRequestURI().getPath();
            if (method.equals("GET")) {
                if (path.endsWith("upload-keys")) send(x, 200, Map.of("success", true, "upload_keys", List.of(key()), "page", 1, "limit", 20, "total", 1));
                else send(x, 200, Map.of("success", true, "project_users", List.of(user()), "page", 1, "limit", 20, "total", 1, "project_active_count", 1, "org_active_count", 1, "usage_period", Map.of("start", "2030-01-01", "end", "2030-02-01")));
            } else if (path.endsWith("upload-keys") || path.endsWith("rotate")) {
                byte[] bytes = x.getRequestBody().readAllBytes();
                if (path.endsWith("upload-keys")) { var body = Validation.JSON.readTree(bytes); assertFalse(body.has("scopes")); assertEquals("Chat", body.get("name").textValue()); }
                send(x, 200, Map.of("success", true, "id", KEY, "key_id", "key-record", "api_key", "one-time-fixture-secret", "upload_key", key()));
            } else if (path.endsWith("revoke")) { drain(x); send(x, 200, Map.of("success", true)); }
            else {
                var bytes = x.getRequestBody().readAllBytes();
                if (path.equals("/api/platform/project-users")) assertEquals("customer-one", Validation.JSON.readTree(bytes).get("customer_user_id").textValue());
                if (method.equals("PATCH")) assertEquals("Display", Validation.JSON.readTree(bytes).get("display_name").textValue());
                var user = user(); if (path.endsWith("suspend")) user.put("status", "suspended");
                send(x, 200, Map.of("success", true, "created", true, "project_user", user));
            }
        });
        try (var client = client()) {
            var p = client.platform(); assertEquals(1, p.listUsers().orgActiveCount());
            assertTrue(p.createUser(new Options.CreateUser("customer-one", null, Map.of("tier", "example"))).created());
            assertEquals(USER, p.updateUser(USER, new Options.UpdateUser("Display", Map.of())).id());
            assertEquals("suspended", p.suspendUser(USER).status()); assertEquals("active", p.reactivateUser(USER).status());
            assertEquals(1, p.listUploadKeys(USER).total());
            var issued = p.createUploadKey(USER, new Options.CreateKey("Chat")); assertEquals("one-time-fixture-secret", issued.apiKey()); assertFalse(issued.toString().contains(issued.apiKey()));
            assertEquals(KEY, p.rotateUploadKey(USER, KEY).id()); p.revokeUploadKey(USER, KEY); assertEquals(9, count.get());
        }
    }
    record Mutation(String name, Long id, Consumer<KompressrClient> run) { @Override public String toString() { return name; } }
    static Stream<Mutation> mutations() { return Stream.of(
        new Mutation("upload", null, c -> c.uploadBytes(new byte[]{1}, "fixture.png")),
        new Mutation("sign", 42L, c -> c.generatePrivateUrl(42)), new Mutation("delete", 42L, c -> c.deleteAsset(42)), new Mutation("bulk", null, c -> c.bulkDeleteAssets(List.of(42L, 43L))),
        new Mutation("create", null, c -> c.platform().createUser(new Options.CreateUser("customer", null, null))), new Mutation("update", null, c -> c.platform().updateUser(USER, new Options.UpdateUser(null, null))),
        new Mutation("suspend", null, c -> c.platform().suspendUser(USER)), new Mutation("reactivate", null, c -> c.platform().reactivateUser(USER)),
        new Mutation("issue", null, c -> c.platform().createUploadKey(USER, new Options.CreateKey("Fixture"))), new Mutation("rotate", null, c -> c.platform().rotateUploadKey(USER, KEY)), new Mutation("revoke", null, c -> c.platform().revokeUploadKey(USER, KEY)));
    }
    @ParameterizedTest @MethodSource("mutations") void malformedMutationsRemainAmbiguousAndAreNeverReplayed(Mutation mutation) throws Exception {
        AtomicInteger calls = new AtomicInteger();
        serve(x -> { drain(x); calls.incrementAndGet(); sendRaw(x, 200, "{broken".getBytes()); });
        try (var client = client()) { var e = assertThrows(KompressrException.class, () -> mutation.run().accept(client)); assertEquals("INVALID_RESPONSE", e.code()); assertEquals(200, e.status()); assertTrue(e.mayHaveSucceeded()); assertEquals(mutation.id(), e.assetId()); assertEquals(1, calls.get()); }
    }
    @ParameterizedTest @MethodSource("mutations") void incompleteMutationShapesStayInsideAmbiguityBoundary(Mutation mutation) throws Exception {
        serve(x -> { drain(x); send(x, 200, mutation.name().equals("revoke") ? Map.of() : envelope(Map.of("asset_id", 42))); });
        try (var client = client()) { var e = assertThrows(KompressrException.class, () -> mutation.run().accept(client)); assertEquals("INVALID_RESPONSE", e.code()); assertTrue(e.mayHaveSucceeded()); assertEquals(mutation.name().equals("upload") ? Long.valueOf(42) : mutation.id(), e.assetId()); }
    }
    @ParameterizedTest @ValueSource(strings = {"0", "-1", "1.5", "9007199254740992", "\"42\""}) void unsafeUploadIdsAreNeverRecovered(String id) throws Exception {
        serve(x -> { drain(x); sendRaw(x, 200, ("{\"success\":true,\"data\":{\"asset_id\":" + id + "}}").getBytes()); });
        try (var client = client()) { var e = assertThrows(KompressrException.class, () -> client.uploadBytes(new byte[]{1}, "f.png")); assertNull(e.assetId()); assertTrue(e.mayHaveSucceeded()); }
    }
    @Test void mismatchedIdsDoNotReplaceKnownMutationContext() throws Exception {
        serve(x -> { drain(x); send(x, 200, state().put("id", 43)); });
        try (var client = client()) { var e = assertThrows(KompressrException.class, () -> client.deleteAsset(42)); assertEquals(42, e.assetId()); assertTrue(e.mayHaveSucceeded()); }
    }
    @ParameterizedTest @ValueSource(ints = {429, 502, 503, 504}) void eligibleReadsRetryAndHonorRetryAfter(int status) throws Exception {
        AtomicInteger calls = new AtomicInteger(); AtomicLong first = new AtomicLong();
        serve(x -> { if (calls.incrementAndGet() == 1) { first.set(System.nanoTime()); x.getResponseHeaders().set("Retry-After", "0.4"); send(x, status, Map.of("error", "retry")); } else send(x, 200, envelope(processed())); });
        try (var client = KompressrClient.builder(SECRET).apiBaseUrl(origin).build()) { assertEquals(42, client.getUploadStatus(42).id()); assertEquals(2, calls.get()); assertTrue(System.nanoTime() - first.get() >= 390_000_000); }
    }
    @Test void longRetryAfterCannotEscapeDeadline() throws Exception {
        AtomicInteger calls = new AtomicInteger(); serve(x -> { calls.incrementAndGet(); x.getResponseHeaders().set("Retry-After", "60"); send(x, 429, Map.of("error", "retry")); });
        try (var client = KompressrClient.builder(SECRET).apiBaseUrl(origin).requestTimeout(Duration.ofMillis(150)).build()) {
            long start = System.nanoTime(); var e = assertThrows(KompressrException.class, () -> client.getUploadStatus(42)); assertEquals("REQUEST_TIMEOUT", e.code()); assertEquals(429, e.status()); assertEquals(1, calls.get()); assertTrue(System.nanoTime() - start < 1_000_000_000);
        }
    }
    @Test void scopesAndRedactionPreserveDenialWithoutCredentialFallback() throws Exception {
        AtomicInteger calls = new AtomicInteger(); serve(x -> { calls.incrementAndGet(); assertEquals("Bearer " + SECRET, x.getRequestHeaders().getFirst("Authorization")); send(x, 403, Map.of("error", "denied " + SECRET + " Bearer alternate https://cdn.example/private?signature=hidden api_key=extra", "code", "SCOPE_DENIED")); });
        try (var client = client()) { var e = assertThrows(KompressrException.class, () -> client.getUploadStatus(42)); assertEquals("SCOPE_DENIED", e.code()); assertEquals(403, e.status()); assertFalse(e.mayHaveSucceeded()); assertEquals(1, calls.get()); for (String secret : List.of(SECRET, "alternate", "https://", "hidden", "extra")) assertFalse(e.toString().contains(secret)); }
    }
    @Test void redirectsNeverForwardCredentialOrReplayMutation() throws Exception {
        AtomicInteger calls = new AtomicInteger(); serve(x -> { calls.incrementAndGet(); drain(x); x.getResponseHeaders().set("Location", origin + "/redirect-target"); send(x, 307, Map.of("error", "redirect")); });
        try (var client = client()) { var e = assertThrows(KompressrException.class, () -> client.deleteAsset(42)); assertEquals(307, e.status()); assertTrue(e.mayHaveSucceeded()); assertEquals(1, calls.get()); }
    }
    @Test void networkDisconnectNeverRetriesDelete() throws Exception {
        AtomicInteger calls = new AtomicInteger(); serve(x -> { drain(x); calls.incrementAndGet(); x.close(); });
        try (var client = KompressrClient.builder(SECRET).apiBaseUrl(origin).maxReadRetries(5).build()) { var e = assertThrows(KompressrException.class, () -> client.deleteAsset(42)); assertEquals("NETWORK_ERROR", e.code()); assertTrue(e.mayHaveSucceeded()); assertEquals(1, calls.get()); }
    }
    @ParameterizedTest @ValueSource(booleans = {false, true}) void bodyDeadlineCoversReadsAndWrites(boolean write) throws Exception {
        serve(x -> { drain(x); x.sendResponseHeaders(200, 0); x.getResponseBody().write('{'); x.getResponseBody().flush(); Thread.sleep(2000); x.close(); });
        try (var client = client()) {
            long start = System.nanoTime(); var options = Options.Request.timeout(Duration.ofMillis(150));
            var e = assertThrows(KompressrException.class, () -> { if (write) client.deleteAsset(42, options); else client.getUploadStatus(42, options); });
            assertEquals("REQUEST_TIMEOUT", e.code()); assertEquals(write, e.mayHaveSucceeded()); assertEquals(200, e.status()); assertTrue(System.nanoTime() - start < 1_000_000_000);
        }
    }
    @Test void preCancelledWriteIsNeverDispatched() throws Exception {
        AtomicInteger count = new AtomicInteger(); serve(x -> { count.incrementAndGet(); drain(x); send(x, 200, envelope(accepted())); });
        var token = new CancellationToken(); token.cancel();
        try (var client = client()) { var e = assertThrows(KompressrException.class, () -> client.uploadBytes(new byte[]{1}, "file.png", null, new Options.Request(null, token))); assertEquals("REQUEST_CANCELLED", e.code()); assertFalse(e.mayHaveSucceeded()); assertEquals(0, count.get()); }
    }
    @Test void cancellationStopsAnInFlightBodyAndKeepsWriteId() throws Exception {
        var started = new CountDownLatch(1);
        serve(x -> { drain(x); x.sendResponseHeaders(200, 0); x.getResponseBody().write('{'); x.getResponseBody().flush(); started.countDown(); Thread.sleep(2000); x.close(); });
        var token = new CancellationToken();
        try (var client = client()) {
            var pool = Executors.newSingleThreadExecutor();
            try {
                var future = pool.submit(() -> assertThrows(KompressrException.class, () -> client.deleteAsset(42, new Options.Request(null, token))));
                assertTrue(started.await(1, TimeUnit.SECONDS)); token.cancel(); var e = future.get(1, TimeUnit.SECONDS); assertEquals("REQUEST_CANCELLED", e.code()); assertEquals(42, e.assetId()); assertTrue(e.mayHaveSucceeded());
            } finally { pool.shutdownNow(); }
        }
    }
    @Test void waitsAreBoundedResumableAndNeverReupload() throws Exception {
        AtomicInteger calls = new AtomicInteger(); serve(x -> { assertEquals("GET", x.getRequestMethod()); calls.incrementAndGet(); send(x, 200, envelope(processed().put("status", "processing"))); });
        try (var client = client()) {
            var e = assertThrows(KompressrException.class, () -> client.waitUntilReady(42, new Options.Wait(Duration.ofMillis(100), Duration.ofMillis(20), null)));
            assertEquals("WAIT_TIMEOUT", e.code()); assertEquals(42, e.assetId()); assertFalse(e.mayHaveSucceeded()); assertTrue(calls.get() > 0);
            var token = new CancellationToken(); token.cancel(); assertEquals("WAIT_CANCELLED", assertThrows(KompressrException.class, () -> client.waitUntilReady(42, new Options.Wait(null, null, token))).code());
        }
    }
    @ParameterizedTest @ValueSource(strings = {"failed", "unprocessable", "unknown", "deleted", "private", "missing_url"}) void invalidOrTerminalReadinessNeverProducesReadyResult(String type) throws Exception {
        serve(x -> { var data = processed(); switch (type) { case "deleted" -> { data.put("deletion_status", "deleted"); data.remove("cdn_url"); } case "private" -> { data.put("visibility", "private"); } case "missing_url" -> data.remove("cdn_url"); default -> data.put("status", type); } send(x, 200, envelope(data)); });
        try (var client = client()) { var e = assertThrows(KompressrException.class, () -> client.waitUntilReady(42)); assertEquals(42, e.assetId()); assertEquals(type.equals("deleted") ? "ASSET_DELETED" : Set.of("private", "missing_url").contains(type) ? "INVALID_RESPONSE" : "PROCESSING_FAILED", e.code()); }
    }
    @Test void validationRejectsBeforeAnyHttpRequest() throws Exception {
        AtomicInteger calls = new AtomicInteger(); serve(x -> { calls.incrementAndGet(); x.close(); });
        try (var client = client()) {
            List<Runnable> invalid = List.of(() -> client.getAsset(0), () -> client.getAsset(Validation.MAX_SAFE + 1), () -> client.bulkDeleteAssets(List.of()),
                () -> client.generatePrivateUrl(42, new Options.Signing(59, "webp"), null),
                () -> client.uploadBytes(new byte[]{1}, "bad\n.png"),
                () -> client.uploadBytes(new byte[]{1}, "image.png", new Options.Upload("other", null, null, null), null),
                () -> client.uploadBytes(new byte[]{1}, "image.png", new Options.Upload(null, null, Map.of("n", Double.NaN), null), null),
                () -> client.platform().createUploadKey(USER, new Options.CreateKey("fixture", List.of("administrator"), null, null, null)),
                () -> client.getAsset(42, Options.Request.timeout(Duration.ofNanos(1))),
                () -> client.platform().createUser(new Options.CreateUser("", null, null)));
            for (var action : invalid) { var e = assertThrows(KompressrException.class, action::run); assertEquals("INVALID_ARGUMENT", e.code()); assertFalse(e.mayHaveSucceeded()); }
            assertEquals(0, calls.get());
        }
    }
    @Test void defaultEndpointsAndOriginValidation() {
        try (var client = KompressrClient.builder("fixture").build()) { assertEquals("https://kompressr.com", client.apiBaseUrl()); assertEquals("https://uploads.kompressr.com", client.uploadBaseUrl()); }
        for (var origin : List.of("https://user:pass@example.com", "https://example.com/path", "file:///example", "https://example.com?key=x", "https://example.com#fragment")) assertThrows(KompressrException.class, () -> KompressrClient.builder("fixture").apiBaseUrl(origin).build());
    }
    @Test void responsesAreBoundedAndNeverExposeGatewayHtml() throws Exception {
        serve(x -> { drain(x); sendRaw(x, 502, ("<html>" + SECRET + "</html>").getBytes()); });
        try (var client = client()) { var e = assertThrows(KompressrException.class, () -> client.deleteAsset(42)); assertEquals(502, e.status()); assertTrue(e.mayHaveSucceeded()); assertFalse(e.toString().contains("html")); assertFalse(e.toString().contains(SECRET)); }
    }
    @Test void oversizedSuccessfulBodyIsRejected() throws Exception {
        serve(x -> { drain(x); sendRaw(x, 200, new byte[2 * 1024 * 1024 + 1]); });
        try (var client = client()) { var e = assertThrows(KompressrException.class, () -> client.deleteAsset(42)); assertEquals("INVALID_RESPONSE", e.code()); assertTrue(e.mayHaveSucceeded()); }
    }
    @Test void separateUploadOriginIsUsedWithoutManagementFallback() throws Exception {
        serve(x -> { assertEquals("/api/upload", x.getRequestURI().getPath()); drain(x); send(x, 200, envelope(accepted())); });
        try (var client = KompressrClient.builder(SECRET).apiBaseUrl("http://127.0.0.1:1").uploadBaseUrl(origin).build()) {
            assertEquals(42, client.uploadBytes(new byte[]{1}, "fixture.png").id());
        }
    }
    @Test void interruptStopsHttpBodyAndPreservesInterruptFlag() throws Exception {
        var started = new CountDownLatch(1); var finished = new CountDownLatch(1);
        serve(x -> { x.sendResponseHeaders(200, 0); x.getResponseBody().write('{'); x.getResponseBody().flush(); started.countDown(); Thread.sleep(2000); x.close(); });
        AtomicReference<Throwable> failure = new AtomicReference<>();
        try (var client = client()) {
            var thread = new Thread(() -> {
                try { var e = assertThrows(KompressrException.class, () -> client.getUploadStatus(42)); assertEquals("REQUEST_CANCELLED", e.code()); assertTrue(Thread.currentThread().isInterrupted()); }
                catch (Throwable e) { failure.set(e); } finally { finished.countDown(); }
            });
            thread.start(); assertTrue(started.await(1, TimeUnit.SECONDS)); thread.interrupt();
            assertTrue(finished.await(1, TimeUnit.SECONDS)); assertNull(failure.get());
        }
    }
    @Test void invalidPaginationStopsBeforeFetchingAnotherPage() throws Exception {
        AtomicInteger calls = new AtomicInteger(); serve(x -> { calls.incrementAndGet(); send(x, 200, Map.of("success", true, "data", List.of(processed()), "page", 2, "limit", 20, "total", 50)); });
        try (var client = client()) { assertEquals("INVALID_RESPONSE", assertThrows(KompressrException.class, () -> client.iterateUploads().iterator().hasNext()).code()); assertEquals(1, calls.get()); }
    }
    @Test void retryWaitFailureDuringReadinessRetainsAssetId() throws Exception {
        serve(x -> { x.getResponseHeaders().set("Retry-After", "60"); send(x, 429, Map.of("error", "wait")); });
        try (var client = KompressrClient.builder(SECRET).apiBaseUrl(origin).build()) {
            var e = assertThrows(KompressrException.class, () -> client.waitUntilReady(42, new Options.Wait(Duration.ofMillis(150), null, null)));
            assertEquals("WAIT_TIMEOUT", e.code()); assertEquals(42, e.assetId());
        }
    }
    @Test void validExplicitKeyRestrictionsReachWireUnchanged() throws Exception {
        serve(x -> { var body = Validation.JSON.readTree(x.getRequestBody()); assertEquals("[\"upload\",\"status\",\"private_url\"]", body.get("scopes").toString()); assertEquals("private", body.get("allowed_visibility").textValue()); assertEquals("[1]", body.get("allowed_asset_types").toString()); assertEquals("2099-01-01T00:00:00Z", body.get("expires_at").textValue()); send(x, 200, Map.of("success", true, "id", KEY, "key_id", "record", "api_key", "fixture-one-time")); });
        try (var client = client()) { var issued = client.platform().createUploadKey(USER, new Options.CreateKey("Scoped", List.of("upload", "status", "private_url"), "private", List.of(1), "2099-01-01T00:00:00Z")); assertNull(issued.uploadKey()); }
    }

    @ParameterizedTest @ValueSource(booleans = {false, true}) void blockedDnsCannotEscapeCallerDeadlineOrSendAfterItExpires(boolean closeWhileBlocked) throws Exception {
        AtomicInteger requests = new AtomicInteger(); var resolving = new CountDownLatch(1); var release = new CountDownLatch(1); var resolved = new CountDownLatch(1);
        serve(x -> { requests.incrementAndGet(); drain(x); send(x, 200, state()); });
        var builder = KompressrClient.builder(SECRET).apiBaseUrl("http://fixture.invalid:" + server.getAddress().getPort()).requestTimeout(Duration.ofMillis(150));
        builder.dnsResolver = new org.apache.hc.client5.http.DnsResolver() {
            @Override public java.net.InetAddress[] resolve(String host) throws java.net.UnknownHostException {
                resolving.countDown(); boolean interrupted = false;
                while (release.getCount() > 0) { try { release.await(); } catch (InterruptedException e) { interrupted = true; } }
                if (interrupted) Thread.currentThread().interrupt();
                resolved.countDown(); return new java.net.InetAddress[]{java.net.InetAddress.getLoopbackAddress()};
            }
            @Override public String resolveCanonicalHostname(String host) { return host; }
        };
        var client = builder.build();
        try {
            long started = System.nanoTime();
            var e = assertThrows(KompressrException.class, () -> client.deleteAsset(42));
            assertEquals("REQUEST_TIMEOUT", e.code()); assertTrue(e.mayHaveSucceeded()); assertTrue(System.nanoTime() - started < 1_000_000_000); assertEquals(0, resolving.getCount());
            if (closeWhileBlocked) { long closeStarted = System.nanoTime(); client.close(); assertTrue(System.nanoTime() - closeStarted < 500_000_000); }
            // Also exercise late DNS completion while the client is still open.
            release.countDown(); assertTrue(resolved.await(1, TimeUnit.SECONDS)); Thread.sleep(100); assertEquals(0, requests.get());
            long closeStarted = System.nanoTime(); client.close(); assertTrue(System.nanoTime() - closeStarted < 500_000_000);
        } finally { release.countDown(); client.close(); }
    }

    @Test void emptyKeyScopesAreRejectedBeforeHttpWhileDefaultsAndExplicitScopesArePreserved() throws Exception {
        var bodies = new ArrayList<JsonNode>();
        serve(x -> {
            bodies.add(Validation.JSON.readTree(x.getRequestBody()));
            send(x, 200, Map.of("success", true, "id", KEY, "key_id", "record", "api_key", "fixture-one-time"));
        });
        try (var client = client()) {
            var error = assertThrows(KompressrException.class, () -> client.platform().createUploadKey(USER,
                new Options.CreateKey("Scoped", List.of(), null, null, null)));
            assertEquals("INVALID_ARGUMENT", error.code()); assertEquals("validation", error.kind());
            assertFalse(error.mayHaveSucceeded()); assertEquals(0, bodies.size());
            client.platform().createUploadKey(USER, new Options.CreateKey("Defaults"));
            client.platform().createUploadKey(USER, new Options.CreateKey("Status only", List.of("status"), null, null, null));
            assertEquals(2, bodies.size()); assertFalse(bodies.get(0).has("scopes"));
            assertEquals("[\"status\"]", bodies.get(1).get("scopes").toString());
        }
    }

}
