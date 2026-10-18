using System.Globalization;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace Kompressr.Sdk;

internal static class Validation
{
    internal const long MaxId = 9_007_199_254_740_991;
    private static readonly UTF8Encoding Utf8 = new(false, true);
    internal static readonly string[] Deletions = ["active", "deleting", "deleted", "legacy_deleted"];
    internal static readonly string[] Scopes = ["upload", "status", "list", "private_url", "delete"];
    internal static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new SafeLongConverter(), new SafeIntConverter() }
    };
    internal static long Id(long id)
    {
        if (id < 1 || id > MaxId) throw KompressrException.Invalid("Use a positive asset ID no greater than 9007199254740991.");
        return id;
    }
    internal static int Positive(int value, string label, int maximum = int.MaxValue)
    {
        if (value < 1 || value > maximum) throw KompressrException.Invalid($"{label} must be from 1 to {maximum}.");
        return value;
    }
    internal static TimeSpan Duration(TimeSpan value, string label, int maximumMs = int.MaxValue)
    {
        if (value.Ticks % TimeSpan.TicksPerMillisecond != 0 || value.TotalMilliseconds < 1 || value.TotalMilliseconds > maximumMs)
            throw KompressrException.Invalid($"{label} must be a positive whole number of milliseconds, at most {maximumMs}.");
        return value;
    }
    internal static string Uuid(string value)
    {
        if (value is null || !Regex.IsMatch(value, "\\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\\z"))
            throw KompressrException.Invalid("The identifier must be a UUID.");
        return value;
    }
    internal static string Choice(string value, params string[] choices)
    {
        if (!choices.Contains(value, StringComparer.Ordinal)) throw KompressrException.Invalid("Unsupported option value.");
        return value;
    }
    internal static string Text(string value, int maximum, bool empty = false, bool trim = true)
    {
        if (value is null) throw KompressrException.Invalid("A text value is required.");
        string tested = trim ? value.Trim() : value;
        try
        {
            if ((!empty && string.IsNullOrWhiteSpace(tested)) || Utf8.GetByteCount(tested) > maximum)
                throw KompressrException.Invalid($"Text exceeds its supported UTF-8 limit of {maximum} bytes or is empty.");
        }
        catch (EncoderFallbackException) { throw KompressrException.Invalid("Text must contain valid Unicode."); }
        return value;
    }
    internal static Dictionary<string, object?> Metadata(IReadOnlyDictionary<string, object?> value, int maximum = 4096)
    {
        if (value is null || value.Count > 5) throw KompressrException.Invalid("Customer data supports at most five scalar fields.");
        Dictionary<string, object?> result = new(StringComparer.Ordinal);
        foreach (var (rawKey, item) in value)
        {
            var key = Text(rawKey, 64).Trim();
            if (result.ContainsKey(key)) throw KompressrException.Invalid("Customer data keys must be unique after trimming.");
            if (item is string text) Text(text, 512, empty: true, trim: false);
            else if (item is not null && item is not bool && !IsFiniteNumber(item)) throw KompressrException.Invalid("Customer data values must be scalar JSON values.");
            result[key] = item;
        }
        if (JsonSerializer.SerializeToUtf8Bytes(result, JsonOptions).Length > maximum)
            throw KompressrException.Invalid("Encoded customer data exceeds its byte limit.");
        return result;
    }
    private static bool IsFiniteNumber(object value) => value switch
    {
        byte or sbyte or short or ushort or int or uint or long or ulong or decimal => true,
        float f => float.IsFinite(f), double d => double.IsFinite(d), _ => false
    };
    internal static JsonElement Object(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.Object) throw KompressrException.BadResponse();
        return value;
    }
    internal static JsonElement Field(JsonElement value, string name)
    {
        Object(value);
        if (!value.TryGetProperty(name, out var result)) throw KompressrException.BadResponse();
        return result;
    }
    internal static string String(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(value.GetString())) throw KompressrException.BadResponse();
        return value.GetString()!;
    }
    internal static long Integer(JsonElement value, long minimum = -MaxId, long maximum = MaxId)
    {
        if (value.ValueKind != JsonValueKind.Number || !value.TryGetDouble(out var number) || !double.IsFinite(number) || Math.Truncate(number) != number || number < minimum || number > maximum)
            throw KompressrException.BadResponse();
        return (long)number;
    }
    internal static bool Boolean(JsonElement value)
    {
        if (value.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw KompressrException.BadResponse();
        return value.GetBoolean();
    }
    internal static void EnumValue(JsonElement value, params string[] choices)
    {
        if (!choices.Contains(String(value), StringComparer.Ordinal)) throw KompressrException.BadResponse();
    }
    internal static JsonElement Success(JsonElement value)
    {
        if (!Boolean(Field(value, "success"))) throw KompressrException.BadResponse();
        return value;
    }
    internal static JsonElement Data(JsonElement value) => Field(Success(value), "data");
    private static void Strings(JsonElement value, params string[] keys)
    {
        foreach (var key in keys) if (value.TryGetProperty(key, out var item) && item.ValueKind != JsonValueKind.String) throw KompressrException.BadResponse();
    }
    private static void Url(JsonElement value)
    {
        if (!Uri.TryCreate(String(value), UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") || uri.UserInfo.Length != 0)
            throw KompressrException.BadResponse();
    }
    private static void MetadataResponse(JsonElement value)
    {
        Object(value);
        Dictionary<string, object?> data = new(StringComparer.Ordinal);
        foreach (var field in value.EnumerateObject())
        {
            if (data.ContainsKey(field.Name)) throw KompressrException.BadResponse();
            data[field.Name] = field.Value.ValueKind switch
            {
                JsonValueKind.Null => null, JsonValueKind.True => true, JsonValueKind.False => false,
                JsonValueKind.String => field.Value.GetString(),
                JsonValueKind.Number when field.Value.TryGetDouble(out var number) && double.IsFinite(number) => number,
                _ => throw KompressrException.BadResponse()
            };
        }
        try { Metadata(data, 8192); }
        catch (KompressrException) { throw KompressrException.BadResponse(); }
    }
    private static T Decode<T>(JsonElement value) => value.Deserialize<T>(JsonOptions) ?? throw KompressrException.BadResponse();
    internal static UploadAccepted Accepted(JsonElement envelope)
    {
        var value = Data(envelope);
        ValidateUpload(value, true);
        var node = JsonNode.Parse(value.GetRawText())!.AsObject();
        node["id"] = Integer(Field(value, "asset_id"), 1);
        node.Remove("asset_id");
        if (envelope.TryGetProperty("warning", out var warning) && warning.ValueKind == JsonValueKind.String) node["warning"] = warning.GetString();
        return node.Deserialize<UploadAccepted>(JsonOptions) ?? throw KompressrException.BadResponse();
    }
    private static void ValidateUpload(JsonElement value, bool accepted)
    {
        Integer(Field(value, accepted ? "asset_id" : "id"), 1);
        EnumValue(Field(value, "status"), "pending", "processing", "processed", "failed", "unprocessable", "unknown");
        EnumValue(Field(value, "visibility"), "public", "private");
        EnumValue(Field(value, "deletion_status"), Deletions);
        Integer(Field(value, "original_size"), 0);
        String(Field(value, "asset_type"));
        if (accepted) String(Field(value, "original_name"));
        Strings(value, "original_name", "deletion_requested_at", "external_id", "created_at", "input_format", "output_format", "private_url_expires_at", "warning");
        foreach (var key in new[] { "cdn_url", "cdn_url_avif", "private_url" })
        {
            if (!value.TryGetProperty(key, out var url)) continue;
            Url(url);
            if (String(Field(value, "deletion_status")) != "active" || (String(Field(value, "visibility")) == "private" && key != "private_url"))
                throw KompressrException.BadResponse();
        }
        if (value.TryGetProperty("data", out var data)) MetadataResponse(data);
        if (value.TryGetProperty("options", out var options))
            foreach (var field in Object(options).EnumerateObject()) if (field.Value.ValueKind != JsonValueKind.String) throw KompressrException.BadResponse();
        if (value.TryGetProperty("quality", out var quality)) EnumValue(quality, "480p", "720p", "1080p", "4k");
    }
    internal static UploadAsset Upload(JsonElement value)
    {
        ValidateUpload(value, false);
        Integer(Field(value, "kompressd_size"), 0);
        Boolean(Field(value, "can_generate_private_url"));
        var savings = Field(value, "savings_percent");
        if (savings.ValueKind != JsonValueKind.Number || !savings.TryGetDouble(out var number) || !double.IsFinite(number)) throw KompressrException.BadResponse();
        return Decode<UploadAsset>(value);
    }
    internal static PrivateUrl SignedUrl(JsonElement envelope, long id)
    {
        var value = Data(envelope);
        if (Integer(Field(value, "asset_id"), 1) != id) throw KompressrException.BadResponse();
        EnumValue(Field(value, "variant"), "webp", "avif");
        Url(Field(value, "private_url"));
        return new() { AssetId = id, Variant = String(Field(value, "variant")), Url = String(Field(value, "private_url")),
            ExpiresAt = String(Field(value, "expires_at")), ExpiresIn = (int)Integer(Field(value, "expires_in"), 60, 604800) };
    }
    internal static AssetState Asset(JsonElement value)
    {
        Integer(Field(value, "id"), 1); String(Field(value, "project_id")); Integer(Field(value, "kind"), 1);
        Integer(Field(value, "storage_credited_mb"), 0); Integer(Field(value, "processing_status"));
        EnumValue(Field(value, "source"), "upload", "origin"); EnumValue(Field(value, "deletion_status"), Deletions);
        Strings(value, "deletion_requested_at");
        if (value.TryGetProperty("accounting_status", out var accounting)) EnumValue(accounting, "pending", "settled", "unavailable");
        if (value.TryGetProperty("last_failure", out var failure)) foreach (var key in new[] { "code", "message", "at" }) String(Field(failure, key));
        return Decode<AssetState>(value);
    }
    internal static Page<T> Page<T>(JsonElement value, Func<JsonElement, T> parse, string key = "data")
    {
        var rows = Field(value, key);
        if (rows.ValueKind != JsonValueKind.Array) throw KompressrException.BadResponse();
        return new() { Data = rows.EnumerateArray().Select(parse).ToArray(), PageNumber = (int)Integer(Field(value, "page"), 1, int.MaxValue),
            Limit = (int)Integer(Field(value, "limit"), 1, int.MaxValue), Total = Integer(Field(value, "total"), 0) };
    }
    internal static BulkDeletion Bulk(JsonElement value, IReadOnlyList<long> expected)
    {
        var rows = Field(value, "results");
        if (rows.ValueKind != JsonValueKind.Array || rows.GetArrayLength() != expected.Count) throw KompressrException.BadResponse();
        var output = new List<BulkDeletionItem>();
        int index = 0;
        foreach (var row in rows.EnumerateArray())
        {
            long id = Integer(Field(row, "id"), 1);
            if (id != expected[index++]) throw KompressrException.BadResponse();
            int status = (int)Integer(Field(row, "status"), 100, 599);
            bool accepted = Boolean(Field(row, "accepted"));
            AssetState? state = null;
            if (accepted)
            {
                state = Asset(Field(row, "state"));
                if (status is not (200 or 202) || state.Id != id || state.DeletionStatus == "active") throw KompressrException.BadResponse();
            }
            else if (status < 400 || String(Field(row, "error")).Length == 0) throw KompressrException.BadResponse();
            Strings(row, "code", "error");
            output.Add(new() { Id = id, Status = status, Accepted = accepted, State = state,
                Code = row.TryGetProperty("code", out var code) ? code.GetString() : null,
                Error = row.TryGetProperty("error", out var error) ? error.GetString() : null });
        }
        int acceptedCount = output.Count(row => row.Accepted);
        var counts = Field(value, "counts");
        if (Integer(Field(counts, "total"), 0) != output.Count || Integer(Field(counts, "accepted"), 0) != acceptedCount || Integer(Field(counts, "failed"), 0) != output.Count - acceptedCount)
            throw KompressrException.BadResponse();
        return new() { Results = output, Counts = new() { Total = output.Count, Accepted = acceptedCount, Failed = output.Count - acceptedCount } };
    }
    internal static ProjectUser User(JsonElement value)
    {
        foreach (var key in new[] { "id", "project_id", "customer_user_id" }) String(Field(value, key));
        EnumValue(Field(value, "status"), "active", "suspended");
        Strings(value, "display_name", "created_at", "last_seen_at", "last_upload_at", "last_key_used_at");
        foreach (var key in new[] { "asset_count", "storage_bytes", "active_key_count", "bandwidth_bytes_current_period", "requests_current_period" })
            if (value.TryGetProperty(key, out var counter)) Integer(counter, 0);
        if (value.TryGetProperty("metadata", out var metadata)) MetadataResponse(metadata);
        return Decode<ProjectUser>(value);
    }
    internal static ProjectUserPage Users(JsonElement value)
    {
        var page = Page(Success(value), User, "project_users");
        UsagePeriod? period = null;
        if (value.TryGetProperty("usage_period", out var usage))
        {
            var start = String(Field(usage, "start")); var end = String(Field(usage, "end"));
            if (!DateOnly.TryParseExact(start, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _) || !DateOnly.TryParseExact(end, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _)) throw KompressrException.BadResponse();
            period = new() { Start = start, End = end };
        }
        return new() { Data = page.Data, PageNumber = page.PageNumber, Limit = page.Limit, Total = page.Total,
            ProjectActiveCount = Integer(Field(value, "project_active_count"), 0), OrgActiveCount = Integer(Field(value, "org_active_count"), 0), UsagePeriod = period };
    }
    internal static UploadKey Key(JsonElement value)
    {
        foreach (var key in new[] { "id", "key_id", "project_id", "project_user_id", "name" }) String(Field(value, key));
        var scopes = Field(value, "scopes");
        if (scopes.ValueKind != JsonValueKind.Array) throw KompressrException.BadResponse();
        foreach (var scope in scopes.EnumerateArray()) EnumValue(scope, Scopes);
        EnumValue(Field(value, "allowed_visibility"), "public", "private", "both");
        if (value.TryGetProperty("allowed_asset_types", out var types))
        {
            if (types.ValueKind != JsonValueKind.Array) throw KompressrException.BadResponse();
            foreach (var type in types.EnumerateArray()) Integer(type, 1);
        }
        foreach (var key in new[] { "expires_at", "revoked_at", "last_used_at" })
            if (value.TryGetProperty(key, out var item) && item.ValueKind is not (JsonValueKind.String or JsonValueKind.Null)) throw KompressrException.BadResponse();
        Strings(value, "created_at");
        return Decode<UploadKey>(value);
    }
    internal static IssuedKey Issued(JsonElement value)
    {
        Success(value);
        return new() { Id = String(Field(value, "id")), KeyId = String(Field(value, "key_id")), ApiKey = String(Field(value, "api_key")),
            UploadKey = value.TryGetProperty("upload_key", out var key) ? Key(key) : null };
    }
    private sealed class SafeLongConverter : JsonConverter<long>
    {
        public override long Read(ref Utf8JsonReader reader, Type type, JsonSerializerOptions options)
        {
            using var value = JsonDocument.ParseValue(ref reader);
            return Integer(value.RootElement);
        }
        public override void Write(Utf8JsonWriter writer, long value, JsonSerializerOptions options) => writer.WriteNumberValue(value);
    }
    private sealed class SafeIntConverter : JsonConverter<int>
    {
        public override int Read(ref Utf8JsonReader reader, Type type, JsonSerializerOptions options)
        {
            using var value = JsonDocument.ParseValue(ref reader);
            return (int)Integer(value.RootElement, int.MinValue, int.MaxValue);
        }
        public override void Write(Utf8JsonWriter writer, int value, JsonSerializerOptions options) => writer.WriteNumberValue(value);
    }
}
