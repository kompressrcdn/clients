# @kompressr/sdk

Node.js client for Kompressr file storage, optimization and delivery. Use the same client from JavaScript or TypeScript. It has no runtime dependencies and does not start an MCP server or save credentials.

## Install

```sh
npm install @kompressr/sdk
```

[Create an account](https://kompressr.com/signup) and choose a plan with API upload access. In [Dashboard → Projects](https://kompressr.com/dashboard/projects), open a project and select **API Keys**. Generate a key and store its full value securely as `KOMPRESSR_API_KEY` on your backend; it is shown only once. Project keys use `KEY_ID.SECRET` format. Use the project's UUID when listing uploads.

For source builds before publication, follow [CONTRIBUTING.md](CONTRIBUTING.md), run `npm pack` in the built package directory and install the resulting tarball in your application.

Supported runtimes: Node 22.12+ and Node 24. Both ESM imports and CommonJS `require` are provided, with TypeScript declarations. Browser, edge, Bun, Deno and React Native support are not certified by this release. API uploads require an eligible paid plan; the free dashboard image trial does not grant API upload access. File formats, sizes and processing options depend on your plan and project.

## First upload

```js
import { KompressrClient } from '@kompressr/sdk';

const files = new KompressrClient({
  apiKey: process.env.KOMPRESSR_API_KEY,
});

const accepted = await files.uploadFile('./output.png', {
  visibility: 'public',
  data: { external_id: 'image-123' },
});
// Persist accepted.id in your application before waiting.
await saveAssetId(accepted.id);
const ready = await files.waitUntilReady(accepted.id);
return ready.cdn_url; // In your application's handler or background job.
```

`saveAssetId` represents your own database/job persistence. See [the executable example](examples/public-upload.mjs), which saves the ID to a local receipt before waiting, and [the TypeScript example](examples/usage.ts).

An accepted upload can contain a URL while processing is pending. **Do not share the URL until processing is complete.** The helper returns the current processed result. Its default two-minute wait is a polling budget, not a processing-time guarantee. For longer jobs, save the ID and poll later; a timeout does not cancel processing or justify uploading again.

SDK upload acceptance normalizes the wire `asset_id` to `id`. Other response fields keep their API names, such as `cdn_url`, `original_size` and `deletion_status`. API response envelopes are removed. Sizes are bytes except `storage_credited_mb`, which reports the server's recorded storage credit in MB, not a cash refund.

## Endpoints and credentials

Production is the default: management requests use `https://kompressr.com`, and file uploads use `https://uploads.kompressr.com`.

For a custom deployment or local integration, configure `apiBaseUrl` and `uploadBaseUrl` explicitly:

```js
const files = new KompressrClient({
  apiKey: process.env.KOMPRESSR_API_KEY,
  apiBaseUrl: process.env.KOMPRESSR_API_URL,
  uploadBaseUrl: process.env.KOMPRESSR_UPLOAD_BASE_URL,
});
```

Supply both origins when they differ. A custom management origin uses the same origin for uploads unless overridden. Overrides must be HTTP(S) origins without paths, queries, fragments or embedded credentials. Keep private endpoint settings outside source control. The removed `environment` option is rejected; configure custom endpoints explicitly.

Keep project/master keys on your trusted backend. A scoped key only accesses the identity and actions allowed by the server. Upload, status and asset management do not need a project ID; `listUploads` requires `projectId` in the constructor or call. Default scoped keys exclude deletion. Giving the client a key does not grant additional permissions or plan capabilities.

For an application with a browser upload form, send the file to your backend and use `uploadBlob` there. The [Next.js route recipe](examples/next-route.ts) demonstrates the server integration and its required application authentication. Direct browser scoped uploads need a separately verified credential and CORS workflow.

## Private files

```js
const accepted = await files.uploadFile('./report.pdf', { visibility: 'private' });
await saveAssetId(accepted.id);
await files.waitUntilReady(accepted.id, { timeoutMs: 120_000 });
// Your application must first authorize the recipient.
const link = await files.generatePrivateUrl(accepted.id, { expiresIn: 3600 });
return { url: link.private_url, expiresAt: link.expires_at };
```

Private responses never provide a public CDN URL. Generate a fresh URL after processing because an initial acceptance URL can expire while the job runs. URL lifetime is 60–604800 seconds. Expiring a URL does not delete its file, and possession of a valid signed URL grants delivery access for its permitted lifetime. Keep these links out of ordinary logs.

## Listing and deletion

```js
for await (const asset of files.iterateUploads({ projectId: 'YOUR_PROJECT_UUID' })) {
  // Each page is fetched on demand; save/use records according to your app.
}

const state = await files.deleteAsset(assetId);
// A deleting state confirms acceptance; physical cleanup runs later.
const progress = await files.getAsset(assetId);
const batch = await files.bulkDeleteAssets([firstAssetId, secondAssetId]);
for (const item of batch.results) {
  if (!item.accepted) handleFailedDeletion(item);
}
```

The illustrative IDs and handlers above come from your application. Deletion is permanent with no restore or cancellation. File-removal completion and cache invalidation are different: cached, downloaded or offline copies may remain. Repeatedly deleting the same old ID cannot delete a replacement with a new ID. Bulk HTTP success can include failed items; the SDK preserves each result. It does not expand a selection into delete-all or automatically split it into unlimited batches.

`listUploads` includes upload metadata, processing and delivery fields and requires a project ID. `listAssets` lists all managed assets within the key's scope using a smaller lifecycle record; it infers the project from the key and does not provide upload metadata/URLs. Both support deletion filters. List storage credits are zero; use `getAsset` for recorded credits.

## Errors, waiting and retries

```js
import { KompressrError } from '@kompressr/sdk';

try {
  await files.waitUntilReady(savedAssetId);
} catch (error) {
  if (error instanceof KompressrError && error.code === 'WAIT_TIMEOUT') {
    // Schedule another status check with error.assetId; do not reupload.
  } else {
    throw error;
  }
}
```

Every HTTP operation accepts `{ signal, timeoutMs }`. Request deadlines include response reads and automatic retries. Management requests default to 30 seconds; uploads default to 10 minutes. `waitUntilReady` defaults to 120 seconds with a roughly two-second polling interval and small jitter. Cancellation stops the caller's request/wait, not an accepted server job. Configure larger finite upload deadlines for your connection and file size; server/provider limits still apply.

GET requests retry network failures and HTTP 429/502/503/504 up to two times with bounded backoff, respecting `Retry-After` without shortening it. A retry delay cannot exceed the overall request deadline. `maxReadRetries: 0` disables retries. Mutating requests are not automatically replayed. After a dispatched write returns malformed JSON/data, times out, is interrupted or encounters a server failure, `mayHaveSucceeded` warns that its outcome can be ambiguous; inspect it before repeating it. Deletion can be explicitly retried with the same IDs. Processing failure, malformed responses and missing permissions are not retried as transient reads.

Cancellation before dispatch sends no write; cancellation after dispatch cannot roll back accepted server work. If a malformed upload response still has a safe numeric asset ID in a valid success envelope, the error carries that ID for status checks. Missing/unsafe IDs and broken JSON are not guessed. Status/list records can omit `original_name`; use an application display fallback.

`uploadBytes` snapshots the selected Uint8Array/Buffer view once using Blob for ordinary backing buffers; it does not copy the whole backing buffer. Shared-backed views retain a safe compatibility copy. For large generated files, prefer a file path or an existing Blob to avoid holding another in-memory snapshot.

Errors have a `kind`, `code`, optional HTTP `status`, `retryAfterMs`, `assetId`, and `mayHaveSucceeded`. Server messages are bounded and redact credential/URL material; raw gateway HTML is not included. Preserve useful codes and avoid logging keys or private delivery links yourself.

## Platform administration

The same package groups identity/key administration under `files.platform`. Use a project/master key on your backend to create customer/agent identities and issue scoped keys. Ordinary file-storage integrations can ignore this group.

```js
const { project_user } = await files.platform.createUser({
  customerUserId: 'customer-123', displayName: 'Customer 123',
});
const key = await files.platform.createUploadKey(project_user.id, { name: 'App runtime' });
// Return/store key.api_key securely for the intended runtime; never log it.
```

The default server scopes exclude `delete`. Supplying `scopes` replaces the defaults, so include every action the runtime needs. Suspension revokes keys without removing files; reactivation does not restore old secrets. These methods call existing APIs and add no dashboard or administration service.

## Reference, release and verification

See [API.md](API.md) for every method, option, result shape and permission; [CHANGELOG.md](CHANGELOG.md) for migration/release status. No server-side URL import, arbitrary filesystem path overwrite, backup/recovery, or S3 compatibility is promised by this client.

From the SDK package directory, `npm run verify` builds, typechecks, tests and verifies packed consumers. Local HTTP fixtures and protocol checks demonstrate client behavior; they do not certify the deployed processing service. Release verification includes authenticated lifecycle and registry-installation checks. This package has an independent release lifecycle within the clients repository. SDK publication must precede MCP publication because MCP depends on the SDK version. See [CONTRIBUTING.md](CONTRIBUTING.md) for local development and release checks.
