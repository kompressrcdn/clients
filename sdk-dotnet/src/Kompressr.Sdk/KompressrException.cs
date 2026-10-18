namespace Kompressr.Sdk;

/// <summary>Safe error details. No raw HTTP bodies, credentials, URLs or transport inner exceptions.</summary>
public sealed class KompressrException : Exception
{
    public string Kind { get; }
    public string Code { get; }
    public int? Status { get; }
    public TimeSpan? RetryAfter { get; }
    public long? AssetId { get; }
    public bool MayHaveSucceeded { get; }

    internal KompressrException(string message, string kind, string code, int? status = null,
        TimeSpan? retryAfter = null, long? assetId = null, bool mayHaveSucceeded = false) : base(message)
    {
        Kind = kind; Code = code; Status = status; RetryAfter = retryAfter;
        AssetId = assetId; MayHaveSucceeded = mayHaveSucceeded;
    }
    internal KompressrException Context(int? status, long? assetId, bool mayHaveSucceeded) =>
        new(Message, Kind, Code, status ?? Status, RetryAfter, assetId ?? AssetId, mayHaveSucceeded);

    internal static KompressrException Invalid(string message) => new(message, "validation", "INVALID_ARGUMENT");
    internal static KompressrException BadResponse() => new("Kompressr returned an invalid response.", "invalid_response", "INVALID_RESPONSE");
}
