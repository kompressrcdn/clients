using Kompressr.Sdk;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

internal static class Program
{
    private const string Project = "660e8400-e29b-41d4-a716-446655440001";
    private const string UserId = "660e8400-e29b-41d4-a716-446655440002";
    private const string KeyId = "660e8400-e29b-41d4-a716-446655440003";
    private const string Credential = "fixture-credential";
    private static readonly JsonObject Fixture = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "fixtures", "file-lifecycle.json")))!.AsObject();
    private static int passed;
    private static JsonNode Record(string name) => Fixture[name]!.DeepClone();
    private static JsonObject Status(string state = "processed", string visibility = "public")
    {
        var result = Record("processed").AsObject();
        result.Remove("asset_id"); result["status"] = state; result["visibility"] = visibility;
        if (visibility == "private") { result.Remove("cdn_url"); result["can_generate_private_url"] = state == "processed"; }
        return result;
    }
    private static JsonObject User(string status = "active") => new() { ["id"] = UserId, ["project_id"] = Project, ["customer_user_id"] = "example-user", ["status"] = status };
    private static JsonObject Key() => new() { ["id"] = KeyId, ["key_id"] = "fixture-key-id", ["project_id"] = Project, ["project_user_id"] = UserId, ["name"] = "Chat uploads", ["scopes"] = new JsonArray("upload", "status", "list", "private_url"), ["allowed_visibility"] = "private", ["allowed_asset_types"] = new JsonArray(1, 2), ["expires_at"] = null };
    private static Reply Accepted() => Reply.Json(new { success = true, data = Record("accepted") });
    private static Reply Ready(string state = "processed", string visibility = "public") => Reply.Json(new { success = true, data = Status(state, visibility) });
    private static KompressrClient Client(FixtureServer server, int retries = 0, int timeout = 3000, string? uploadOrigin = null) => new(new()
    { ApiKey = Credential, ProjectId = Project, ApiBaseUrl = server.Url, UploadBaseUrl = uploadOrigin, MaxReadRetries = retries, RequestTimeout = TimeSpan.FromMilliseconds(timeout), UploadTimeout = TimeSpan.FromMilliseconds(timeout) });
    private static void Check(bool condition, string message = "Assertion failed.") { if (!condition) throw new Exception(message); }
    private static async Task<KompressrException> Error(Func<Task> call, string code, bool? ambiguous = null, long? asset = null)
    {
        try { await call(); } catch (KompressrException error)
        {
            Check(error.Code == code, $"Expected {code}, got {error.Code}.");
            if (ambiguous is not null) Check(error.MayHaveSucceeded == ambiguous, "Wrong write ambiguity.");
            if (asset is not null) Check(error.AssetId == asset, "Missing or wrong recovery asset ID.");
            return error;
        }
        throw new Exception("Expected a KompressrException.");
    }
    private static async Task Run(string name, Func<Task> body)
    {
        await body(); passed++; Console.WriteLine("PASS " + name);
    }
    public static async Task Main()
    {
        Console.WriteLine("Runtime " + System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription);
        await Run("public lifecycle and accepted versus ready", async () =>
        {
            int polls = 0;
            await using var server = new FixtureServer(request => request.Path switch
            {
                "/api/upload" => Accepted(),
                "/api/upload/42/status" => Ready(Interlocked.Increment(ref polls) == 1 ? "processing" : "processed"),
                "/api/assets/42" => Reply.Json(Record("deletionAccepted"), 202),
                _ => throw new Exception("Unexpected route.")
            });
            var client = Client(server);
            var accepted = await client.UploadBytesAsync(new byte[] { 1, 2, 3 }, "image.png", new() { Visibility = "public", Quality = "720p", PrivateUrlExpiresIn = 3600, Data = new Dictionary<string, object?> { [" conversation "] = "chat-1", ["flag"] = true } });
            Check(accepted.Id == 42 && accepted.Status == "processing");
            var ready = await client.WaitUntilReadyAsync(accepted.Id, new() { PollInterval = TimeSpan.FromMilliseconds(5) });
            Check(ready.CdnUrl == "https://cdn.example/ready.webp" && polls == 2);
            var deleted = await client.DeleteAssetAsync(42);
            Check(deleted.DeletionStatus == "deleting");
            foreach (var request in server.Requests) Check(request.Headers["Authorization"] == "Bearer " + Credential);
            var upload = server.Requests.First();
            string body = Encoding.UTF8.GetString(upload.Body);
            Check(body.IndexOf("visibility", StringComparison.Ordinal) < body.IndexOf("name=file", StringComparison.Ordinal));
            Check(body.IndexOf("kmp-quality", StringComparison.Ordinal) < body.IndexOf("name=file", StringComparison.Ordinal));
            Check(body.IndexOf("data", StringComparison.Ordinal) < body.IndexOf("name=file", StringComparison.Ordinal));
            Check(body.Contains("\"conversation\":\"chat-1\"", StringComparison.Ordinal));
            Check(!upload.Headers.ContainsKey("Transfer-Encoding"));
            Check(server.Requests.Select(request => request.ConnectionId).Distinct().Count() == server.Requests.Count);
        });
        await Run("separate upload origin and private delivery", async () =>
        {
            await using var upload = new FixtureServer(_ => Accepted());
            await using var management = new FixtureServer(request => request.Path == "/api/upload/42/status" ? Ready(visibility: "private") : Reply.Json(new
            { success = true, data = new { asset_id = 42, variant = "webp", private_url = "https://cdn.example/private?signature=fixture", expires_at = "2030-01-01T01:00:00Z", expires_in = 3600 } }));
            var client = Client(management, uploadOrigin: upload.Url);
            Check(client.UploadBaseUrl == upload.Url && client.ApiBaseUrl == management.Url);
            await client.UploadBytesAsync(new byte[] { 1 }, "private.png", new() { Visibility = "private" });
            var ready = await client.WaitUntilReadyAsync(42);
            Check(ready.CdnUrl is null && ready.CanGeneratePrivateUrl);
            Check(management.Requests.Count == 1, "Wait must not sign automatically.");
            var link = await client.GeneratePrivateUrlAsync(42);
            Check(link.Url.StartsWith("https://cdn.example/", StringComparison.Ordinal) && link.ExpiresIn == 3600);
            Check(upload.Requests.Count == 1 && management.Requests.Count == 2);
            Check(!link.ToString()!.Contains("signature", StringComparison.Ordinal));
        });
        await Run("upload byte input is snapshotted", async () =>
        {
            await using var server = new FixtureServer(_ => Accepted());
            byte[] bytes = [70, 71, 72];
            var task = Client(server).UploadBytesAsync(bytes, "bytes.bin");
            bytes.AsSpan().Fill(90);
            await task;
            Check(Encoding.UTF8.GetString(server.Requests.Single().Body).Contains("FGH", StringComparison.Ordinal));
        });
        await Run("bounded 32 MiB file streaming and handle release", async () =>
        {
            await using var server = new FixtureServer(_ => Accepted()) { DrainOnly = true };
            string path = Path.GetTempFileName();
            try
            {
                using (var file = File.OpenWrite(path)) file.SetLength(32 * 1024 * 1024);
                GC.Collect(); long before = GC.GetTotalAllocatedBytes(true);
                await Client(server, timeout: 10000).UploadFileAsync(path, new() { Visibility = "public" });
                long allocated = GC.GetTotalAllocatedBytes(true) - before;
                Check(allocated < 8 * 1024 * 1024, "Streaming allocated more than 8 MiB.");
                Check(server.Requests.Single().BodyLength > 32 * 1024 * 1024);
                using var reopened = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
                Check(reopened.Length == 32 * 1024 * 1024);
            }
            finally { File.Delete(path); }
        });
        await Run("listing filters and lazy pagination", async () =>
        {
            await using var server = new FixtureServer(request =>
            {
                int page = request.Path.Contains("page=2", StringComparison.Ordinal) ? 2 : 1;
                var row = Status(); row["id"] = page == 1 ? 42 : 43;
                return Reply.Json(new { success = true, data = new[] { row }, page, limit = 1, total = 2 });
            });
            var client = Client(server);
            var filters = new UploadFilters { Limit = 1, Visibility = "public", Status = "processed", ExternalId = "chat & one", Data = new Dictionary<string, string> { [" owner "] = "user/one" }, DeletionStatus = "active" };
            var sequence = client.IterateUploadsAsync(filters);
            Check(server.Requests.Count == 0);
            List<long> ids = [];
            await foreach (var asset in sequence) ids.Add(asset.Id);
            Check(ids.SequenceEqual(new long[] { 42, 43 }));
            Check(server.Requests.First().Path.Contains("data.owner=user%2Fone", StringComparison.Ordinal));
            Check(server.Requests.First().Path.Contains("status=3", StringComparison.Ordinal));
            Check(server.Requests.First().Path.Contains("project_id=" + Project, StringComparison.Ordinal));
            await foreach (var _ in client.IterateUploadsAsync(filters)) break;
            Check(server.Requests.Count == 3);
        });
        await Run("iterator rejects wrong returned page", async () =>
        {
            await using var server = new FixtureServer(_ => Reply.Json(new { success = true, data = new[] { Status() }, page = 2, limit = 1, total = 5 }));
            await Error(async () => { await foreach (var _ in Client(server).IterateUploadsAsync()) { } }, "INVALID_RESPONSE");
            Check(server.Requests.Count == 1);
        });
        await Run("managed asset list/detail and partial bulk deletion", async () =>
        {
            await using var server = new FixtureServer(request => request.Path.StartsWith("/api/assets?", StringComparison.Ordinal) ? Reply.Json(new { data = new[] { Record("deletionAccepted") }, page = 1, limit = 20, total = 1 }) : request.Path == "/api/assets/42" ? Reply.Json(Record("deletionAccepted")) : Reply.Json(Record("bulkDeletion")));
            var client = Client(server);
            Check((await client.ListAssetsAsync(new() { DeletionStatus = "deleting" })).Data[0].StorageCreditedMb == 0);
            Check((await client.GetAssetAsync(42)).Id == 42);
            var bulk = await client.BulkDeleteAssetsAsync(new long[] { 42, 42, 43 });
            Check(bulk.Results.Count == 2 && !bulk.Results[1].Accepted && bulk.Counts.Failed == 1);
            Check(Encoding.UTF8.GetString(server.Requests.Last().Body).Contains("[42,42,43]", StringComparison.Ordinal));
        });
        await Run("all nine platform operations and omitted destructive scopes", async () =>
        {
            await using var server = new FixtureServer(request =>
            {
                if (request.Path.Contains("/upload-keys", StringComparison.Ordinal))
                {
                    if (request.Method == "GET") return Reply.Json(new { success = true, upload_keys = new[] { Key() }, page = 1, limit = 20, total = 1 });
                    if (request.Path.EndsWith("/revoke", StringComparison.Ordinal)) return Reply.Json(new { success = true });
                    return Reply.Json(new { success = true, id = KeyId, key_id = "fixture-key-id", api_key = "issued-fixture-credential", upload_key = request.Path.EndsWith("/rotate", StringComparison.Ordinal) ? null : Key() });
                }
                if (request.Method == "GET") return Reply.Json(new { success = true, project_users = new[] { User() }, page = 1, limit = 20, total = 1, project_active_count = 1, org_active_count = 2, usage_period = new { start = "2030-01-01", end = "2030-02-01" } });
                if (request.Path.EndsWith("/suspend", StringComparison.Ordinal)) return Reply.Json(new { success = true, project_user = User("suspended") });
                if (request.Path == "/api/platform/project-users") return Reply.Json(new { success = true, created = true, project_user = User() });
                return Reply.Json(new { success = true, project_user = User() });
            });
            var platform = Client(server).Platform;
            Check((await platform.ListUsersAsync()).OrgActiveCount == 2);
            Check((await platform.CreateUserAsync(new() { CustomerUserId = "example-user", Metadata = new Dictionary<string, object?> { ["team"] = "example" } })).Created);
            Check((await platform.UpdateUserAsync(UserId, new() { DisplayName = "Example" })).Id == UserId);
            Check((await platform.SuspendUserAsync(UserId)).Status == "suspended");
            Check((await platform.ReactivateUserAsync(UserId)).Status == "active");
            Check((await platform.ListUploadKeysAsync(UserId)).Data.Count == 1);
            var key = await platform.CreateUploadKeyAsync(UserId, new() { Name = "Chat uploads", AllowedVisibility = "private" });
            Check(key.ApiKey == "issued-fixture-credential");
            Check(!key.ToString()!.Contains(key.ApiKey, StringComparison.Ordinal));
            Check(!Encoding.UTF8.GetString(server.Requests.Last().Body).Contains("scopes", StringComparison.Ordinal));
            // An absent upload_key is allowed when rotating; null is not a valid record.
            await Error(() => platform.RotateUploadKeyAsync(UserId, KeyId), "INVALID_RESPONSE", true);
            await platform.RevokeUploadKeyAsync(UserId, KeyId);
            Check(server.Requests.Count == 9);
        });
        await Run("rotate permits absent upload key and supports explicit scopes", async () =>
        {
            await using var server = new FixtureServer(_ => Reply.Json(new { success = true, id = KeyId, key_id = "fixture-key-id", api_key = "issued-fixture-credential" }));
            var platform = new PlatformClient(new() { ApiKey = Credential, ApiBaseUrl = server.Url, MaxReadRetries = 0 });
            Check((await platform.RotateUploadKeyAsync(UserId, KeyId)).UploadKey is null);
            await platform.CreateUploadKeyAsync(UserId, new() { Name = "Cleanup", Scopes = new[] { "delete", "status" }, AllowedAssetTypes = new long[] { 1 }, ExpiresAt = DateTimeOffset.UtcNow.AddDays(1) });
            Check(Encoding.UTF8.GetString(server.Requests.Last().Body).Contains("\"scopes\":[\"delete\",\"status\"]", StringComparison.Ordinal));
        });
        await Run("key scopes distinguish empty from omitted and explicit selections", async () =>
        {
            await using var server = new FixtureServer(_ => Reply.Json(new
            { success = true, id = KeyId, key_id = "fixture-key-id", api_key = "issued-fixture-credential" }));
            var platform = Client(server).Platform;
            KompressrException? failure = null;
            try { await platform.CreateUploadKeyAsync(UserId, new() { Name = "Empty selection", Scopes = Array.Empty<string>() }); }
            catch (KompressrException error) { failure = error; }
            Check(server.Requests.Count == 0 && server.Connections == 0, "Explicit empty scopes dispatched an HTTP request.");
            Check(failure?.Code == "INVALID_ARGUMENT" && failure.Kind == "validation" && !failure.MayHaveSucceeded,
                "Explicit empty scopes must fail validation before dispatch.");

            await platform.CreateUploadKeyAsync(UserId, new() { Name = "Default permissions" });
            await platform.CreateUploadKeyAsync(UserId, new() { Name = "Null uses defaults", Scopes = null });
            string[] selected = ["status", "delete", "status"];
            await platform.CreateUploadKeyAsync(UserId, new() { Name = "Explicit permissions", Scopes = selected });
            var requests = server.Requests.ToArray();
            Check(requests.Length == 3);
            foreach (var request in requests.Take(2))
            {
                using var body = JsonDocument.Parse(request.Body);
                Check(!body.RootElement.TryGetProperty("scopes", out _), "Omitted or null scopes must leave server defaults available.");
            }
            using var explicitBody = JsonDocument.Parse(requests[2].Body);
            Check(explicitBody.RootElement.GetProperty("scopes").EnumerateArray().Select(value => value.GetString()).SequenceEqual(selected),
                "Explicit scope selections must be sent exactly as requested.");
        });
        await Run("validation sends no requests", async () =>
        {
            await using var server = new FixtureServer(_ => Accepted());
            var client = Client(server);
            Func<Task>[] invalid =
            [
                () => client.GetAssetAsync(0), () => client.GetAssetAsync(9_007_199_254_740_992),
                () => client.UploadBytesAsync(new byte[] { 1 }, "bad\nname"),
                () => client.UploadBytesAsync(new byte[] { 1 }, "x", new() { Visibility = "unknown" }),
                () => client.UploadBytesAsync(new byte[] { 1 }, "x", new() { PrivateUrlExpiresIn = 59 }),
                () => client.UploadBytesAsync(new byte[] { 1 }, "x", new() { Data = new Dictionary<string, object?> { ["a"] = "one", [" a "] = "two" } }),
                () => client.UploadBytesAsync(new byte[] { 1 }, "x", new() { Data = new Dictionary<string, object?> { ["a"] = double.NaN } }),
                () => client.UploadBytesAsync(new byte[] { 1 }, "x", new() { Data = new Dictionary<string, object?> { ["a"] = new string('é', 257) } }),
                () => client.UploadBytesAsync(new byte[] { 1 }, "x", new() { Data = new Dictionary<string, object?> { ["a"] = new[] { 1 } } }),
                () => client.GeneratePrivateUrlAsync(42, new() { Variant = "png" }),
                () => client.ListUploadsAsync(new() { ProjectId = "bad" }),
                () => client.ListUploadsAsync(new() { Limit = 101 }),
                () => client.ListUploadsAsync(new() { Status = "unknown" }),
                () => client.GetAssetAsync(42, new() { Timeout = TimeSpan.Zero }),
                () => client.WaitUntilReadyAsync(42, new() { PollInterval = TimeSpan.FromSeconds(31) }),
                () => client.BulkDeleteAssetsAsync(Array.Empty<long>()),
                () => client.BulkDeleteAssetsAsync(Enumerable.Repeat(42L, 101).ToArray()),
                () => client.Platform.CreateUserAsync(new() { CustomerUserId = " " }),
                () => client.Platform.UpdateUserAsync("bad", new()),
                () => client.Platform.CreateUploadKeyAsync(UserId, new() { Name = "bad", Scopes = new[] { "admin" } }),
                () => client.Platform.CreateUploadKeyAsync(UserId, new() { Name = "bad", ExpiresAt = DateTimeOffset.UtcNow.AddDays(-1) }),
                () => client.Platform.CreateUploadKeyAsync(UserId, new() { Name = "bad", AllowedAssetTypes = new long[] { 0 } }),
                () => client.Platform.RevokeUploadKeyAsync(UserId, "bad")
            ];
            foreach (var call in invalid) await Error(call, "INVALID_ARGUMENT", false);
            Check(server.Requests.Count == 0);
            foreach (var origin in new[] { "ftp://example.test", "https://example.test/path", "https://user@example.test", "https://example.test?query=1" })
                await Error(() => Task.FromResult(new KompressrClient(new() { ApiKey = Credential, ApiBaseUrl = origin })), "INVALID_ARGUMENT");
            await Error(() => Task.FromResult(new KompressrClient(new() { ApiKey = "bad\r\nkey" })), "INVALID_ARGUMENT");
            var defaults = new KompressrClient(new() { ApiKey = Credential });
            Check(defaults.ApiBaseUrl == "https://kompressr.com" && defaults.UploadBaseUrl == "https://uploads.kompressr.com");
        });
        foreach (int status in new[] { 429, 502, 503, 504 }) await Run("GET retries HTTP " + status, async () =>
        {
            int calls = 0;
            await using var server = new FixtureServer(_ => Interlocked.Increment(ref calls) == 1 ? new Reply { Status = status, Body = "gateway page", Headers = new() { ["Retry-After"] = "0" } } : Ready());
            Check((await Client(server, retries: 2).GetUploadStatusAsync(42)).Id == 42);
            Check(calls == 2);
        });
        await Run("GET EOF retry count excludes hidden transport retries", async () =>
        {
            await using var server = new FixtureServer(_ => new() { Disconnect = true });
            await Error(() => Client(server, retries: 2).GetUploadStatusAsync(42), "NETWORK_ERROR", false);
            Check(server.Requests.Count == 3 && server.Connections == 3, "Native retries exceeded the configured attempt count.");
        });
        await Run("Retry-After remains bounded by total deadline", async () =>
        {
            await using var server = new FixtureServer(_ => new() { Status = 429, Body = "{}", Headers = new() { ["Retry-After"] = "60" } });
            var watch = Stopwatch.StartNew();
            var error = await Error(() => Client(server, retries: 2, timeout: 100).GetUploadStatusAsync(42), "REQUEST_TIMEOUT");
            Check(error.Status == 429 && error.RetryAfter == TimeSpan.FromSeconds(60));
            Check(server.Requests.Count == 1 && watch.Elapsed < TimeSpan.FromSeconds(2));
        });
        await Run("Retry-After body fallback and HTTP date", async () =>
        {
            foreach (bool header in new[] { false, true })
            {
                await using var server = new FixtureServer(_ => new() { Status = 503, Body = "{\"retry_after\":5}", Headers = header ? new() { ["Retry-After"] = DateTimeOffset.UtcNow.AddSeconds(20).ToString("R") } : new() });
                var error = await Error(() => Client(server, retries: 1, timeout: 80).GetUploadStatusAsync(42), "REQUEST_TIMEOUT");
                Check(error.RetryAfter >= TimeSpan.FromSeconds(4) && server.Requests.Count == 1);
            }
        });
        await Run("permissions are preserved without retry or credential fallback", async () =>
        {
            await using var server = new FixtureServer(_ => Reply.Json(new { success = false, code = "SCOPE_FORBIDDEN", error = "The supplied key lacks the delete scope." }, 403));
            var client = Client(server, retries: 5);
            var read = await Error(() => client.GetAssetAsync(42), "SCOPE_FORBIDDEN", false);
            var write = await Error(() => client.DeleteAssetAsync(42), "SCOPE_FORBIDDEN", false, 42);
            await Error(() => client.Platform.ListUsersAsync(), "SCOPE_FORBIDDEN", false);
            Check(read.Status == 403 && write.Message.Contains("delete scope", StringComparison.Ordinal));
            Check(server.Requests.Count == 3 && server.Requests.All(r => r.Headers["Authorization"] == "Bearer " + Credential));
        });
        await Run("error text redacts credentials and private URLs", async () =>
        {
            await using var server = new FixtureServer(_ => Reply.Json(new { success = false, code = "FORBIDDEN", error = "Unsupported format " + Credential + " Bearer fixture-other https://cdn.example/private?signature=hidden api_key=another" }, 403));
            var error = await Error(() => Client(server).GetAssetAsync(42), "FORBIDDEN");
            string output = error.ToString();
            Check(output.Contains("Unsupported format", StringComparison.Ordinal));
            foreach (var secret in new[] { Credential, "fixture-other", "cdn.example", "signature=hidden", "another" }) Check(!output.Contains(secret, StringComparison.Ordinal));
            Check(error.InnerException is null);
        });
        foreach (string operation in new[] { "upload", "sign", "delete", "suspend", "revoke" }) await Run("one dispatched " + operation + " after disconnect", async () =>
        {
            await using var server = new FixtureServer(_ => new() { Disconnect = true });
            var client = Client(server, retries: 5);
            Func<Task> call = operation switch
            {
                "upload" => () => client.UploadBytesAsync(new byte[] { 1 }, "x"),
                "sign" => () => client.GeneratePrivateUrlAsync(42),
                "delete" => () => client.DeleteAssetAsync(42),
                "suspend" => () => client.Platform.SuspendUserAsync(UserId),
                _ => () => client.Platform.RevokeUploadKeyAsync(UserId, KeyId)
            };
            await Error(call, "NETWORK_ERROR", true);
            Check(server.Requests.Count == 1 && server.Connections == 1, "A write was replayed.");
        });
        await Run("redirect is rejected without forwarding credentials", async () =>
        {
            await using var destination = new FixtureServer(_ => Accepted());
            await using var server = new FixtureServer(_ => new() { Status = 307, Headers = new() { ["Location"] = destination.Url + "/api/upload" } });
            var error = await Error(() => Client(server).UploadBytesAsync(new byte[] { 1 }, "x"), "API_ERROR", true);
            Check(error.Status == 307 && destination.Requests.IsEmpty && server.Requests.Count == 1);
        });
        await Run("server write failure and failed success envelope stay ambiguous", async () =>
        {
            foreach (int status in new[] { 200, 500, 503 })
            {
                await using var server = new FixtureServer(_ => Reply.Json(new { success = false, code = "FAILED", error = "Operation failed." }, status));
                await Error(() => Client(server, retries: 5).DeleteAssetAsync(42), "FAILED", true, 42);
                Check(server.Requests.Count == 1);
            }
        });
        await Run("malformed uploads recover only validated envelope ID", async () =>
        {
            var badRows = new (string Body, long? Id)[]
            {
                ("{\"success\":true,\"data\":{\"asset_id\":42}}", 42),
                ("{\"success\":true,\"data\":{\"asset_id\":42", null),
                ("{\"success\":true,\"data\":{\"asset_id\":\"42\"}}", null),
                ("{\"success\":true,\"data\":{\"asset_id\":true}}", null),
                ("{\"success\":true,\"data\":{\"asset_id\":9007199254740992}}", null),
                ("{\"data\":{\"asset_id\":42}}", null), ("null", null)
            };
            foreach (var (body, id) in badRows)
            {
                await using var server = new FixtureServer(_ => new() { Body = body });
                var error = await Error(() => Client(server).UploadBytesAsync(new byte[] { 1 }, "x"), "INVALID_RESPONSE", true);
                Check(error.AssetId == id && error.Status == 200);
                Check(server.Requests.Count == 1);
            }
        });
        await Run("malformed mutation IDs and bulk per-item outcomes", async () =>
        {
            await using var signing = new FixtureServer(_ => Reply.Json(new { success = true, data = new { asset_id = 43, variant = "webp", private_url = "https://cdn.example/signed", expires_at = "2030-01-01", expires_in = 3600 } }));
            await Error(() => Client(signing).GeneratePrivateUrlAsync(42), "INVALID_RESPONSE", true, 42);
            var deletion = Record("deletionAccepted").AsObject(); deletion["deletion_status"] = "active";
            await using var deleting = new FixtureServer(_ => Reply.Json(deletion));
            await Error(() => Client(deleting).DeleteAssetAsync(42), "INVALID_RESPONSE", true, 42);
            var bulk = Record("bulkDeletion").AsObject(); bulk["counts"]!["accepted"] = 2;
            await using var bulking = new FixtureServer(_ => Reply.Json(bulk));
            var error = await Error(() => Client(bulking).BulkDeleteAssetsAsync(new long[] { 42, 43 }), "INVALID_RESPONSE", true);
            Check(error.AssetId is null);
        });
        await Run("malformed key response does not reveal one-time secret", async () =>
        {
            await using var server = new FixtureServer(_ => Reply.Json(new { success = true, id = KeyId, key_id = "fixture-key-id", api_key = "issued-secret-fixture", upload_key = new { id = KeyId } }));
            var error = await Error(() => Client(server).Platform.RotateUploadKeyAsync(UserId, KeyId), "INVALID_RESPONSE", true);
            Check(!error.ToString().Contains("issued-secret-fixture", StringComparison.Ordinal) && error.Status == 200);
        });
        await Run("private and deleted delivery URLs are rejected", async () =>
        {
            foreach (string mutation in new[] { "private", "deleted", "url", "id", "size", "boolean", "status", "metadata", "missingName" })
            {
                var row = Status();
                switch (mutation)
                {
                    case "private": row["visibility"] = "private"; break;
                    case "deleted": row["deletion_status"] = "deleted"; break;
                    case "url": row["cdn_url"] = "https://user:password@example.test/path"; break;
                    case "id": row["id"] = true; break;
                    case "size": row["original_size"] = -1; break;
                    case "boolean": row["can_generate_private_url"] = "false"; break;
                    case "status": row["status"] = "future"; break;
                    case "metadata": row["data"] = new JsonObject { ["nested"] = new JsonObject() }; break;
                    case "missingName": row.Remove("original_name"); break;
                }
                await using var server = new FixtureServer(_ => Reply.Json(new { success = true, data = row }));
                if (mutation == "missingName") Check((await Client(server).GetUploadStatusAsync(42)).OriginalName is null);
                else await Error(() => Client(server, retries: 5).GetUploadStatusAsync(42), "INVALID_RESPONSE", false);
                Check(server.Requests.Count == 1);
            }
        });
        await Run("oversized and malformed response bodies", async () =>
        {
            foreach (string body in new[] { "not json", new string('x', 2 * 1024 * 1024 + 1) })
            {
                await using var server = new FixtureServer(_ => new() { Body = body });
                await Error(() => Client(server, retries: 5).GetUploadStatusAsync(42), "INVALID_RESPONSE", false);
                Check(server.Requests.Count == 1);
            }
        });
        await Run("body read timeout preserves response status and write uncertainty", async () =>
        {
            await using var server = new FixtureServer(_ => new() { Body = Accepted().Body, BeforeBody = TimeSpan.FromSeconds(3) });
            var watch = Stopwatch.StartNew();
            var error = await Error(() => Client(server, timeout: 100).UploadBytesAsync(new byte[] { 1 }, "x"), "REQUEST_TIMEOUT", true);
            Check(error.Status == 200 && error.AssetId is null && watch.Elapsed < TimeSpan.FromSeconds(2));
        });
        await Run("cancellation before dispatch sends nothing", async () =>
        {
            await using var server = new FixtureServer(_ => Accepted());
            using var stop = new CancellationTokenSource(); stop.Cancel();
            var client = Client(server);
            await Error(() => client.UploadBytesAsync(new byte[] { 1 }, "x", cancellationToken: stop.Token), "REQUEST_CANCELLED", false);
            await Error(() => client.DeleteAssetAsync(42, cancellationToken: stop.Token), "REQUEST_CANCELLED", false);
            Check(server.Requests.IsEmpty);
        });
        await Run("cancellation during delayed body", async () =>
        {
            await using var server = new FixtureServer(_ => new() { Body = Accepted().Body, BeforeBody = TimeSpan.FromSeconds(3) });
            using var stop = new CancellationTokenSource(TimeSpan.FromMilliseconds(100));
            var error = await Error(() => Client(server).UploadBytesAsync(new byte[] { 1 }, "x", cancellationToken: stop.Token), "REQUEST_CANCELLED", true);
            Check(error.Status == 200 && server.Requests.Count == 1);
        });
        await Run("truncated write body is never replayed", async () =>
        {
            await using var server = new FixtureServer(_ => new() { Body = Accepted().Body, Truncate = true });
            await Error(() => Client(server, retries: 5).UploadBytesAsync(new byte[] { 1 }, "x"), "NETWORK_ERROR", true);
            Check(server.Requests.Count == 1);
        });
        await Run("wait timeout/cancellation retain ID and resume without reupload", async () =>
        {
            bool processed = false;
            await using var server = new FixtureServer(_ => Ready(processed ? "processed" : "processing"));
            var client = Client(server);
            await Error(() => client.WaitUntilReadyAsync(42, new() { Timeout = TimeSpan.FromMilliseconds(80), PollInterval = TimeSpan.FromMilliseconds(10) }), "WAIT_TIMEOUT", false, 42);
            using var stop = new CancellationTokenSource(TimeSpan.FromMilliseconds(50));
            await Error(() => client.WaitUntilReadyAsync(42, new() { PollInterval = TimeSpan.FromMilliseconds(10) }, stop.Token), "WAIT_CANCELLED", false, 42);
            processed = true;
            Check((await client.WaitUntilReadyAsync(42)).Id == 42);
            Check(server.Requests.All(request => request.Method == "GET"));
        });
        await Run("wait deadline includes delayed status body", async () =>
        {
            await using var server = new FixtureServer(_ => new() { Body = Ready().Body, BeforeBody = TimeSpan.FromSeconds(2) });
            var error = await Error(() => Client(server).WaitUntilReadyAsync(42, new() { Timeout = TimeSpan.FromMilliseconds(80) }), "WAIT_TIMEOUT", false, 42);
            Check(error.AssetId == 42 && server.Requests.Count == 1);
        });
        foreach (string terminal in new[] { "failed", "unprocessable", "unknown", "deleting", "missingPublicUrl", "unavailablePrivate" }) await Run("wait terminal " + terminal, async () =>
        {
            var row = Status(terminal is "failed" or "unprocessable" or "unknown" ? terminal : "processed");
            if (terminal == "deleting") { row["deletion_status"] = "deleting"; row.Remove("cdn_url"); }
            if (terminal == "missingPublicUrl") row.Remove("cdn_url");
            if (terminal == "unavailablePrivate") { row["visibility"] = "private"; row.Remove("cdn_url"); row["can_generate_private_url"] = false; }
            await using var server = new FixtureServer(_ => Reply.Json(new { success = true, data = row }));
            string code = terminal == "deleting" ? "ASSET_DELETED" : terminal is "missingPublicUrl" or "unavailablePrivate" ? "INVALID_RESPONSE" : "PROCESSING_FAILED";
            await Error(() => Client(server).WaitUntilReadyAsync(42), code, false, 42);
            Check(server.Requests.Count == 1);
        });
        Console.WriteLine($"{passed} integration scenarios passed.");
    }
}
