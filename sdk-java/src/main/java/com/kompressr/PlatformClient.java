package com.kompressr;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import static com.kompressr.Models.*;

/** Project identity and key administration using the owning client's credential. */
public final class PlatformClient {
    private final Transport transport;
    PlatformClient(Transport transport) { this.transport = transport; }
    public record CreatedUser(boolean created, ProjectUser projectUser) {}
    private String path(String id) { return "/api/platform/project-users/" + Validation.uuid(id); }
    private static Map<String, Object> fields(String displayName, Map<String, Object> metadata) {
        var result = new LinkedHashMap<String, Object>();
        if (displayName != null) result.put("display_name", Validation.textInput(displayName, 120, true));
        if (metadata != null) result.put("metadata", Validation.metadata(metadata, 8192));
        return result;
    }
    public ProjectUserPage listUsers() { return listUsers(Options.Pagination.DEFAULT, Options.Request.DEFAULT); }
    public ProjectUserPage listUsers(Options.Pagination options) { return listUsers(options, Options.Request.DEFAULT); }
    public ProjectUserPage listUsers(Options.Pagination supplied, Options.Request request) {
        var options = supplied == null ? Options.Pagination.DEFAULT : supplied;
        return transport.request("GET", "/api/platform/project-users?" + KompressrClient.query(KompressrClient.pagination(options.page(), options.limit())), null, request, false, null, false, root -> {
            Validation.success(root); var page = Validation.page(root, "project_users", Validation::user); UsagePeriod period = null;
            if (root.has("usage_period")) { var p = Validation.object(root.get("usage_period")); String start = Validation.str(p, "start"), end = Validation.str(p, "end"); Validation.shape(start.matches("\\d{4}-\\d{2}-\\d{2}") && end.matches("\\d{4}-\\d{2}-\\d{2}")); period = new UsagePeriod(start, end); }
            return new ProjectUserPage(page.data(), page.page(), page.limit(), page.total(), Validation.nonnegative(root, "project_active_count"), Validation.nonnegative(root, "org_active_count"), period);
        });
    }
    public CreatedUser createUser(Options.CreateUser input) { return createUser(input, Options.Request.DEFAULT); }
    public CreatedUser createUser(Options.CreateUser input, Options.Request request) {
        Validation.require(input != null, "Supply user options.");
        var body = fields(input.displayName(), input.metadata()); body.put("customer_user_id", Validation.textInput(input.customerUserId(), 256, false));
        return transport.request("POST", "/api/platform/project-users", Transport.json(body), request, false, null, false, root -> { Validation.success(root); return new CreatedUser(Validation.bool(root, "created"), Validation.user(root.get("project_user"))); });
    }
    public ProjectUser updateUser(String id, Options.UpdateUser input) { return updateUser(id, input, Options.Request.DEFAULT); }
    public ProjectUser updateUser(String id, Options.UpdateUser input, Options.Request request) {
        Validation.require(input != null, "Supply update options.");
        return transport.request("PATCH", path(id), Transport.json(fields(input.displayName(), input.metadata())), request, false, null, false, root -> Validation.user(Validation.success(root).get("project_user")));
    }
    public ProjectUser suspendUser(String id) { return suspendUser(id, Options.Request.DEFAULT); }
    public ProjectUser suspendUser(String id, Options.Request request) { return mutateUser(id, "suspend", request); }
    public ProjectUser reactivateUser(String id) { return reactivateUser(id, Options.Request.DEFAULT); }
    public ProjectUser reactivateUser(String id, Options.Request request) { return mutateUser(id, "reactivate", request); }
    private ProjectUser mutateUser(String id, String action, Options.Request request) { return transport.request("POST", path(id) + "/" + action, null, request, false, null, false, root -> Validation.user(Validation.success(root).get("project_user"))); }
    public Page<UploadKey> listUploadKeys(String id) { return listUploadKeys(id, Options.Pagination.DEFAULT, Options.Request.DEFAULT); }
    public Page<UploadKey> listUploadKeys(String id, Options.Pagination options) { return listUploadKeys(id, options, Options.Request.DEFAULT); }
    public Page<UploadKey> listUploadKeys(String id, Options.Pagination supplied, Options.Request request) {
        var options = supplied == null ? Options.Pagination.DEFAULT : supplied;
        return transport.request("GET", path(id) + "/upload-keys?" + KompressrClient.query(KompressrClient.pagination(options.page(), options.limit())), null, request, false, null, false, root -> Validation.page(Validation.success(root), "upload_keys", Validation::key));
    }
    public IssuedKey createUploadKey(String id, Options.CreateKey input) { return createUploadKey(id, input, Options.Request.DEFAULT); }
    public IssuedKey createUploadKey(String id, Options.CreateKey input, Options.Request request) {
        Validation.require(input != null, "Supply key options."); var body = new LinkedHashMap<String, Object>(); body.put("name", Validation.textInput(input.name(), 120, false));
        if (input.scopes() != null) { Validation.require(!input.scopes().isEmpty(), "Supply at least one scope, or omit scopes to use the server defaults."); Validation.require(input.scopes().stream().allMatch(s -> s != null && Validation.SCOPES.contains(s)), "Unsupported upload scope."); body.put("scopes", input.scopes()); }
        if (input.allowedVisibility() != null) body.put("allowed_visibility", Validation.choice(input.allowedVisibility(), "public", "private", "both"));
        if (input.allowedAssetTypes() != null) { Validation.require(input.allowedAssetTypes().stream().allMatch(v -> v != null && v > 0), "Asset types must be positive integers."); body.put("allowed_asset_types", input.allowedAssetTypes()); }
        if (input.expiresAt() != null) { try { Validation.require(Instant.parse(input.expiresAt()).isAfter(Instant.now()), "expiresAt must be in the future."); } catch (java.time.DateTimeException e) { throw KompressrException.invalid("expiresAt must be an ISO timestamp."); } body.put("expires_at", input.expiresAt()); }
        return transport.request("POST", path(id) + "/upload-keys", Transport.json(body), request, false, null, false, Validation::issued);
    }
    public IssuedKey rotateUploadKey(String id, String keyId) { return rotateUploadKey(id, keyId, Options.Request.DEFAULT); }
    public IssuedKey rotateUploadKey(String id, String keyId, Options.Request request) {
        return transport.request("POST", path(id) + "/upload-keys/" + Validation.uuid(keyId) + "/rotate", null, request, false, null, false, Validation::issued);
    }
    public void revokeUploadKey(String id, String keyId) { revokeUploadKey(id, keyId, Options.Request.DEFAULT); }
    public void revokeUploadKey(String id, String keyId, Options.Request request) {
        transport.request("POST", path(id) + "/upload-keys/" + Validation.uuid(keyId) + "/revoke", null, request, false, null, false, root -> { Validation.success(root); return null; });
    }
}
