using System.Globalization;
using System.Text.Json;

namespace Kompressr.Sdk;

/// <summary>Project identity and key administration. The service requires project authority.</summary>
public sealed class PlatformClient
{
    private readonly Transport transport;
    public PlatformClient(ClientOptions options) : this(new Transport(options)) { }
    internal PlatformClient(Transport transport) { this.transport = transport; }
    public Task<ProjectUserPage> ListUsersAsync(PageOptions? options = null, CancellationToken cancellationToken = default)
    {
        options ??= new();
        return transport.SendAsync("/api/platform/project-users?" + KompressrClient.Query(KompressrClient.Pagination(options)), HttpMethod.Get, Validation.Users, options, cancellationToken);
    }
    public Task<CreatedUser> CreateUserAsync(CreateUserOptions input, RequestOptions? options = null, CancellationToken cancellationToken = default)
    {
        if (input is null) throw KompressrException.Invalid("Supply user options.");
        var body = UserFields(input.DisplayName, input.Metadata);
        body["customer_user_id"] = Validation.Text(input.CustomerUserId, 256);
        return Write("/api/platform/project-users", HttpMethod.Post, body, response => new CreatedUser
        { Created = Validation.Boolean(Validation.Field(response, "created")), ProjectUser = Validation.User(Validation.Field(response, "project_user")) }, options, cancellationToken);
    }
    public Task<ProjectUser> UpdateUserAsync(string id, UpdateUserOptions input, RequestOptions? options = null, CancellationToken cancellationToken = default)
    {
        if (input is null) throw KompressrException.Invalid("Supply user options.");
        return Write(Path(id), HttpMethod.Patch, UserFields(input.DisplayName, input.Metadata), response => Validation.User(Validation.Field(response, "project_user")), options, cancellationToken);
    }
    public Task<ProjectUser> SuspendUserAsync(string id, RequestOptions? options = null, CancellationToken cancellationToken = default) => MutateUser(id, "suspend", options, cancellationToken);
    public Task<ProjectUser> ReactivateUserAsync(string id, RequestOptions? options = null, CancellationToken cancellationToken = default) => MutateUser(id, "reactivate", options, cancellationToken);
    public Task<Page<UploadKey>> ListUploadKeysAsync(string id, PageOptions? options = null, CancellationToken cancellationToken = default)
    {
        options ??= new();
        return transport.SendAsync(Path(id) + "/upload-keys?" + KompressrClient.Query(KompressrClient.Pagination(options)), HttpMethod.Get, body => Validation.Page(Validation.Success(body), Validation.Key, "upload_keys"), options, cancellationToken);
    }
    public Task<IssuedKey> CreateUploadKeyAsync(string id, CreateKeyOptions input, RequestOptions? options = null, CancellationToken cancellationToken = default)
    {
        if (input is null) throw KompressrException.Invalid("Supply upload key options.");
        Dictionary<string, object?> body = new() { ["name"] = Validation.Text(input.Name, 120) };
        if (input.Scopes is { } scopes)
        {
            var selected = scopes.Select(scope => Validation.Choice(scope, Validation.Scopes)).ToArray();
            if (selected.Length == 0) throw KompressrException.Invalid("Scopes must contain at least one permission. Omit Scopes to use server defaults.");
            body["scopes"] = selected;
        }
        if (input.AllowedVisibility is { } visibility) body["allowed_visibility"] = Validation.Choice(visibility, "public", "private", "both");
        if (input.AllowedAssetTypes is { } types) body["allowed_asset_types"] = types.Select(Validation.Id).ToArray();
        if (input.ExpiresAt is { } expiry)
        {
            if (expiry <= DateTimeOffset.UtcNow) throw KompressrException.Invalid("ExpiresAt must be in the future.");
            body["expires_at"] = expiry.ToUniversalTime().ToString("O", CultureInfo.InvariantCulture);
        }
        return Write(Path(id) + "/upload-keys", HttpMethod.Post, body, Validation.Issued, options, cancellationToken);
    }
    public Task<IssuedKey> RotateUploadKeyAsync(string id, string keyId, RequestOptions? options = null, CancellationToken cancellationToken = default) =>
        Write(Path(id) + "/upload-keys/" + Validation.Uuid(keyId) + "/rotate", HttpMethod.Post, null, Validation.Issued, options, cancellationToken);
    public async Task RevokeUploadKeyAsync(string id, string keyId, RequestOptions? options = null, CancellationToken cancellationToken = default) =>
        _ = await Write(Path(id) + "/upload-keys/" + Validation.Uuid(keyId) + "/revoke", HttpMethod.Post, null, _ => true, options, cancellationToken).ConfigureAwait(false);
    private Task<ProjectUser> MutateUser(string id, string action, RequestOptions? options, CancellationToken cancellationToken) =>
        Write(Path(id) + "/" + action, HttpMethod.Post, null, response => Validation.User(Validation.Field(response, "project_user")), options, cancellationToken);
    private Task<T> Write<T>(string path, HttpMethod method, object? body, Func<JsonElement, T> parse, RequestOptions? options, CancellationToken cancellationToken) =>
        transport.SendAsync(path, method, response => parse(Validation.Success(response)), options, cancellationToken, body is null ? null : Transport.Json(body));
    private static string Path(string id) => "/api/platform/project-users/" + Validation.Uuid(id);
    private static Dictionary<string, object?> UserFields(string? name, IReadOnlyDictionary<string, object?>? metadata)
    {
        Dictionary<string, object?> fields = new();
        if (name is not null) fields["display_name"] = Validation.Text(name, 120, empty: true);
        if (metadata is not null) fields["metadata"] = Validation.Metadata(metadata, 8192);
        return fields;
    }
}
