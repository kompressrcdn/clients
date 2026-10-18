using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Kompressr.Sdk;

internal sealed class Transport
{
    internal string ApiBaseUrl { get; }
    internal string UploadBaseUrl { get; }
    private readonly string apiKey;
    private readonly TimeSpan requestTimeout;
    private readonly TimeSpan uploadTimeout;
    private readonly int retries;
    internal Transport(ClientOptions options)
    {
        if (options is null || string.IsNullOrWhiteSpace(options.ApiKey) || options.ApiKey.Any(c => c < 32 || c > 126))
            throw KompressrException.Invalid("Supply a nonempty ASCII API key without control characters.");
        apiKey = options.ApiKey;
        ApiBaseUrl = Origin(options.ApiBaseUrl);
        UploadBaseUrl = Origin(options.UploadBaseUrl ?? (ApiBaseUrl == "https://kompressr.com" ? "https://uploads.kompressr.com" : ApiBaseUrl));
        requestTimeout = Validation.Duration(options.RequestTimeout, "RequestTimeout");
        uploadTimeout = Validation.Duration(options.UploadTimeout, "UploadTimeout");
        if (options.MaxReadRetries is < 0 or > 5) throw KompressrException.Invalid("MaxReadRetries must be from 0 to 5.");
        retries = options.MaxReadRetries;
    }
    private static string Origin(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") || uri.AbsolutePath != "/" || uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0)
            throw KompressrException.Invalid("Use an absolute HTTP(S) origin without path, credentials, query or fragment.");
        return uri.GetLeftPart(UriPartial.Authority);
    }
    internal static HttpContent Json(object value) => new ByteArrayContent(JsonSerializer.SerializeToUtf8Bytes(value, Validation.JsonOptions))
    { Headers = { ContentType = new MediaTypeHeaderValue("application/json") } };

    internal async Task<T> SendAsync<T>(string path, HttpMethod method, Func<JsonElement, T> parse,
        RequestOptions? options, CancellationToken cancellationToken, HttpContent? content = null,
        bool upload = false, long? assetId = null, bool recoverUploadId = false)
    {
        using (content)
        using (var timeout = new CancellationTokenSource(Validation.Duration(options?.Timeout ?? (upload ? uploadTimeout : requestTimeout), "Timeout")))
        using (var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeout.Token))
        {
            bool write = method != HttpMethod.Get;
            bool dispatched = false;
            int? responseStatus = null;
            TimeSpan? retryAfter = null;
            var token = linked.Token;
            KompressrException Interrupted() => new(cancellationToken.IsCancellationRequested ? "Request cancelled." : "Request timed out.",
                cancellationToken.IsCancellationRequested ? "cancelled" : "timeout", cancellationToken.IsCancellationRequested ? "REQUEST_CANCELLED" : "REQUEST_TIMEOUT",
                responseStatus, retryAfter, assetId, dispatched && write);
            for (int attempt = 0; ; attempt++)
            {
                KompressrException failure;
                try
                {
                    token.ThrowIfCancellationRequested();
                    responseStatus = null;
                    retryAfter = null;
                    using var handler = CreateHandler();
                    using var http = new HttpClient(handler) { Timeout = Timeout.InfiniteTimeSpan };
                    using var request = new HttpRequestMessage(method, (upload ? UploadBaseUrl : ApiBaseUrl) + path)
                    { Version = HttpVersion.Version11, VersionPolicy = HttpVersionPolicy.RequestVersionExact, Content = content };
                    request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
                    request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
                    request.Headers.ConnectionClose = true;
                    request.Headers.ExpectContinue = false;
                    token.ThrowIfCancellationRequested();
                    dispatched = true;
                    using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, token).ConfigureAwait(false);
                    responseStatus = (int)response.StatusCode;
                    bool ok = response.IsSuccessStatusCode;
                    retryAfter = RetryDelay(response, default);
                    JsonDocument? document = null;
                    try { document = await ReadJsonAsync(response, token).ConfigureAwait(false); }
                    catch (KompressrException) when (!ok) { }
                    using (document)
                    {
                        var body = document?.RootElement ?? default;
                        retryAfter = RetryDelay(response, body);
                        if (recoverUploadId && ok && body.ValueKind == JsonValueKind.Object && body.TryGetProperty("success", out var success) && success.ValueKind == JsonValueKind.True && body.TryGetProperty("data", out var data) && data.ValueKind == JsonValueKind.Object && data.TryGetProperty("asset_id", out var id))
                        {
                            try { assetId = Validation.Integer(id, 1); } catch (KompressrException) { }
                        }
                        bool failedEnvelope = body.ValueKind == JsonValueKind.Object && body.TryGetProperty("success", out var accepted) && accepted.ValueKind == JsonValueKind.False;
                        if (!ok || failedEnvelope)
                        {
                            string code = "API_ERROR";
                            if (body.ValueKind == JsonValueKind.Object && body.TryGetProperty("code", out var codeValue) && codeValue.ValueKind == JsonValueKind.String)
                            {
                                string candidate = codeValue.GetString()!;
                                if (!candidate.Contains(apiKey, StringComparison.Ordinal) && Regex.IsMatch(candidate, "\\A[A-Za-z][A-Za-z0-9_.:-]{0,127}\\z")) code = candidate;
                            }
                            var message = body.ValueKind == JsonValueKind.Object && body.TryGetProperty("error", out var errorValue) && errorValue.ValueKind == JsonValueKind.String
                                ? SafeMessage(errorValue.GetString()!) : $"Kompressr returned HTTP {responseStatus}.";
                            throw new KompressrException(message, "api", code, responseStatus, retryAfter, assetId,
                                write && (ok || responseStatus >= 500 || responseStatus is >= 300 and < 400));
                        }
                        token.ThrowIfCancellationRequested();
                        try
                        {
                            var parsed = parse(body);
                            token.ThrowIfCancellationRequested();
                            return parsed;
                        }
                        catch (KompressrException error) when (error.Kind != "invalid_response") { throw KompressrException.BadResponse(); }
                        catch (Exception error) when (error is JsonException or InvalidOperationException or FormatException or OverflowException or ArgumentException)
                        { throw KompressrException.BadResponse(); }
                    }
                }
                catch (Exception) when (token.IsCancellationRequested) { throw Interrupted(); }
                catch (KompressrException error)
                {
                    failure = error.Kind == "invalid_response" ? error.Context(responseStatus, assetId, dispatched && write) : error;
                }
                catch (Exception error) when (error is HttpRequestException or IOException or SocketException or OperationCanceledException)
                {
                    failure = new("Unable to reach Kompressr. Check the endpoint and connection.", "network", "NETWORK_ERROR", responseStatus, retryAfter, assetId, dispatched && write);
                }
                bool transient = failure.Kind == "network" || (failure.Kind == "api" && failure.Status is 429 or 502 or 503 or 504);
                if (write || !transient || attempt >= retries) throw failure;
                var backoff = TimeSpan.FromMilliseconds(250 * (1 << attempt) + Random.Shared.Next(100));
                try { await DelayAsync(failure.RetryAfter > backoff ? failure.RetryAfter.Value : backoff, token).ConfigureAwait(false); }
                catch (OperationCanceledException) { throw Interrupted(); }
            }
        }
    }
    private string SafeMessage(string message)
    {
        string value = message.Replace(apiKey, "[redacted]", StringComparison.Ordinal);
        value = Regex.Replace(value, @"Bearer\s+\S+", "Bearer [redacted]", RegexOptions.IgnoreCase);
        value = Regex.Replace(value, "https?://[^\\s<>\"']+", "[URL redacted]", RegexOptions.IgnoreCase);
        value = Regex.Replace(value, @"\b(?:api_key|password|token|secret|signature)\s*[=:]\s*\S+", "[credential redacted]", RegexOptions.IgnoreCase);
        value = new string(value.Where(c => !char.IsControl(c)).ToArray());
        return value.Length <= 500 ? value : value[..500];
    }
    private static SocketsHttpHandler CreateHandler()
    {
        int connected = 0;
        return new SocketsHttpHandler
        {
            AllowAutoRedirect = false,
            UseCookies = false,
            AutomaticDecompression = DecompressionMethods.None,
            Credentials = null,
            PreAuthenticate = false,
            MaxResponseHeadersLength = 64,
            ConnectCallback = async (context, token) =>
            {
                // SocketsHttpHandler may retry an EOF even for a bodyless mutation. One connection
                // per SDK attempt prevents a hidden retry from dispatching a second request.
                if (Interlocked.Increment(ref connected) != 1) throw new HttpRequestException("Automatic reconnect is disabled.");
                var socket = new Socket(SocketType.Stream, ProtocolType.Tcp) { NoDelay = true };
                try
                {
                    await socket.ConnectAsync(context.DnsEndPoint, token).ConfigureAwait(false);
                    token.ThrowIfCancellationRequested();
                    return new NetworkStream(socket, ownsSocket: true);
                }
                catch { socket.Dispose(); throw; }
            }
        };
    }
    private static async Task<JsonDocument> ReadJsonAsync(HttpResponseMessage response, CancellationToken token)
    {
        const int maximum = 2 * 1024 * 1024;
        if (response.Content.Headers.ContentLength > maximum) throw KompressrException.BadResponse();
        await using var stream = await response.Content.ReadAsStreamAsync(token).ConfigureAwait(false);
        using var output = new MemoryStream();
        byte[] buffer = new byte[16 * 1024];
        while (true)
        {
            int read = await stream.ReadAsync(buffer, token).ConfigureAwait(false);
            if (read == 0) break;
            if (output.Length + read > maximum) throw KompressrException.BadResponse();
            output.Write(buffer, 0, read);
        }
        try { return JsonDocument.Parse(output.GetBuffer().AsMemory(0, checked((int)output.Length))); }
        catch (JsonException) { throw KompressrException.BadResponse(); }
    }
    private static TimeSpan? RetryDelay(HttpResponseMessage response, JsonElement body)
    {
        if (response.Headers.TryGetValues("Retry-After", out var values))
        {
            string header = values.First();
            if (double.TryParse(header, NumberStyles.Float, CultureInfo.InvariantCulture, out var seconds) && double.IsFinite(seconds) && seconds >= 0)
                return Seconds(seconds);
            if (DateTimeOffset.TryParse(header, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var date))
                return date > DateTimeOffset.UtcNow ? date - DateTimeOffset.UtcNow : TimeSpan.Zero;
        }
        if (body.ValueKind == JsonValueKind.Object && body.TryGetProperty("retry_after", out var delay) && delay.ValueKind == JsonValueKind.Number && delay.TryGetDouble(out var number) && double.IsFinite(number) && number >= 0)
            return Seconds(number);
        return null;
    }
    private static TimeSpan Seconds(double seconds)
    {
        if (seconds >= TimeSpan.MaxValue.TotalSeconds) return TimeSpan.MaxValue;
        try { return TimeSpan.FromSeconds(seconds); }
        catch (OverflowException) { return TimeSpan.MaxValue; }
    }
    internal static async Task DelayAsync(TimeSpan delay, CancellationToken token)
    {
        while (delay > TimeSpan.Zero)
        {
            var chunk = delay > TimeSpan.FromMilliseconds(int.MaxValue) ? TimeSpan.FromMilliseconds(int.MaxValue) : delay;
            await Task.Delay(chunk, token).ConfigureAwait(false);
            delay -= chunk;
        }
        token.ThrowIfCancellationRequested();
    }
}
