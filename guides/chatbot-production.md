# Chatbot production integration reference

Start with the [runnable private-upload walkthrough](chatbot-integration.md). This reference covers the application work needed before serving real users. Use a Platform/AI project on Growth, API or Enterprise. Keep development and production in separate projects.

## 1. Provision an identity and key on first use

Configure `KOMPRESSR_API_KEY` with the **project/master key** from the Platform/AI project’s API Keys page and `KOMPRESSR_PROJECT_ID` with that same project’s UUID. This is the trusted provisioning service; the local upload walkthrough used a scoped key in a separate environment. Never give the provisioning credential to the browser or model.

Your backend creates or finds the user using its own stable application user ID. In the examples below, `session`, `credentialStore`, `chatStore`, `assetStore` and `jobs` are adapters you implement in your application; they are not SDK exports.

```ts
import { KompressrClient } from '@kompressr/sdk';

const projectId = process.env.KOMPRESSR_PROJECT_ID!;
const admin = new KompressrClient({
  apiKey: process.env.KOMPRESSR_API_KEY!,
  projectId,
});
const userId = session.user.id; // From your authenticated application session.

const { project_user } = await admin.platform.createUser({
  customerUserId: userId,
});
if (project_user.project_id !== projectId) {
  throw new Error('The project ID does not match the provisioning key.');
}
if (project_user.status !== 'active') {
  throw new Error('File access is suspended.');
}
```

`createUser` finds or creates an identity by customer ID within that project. Save the returned identity ID against your application user. Reuse this identity across their conversations. A workspace-owned bot can instead map each authorized workspace to one identity, if members are intended to share its files.

Before creating a key, check your credential store for an existing usable key. Serialize first-time provisioning per project/user across your backend workers so concurrent chats cannot create duplicate keys. Key creation itself is not idempotent; it must not run on every request.

```ts
const issued = await admin.platform.createUploadKey(project_user.id, {
  name: 'Chat file access',
  scopes: ['upload', 'status', 'list', 'private_url'],
  allowedVisibility: 'private',
});

await credentialStore.save({
  userId,
  projectId,
  projectUserId: project_user.id,
  keyRecordId: issued.id,
  apiKey: issued.api_key,
});
```

Store the secret encrypted, with access limited to provisioning and the authorized tool executor. Kompressr returns the raw key only once; listing keys does not recover it. Store `issued.id` for later rotation/revocation, separately from `issued.key_id`. If saving a newly issued key fails, reconcile the save and revoke the known unused key before issuing another. After an ambiguous key-creation response, inspect the identity's key records and reconcile any orphaned key instead of blindly retrying.

The explicit scopes above allow uploads, status/readiness checks, listing and private URL generation. They exclude deletion. Add `delete` only when the runtime should permanently delete files. Specifying scopes replaces the defaults. You may also set `allowedAssetTypes` and a future `expiresAt`; plan and project limits still apply. Choose `allowedVisibility: 'both'` only if the product needs public files as well.

## 2. Bind each tool call to the authenticated user

The backend loads the credential for the authenticated user and the configured production project. Neither the model nor the caller chooses an arbitrary credential or Kompressr identity.

```ts
const credential = await credentialStore.get(userId, projectId);
if (!credential || credential.projectId !== projectId) {
  throw new Error('File access has not been configured.');
}
const files = new KompressrClient({
  apiKey: credential.apiKey,
  projectId,
});
```

Use a separate SDK client for each selected credential. Keep keys out of prompts, tool results, browser responses and ordinary logs. The project ID is shared across users and is required for upload listing; it does not grant access. Kompressr infers the owning identity from the key.

For a browser attachment form, send the file to your own backend. Authenticate the request, authorize the conversation and apply your application's file size/type limits before reading the body. After those checks, use the **same user-bound `files` client above**:

```ts
// file is the File from the authorized multipart request, not a model-supplied path.
const accepted = await files.uploadBlob(file, file.name, {
  visibility: 'private',
  data: { conversation_id: conversationId },
});
await assetStore.save({ userId, projectId, conversationId, assetId: accepted.id });
await jobs.enqueueReadiness({ userId, projectId, assetId: accepted.id });
// Your HTTP handler returns 202 with { assetId: accepted.id }.
```

Use the durable enqueue/recovery approach below for this route too. Keep the project/master key in the provisioning service; the upload route loads the authenticated user's scoped key. Browser and edge execution of the SDK are not certified by this release.

## 3. Upload and record acceptance

Authorize the conversation before reading a supplied attachment or using a generated file. Resolve file references inside the user's authorized storage/sandbox; do not let the model choose arbitrary host filesystem paths.

```ts
await chatStore.requireAccess(userId, conversationId);
const accepted = await files.uploadFile(authorizedFilePath, {
  visibility: 'private',
  data: { conversation_id: conversationId },
});

await assetStore.save({
  userId,
  projectId,
  conversationId,
  assetId: accepted.id,
});
await jobs.enqueueReadiness({ userId, projectId, assetId: accepted.id });
```

Persist the returned ID before waiting. A short web request can return HTTP 202 with the asset ID and processing state while a background job handles readiness. Make the persisted record a durable work item, or use your job system's reliable enqueue/reconciliation mechanism so a crash between saving and enqueueing cannot strand an upload. The job carries identifiers; it obtains the user's credential from your secret store at execution time.

`data.conversation_id` is useful for filtering and reconciliation, but metadata is not an authorization boundary or an upload idempotency key. Your application must enforce conversation ownership. Two keys for the same Kompressr identity can access that identity's permitted assets across conversations. Use separate identities when a stronger boundary is required, accounting for your plan's identity allowance.

## 4. Wait for readiness and return a private link

After loading the owning user's credential, the worker checks processing. On each request for a delivery link, authorize the user against the stored asset/conversation relationship before signing.

```ts
const ownedAsset = await assetStore.requireAccess(userId, projectId, assetId);
await chatStore.requireAccess(userId, ownedAsset.conversationId);
await files.waitUntilReady(ownedAsset.assetId, { timeoutMs: 120_000 });
const link = await files.generatePrivateUrl(ownedAsset.assetId, {
  expiresIn: 3600,
});
// Return only these delivery fields to the authorized chat UI.
const delivery = { url: link.private_url, expiresAt: link.expires_at };
```

An accepted upload is not necessarily ready. If waiting times out, retain the asset ID and resume status checks; do not upload again just because polling timed out. Stop on processing failure, deletion or permission errors. Catch `KompressrError` to distinguish `WAIT_TIMEOUT` from other failures. After an interrupted or ambiguous upload, inspect the saved ID or reconcile the user's recent uploads before retrying the write; metadata alone does not prevent duplicates.

Store the asset ID in chat history so the backend can issue a fresh private link when a user reopens the conversation. A signed URL grants access to anyone holding it until expiry. Expiry does not delete the file. Public uploads instead return `ready.cdn_url` after `waitUntilReady`; those URLs do not require the user's scoped key for delivery.

## 5. Use MCP when the agent host needs it

For an agent host that supports local stdio, launch the released MCP server in the user's isolated runtime:

```json
{
  "mcpServers": {
    "kompressr": {
      "command": "npx",
      "args": ["-y", "@kompressr/mcp-server@2.0.0"],
      "env": {
        "KOMPRESSR_API_KEY": "USER_SCOPED_KEY",
        "KOMPRESSR_PROJECT_ID": "PLATFORM_PROJECT_UUID"
      }
    }
  }
}
```

The host injects the real values securely. Do not commit a filled-in configuration. MCP loads one credential configuration per process; use separate processes/sandboxes for different identities. A shared process cannot select a different user key per tool call. For a shared chatbot backend, the SDK lets your application select a user-bound client without launching one process per user.

The MCP process can read files permitted by its operating system and has no directory allowlist. Give its sandbox only the intended user's files. Scoped Kompressr credentials restrict API access, not local file access. Remote `file_url` uploads download to temporary storage on the MCP host before uploading.

The file workflow is `upload_asset` → save `asset_id` → `wait_for_asset` → `generate_private_url`. Provision identities/keys through your trusted backend's SDK/API; MCP does not expose administration tools for this. Its account registration tools are unnecessary for users of an already configured chatbot.

The [Smithery listing](https://smithery.ai/servers/kompressr/kompressr) distributes a local MCPB bundle. It does not provide a hosted HTTP MCP endpoint. See [bundle installation](../smithery/README.md#install-in-a-desktop-client) for compatible desktop clients.

## Key lifecycle and user removal

- Rotate with `admin.platform.rotateUploadKey(projectUserId, keyRecordId)`. Securely persist the returned replacement and update/restart affected MCP processes; the old secret stops working. Avoid rotating while dependent jobs are in flight, or let those jobs reload the replacement credential after authorization failure.
- Revoke with `admin.platform.revokeUploadKey(projectUserId, keyRecordId)` when a runtime should lose access. Remove its stored secret too.
- Suspend with `admin.platform.suspendUser(projectUserId)` to stop that identity and revoke its keys. Reactivation does not restore revoked secrets; issue a new key after an authorized reactivation.
- Suspension/revocation does not delete files or recall already issued delivery links. A user-data deletion workflow must separately enumerate and delete the intended asset IDs with authorized credentials and check deletion progress. Do not equate accepted deletion with completed physical cleanup or removal of downloaded copies.

## Verify your integration

Use two disposable application users and a dedicated test project:

1. Sign in as each user and provision once. Confirm repeated chats reuse the identity/credential and concurrent first use does not issue duplicate keys. Confirm secrets never appear in browser payloads, model messages, logs or tool results.
2. Upload a small permitted private file for Alice, save its ID, wait for processing, sign a URL and actually fetch it. Reopen the chat and verify fresh link generation.
3. Use Bob's key to list files and try Alice's status/signing calls. Alice's files must not appear in Bob's list and cross-identity calls must be denied. A deliberately shared signed URL remains a delivery capability until expiry.
4. Verify your application's conversation membership checks even for two conversations owned by one Kompressr identity. Confirm a forged user ID or asset ID cannot select another user's credential.
5. Test missing permissions, polling timeout recovery and a revoked/expired key. A key lacking `delete` must not delete files. Rotate a test key and confirm the old key fails while the updated runtime works.
6. Delete only the disposable test assets using an authorized key, then inspect deletion progress. If using MCP, repeat the file workflow through the actual client and its sandbox.

SDK fixtures verify package behavior. Your authenticated application, storage adapters, production processing/delivery and actual MCP client still need these integration checks.
