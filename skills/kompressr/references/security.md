# Private files, scoped keys and application users

## Choose the credential

| Credential/value | Authority and purpose |
| --- | --- |
| Project/master API key | Project-level file access and eligible identity/key administration; trusted backend only |
| Scoped upload key | One project user's allowed operations, visibility and asset types; does not grant project administration |
| Project UUID | Project identifier; may appear in public website URLs; not a secret |
| Private signed URL | Temporary bearer access to the particular delivery URL; not an API credential |

Neither key type replaces your application's login/session or overrides plan limits. A user-supplied customer ID is not proof of identity. A secret should come from backend configuration or an authorized secret handoff, not from a model's tool arguments.

## Single-owner application

For an ordinary app-managed upload, the backend can use its project key while maintaining owner/resource permissions in its own database. Authenticate the request, validate the file, upload, persist the asset ID against the owner, wait in an appropriate job, and return a public URL or an authorized private link.

Because the project key has broad access, the app must prevent arbitrary asset-ID access. For service-enforced isolation among users or tenants, use scoped identities on an eligible Platform/AI project. Growth is currently the lowest scoped-key plan; check [pricing](https://kompressr.com/pricing#file-support).

## Multi-user or chatbot flow

```text
authenticated user
    → backend checks tenant/conversation membership
    → backend selects that identity's scoped key
    → upload privately and save asset ID + owner + conversation
    → wait/check processing
    → backend rechecks access and requests a short-lived private link
    → application returns link and expiry to the authorized viewer
```

Your company owns the project/subscription. End users need your application's account, not individual Kompressr subscriptions. Use a stable identity mapping and reuse it; do not create an identity or key on every upload. Decide whether isolation is per person, tenant, workspace or agent. Files within one Kompressr identity still need any finer conversation/resource permissions in your app.

Project-authorized JS provisioning fragment:

```js
// authenticatedCustomerId comes from a verified server session.
const created = await projectFiles.platform.createUser({
  customerUserId: authenticatedCustomerId,
});
const issued = await projectFiles.platform.createUploadKey(
  created.project_user.id,
  {
    name: 'Private attachments',
    scopes: ['upload', 'status', 'list', 'private_url'],
    allowedVisibility: 'private',
  },
);
// Commit issued.api_key securely with project_user.id and key record IDs.
// Supply that stored key only to this identity's backend client/runtime.
```

This is a provisioning fragment, not a complete endpoint. Add verified authentication, idempotent application mapping, concurrency control and secure storage before calling it. `createUser` finds/creates by stable customer ID; repeated key issuance can create extra keys. If issuance succeeds but the secret response is lost, reconcile key records rather than blindly issuing more.

## Scope and policy rules

Default scopes: `upload`, `status`, `list`, `private_url`. Default visibility permits public and private files. Deletion needs explicit `delete`. Pass `allowedVisibility: 'private'` (SDK spelling varies) when the identity should never publish files publicly.

- Omitted scopes use defaults. A nonempty supplied set replaces them; include every required action.
- **Do not use an empty scope list to mean no access.** SDKs reject it; the HTTP API treats it as defaults. If permission filtering leaves no actions, do not issue the key.
- `allowed_asset_types` has separate semantics: empty/omitted allows all supported types. Use the [numeric file-family identifiers](http-api.md#restrict-file-families) for a restriction. If no families remain after filtering, do not issue a key; sending `[]` would allow all supported types.
- Expiry, visibility, types and action scopes can all deny a request. Preserve the denial; never retry with a master credential to make it succeed.
- Deleting files requires explicit application intent plus service authority. Granting upload access alone must not grant deletion.

## Keep secrets and links out of the wrong places

Project keys belong only on trusted backends. Never put them in frontend build variables, mobile binaries, committed configuration, public examples or model-visible tool arguments. Scoped keys also need careful handling: they are credentials, not harmless identifiers.

Use backend-mediated browser uploads as the ordinary app pattern. Direct browser/mobile scoped uploads require a deliberate design for authenticated key issuance, limited lifetime/policy, CORS, secure delivery and revocation. A server SDK is not automatically a browser SDK. CORS is a browser access control, not tenant authorization.

Before signing, authorize the current viewer against the saved asset's owner and conversation/resource. Return the signed URL only through that authorized response. Avoid logs/analytics containing API keys, key-issuance result objects or signed links. An unexpired signed URL is shareable bearer access; scope restrictions on later API calls do not make an already-issued link identity-bound.

## Rotation, suspension and deletion

Store the project-user UUID and key-record ID separately from the secret. Key list endpoints do not reveal raw secrets. Creation/rotation returns the new secret once; update the intended runtime securely. Rotation replaces a secret. Revocation prevents later authorized API use of that key; do not assume it recalls already-issued delivery links or downloaded files.

Suspending a project user revokes keys but does not delete files or free their storage. Reactivation does not resurrect revoked secrets; issue a new key. File removal is a separate permanent operation with asynchronous cleanup. If deleting after suspension, use authorized project credentials rather than the revoked scoped key.

## Prove isolation

Create two authorized test identities. With A's key, upload a private asset. B's status/signing/listing must not expose A's asset. A key without `delete` must fail deletion. A private-only key must fail a public upload. App conversation checks must deny a user outside the conversation even if the backend can access the asset. Deliberately sharing A's valid private URL with B can permit delivery until expiry; that is bearer-link behavior, not the same check as API key isolation.

Full workflows: [chatbot integration](https://github.com/kompressrcdn/clients/blob/main/guides/chatbot-integration.md), [production application reference](https://github.com/kompressrcdn/clients/blob/main/guides/chatbot-production.md), [API](http-api.md).
