# JavaScript and TypeScript

Node.js 22+. ESM, CommonJS and TypeScript declarations are provided. This release does not certify browsers, edge runtimes, Bun, Deno or React Native. Use a Node backend route/job for React, Next.js or other frontend applications.

```sh
npm install @kompressr/sdk
```

Finish helper; the caller already holds the accepted ID. `saveAssetId` is supplied by your application and must persist before resolving:

```js
import { KompressrClient } from '@kompressr/sdk';

const files = new KompressrClient({
  apiKey: process.env.KOMPRESSR_API_KEY,
  projectId: process.env.KOMPRESSR_PROJECT_ID,
});

export async function finishPublicUpload(assetId, saveAssetId) {
  await saveAssetId(assetId);
  const ready = await files.waitUntilReady(assetId);
  return ready.cdn_url;
}
```

In the caller, upload once and retain `accepted` before invoking the helper:

```js
const accepted = await files.uploadFile(path, { visibility: 'public' });
const url = await finishPublicUpload(accepted.id, saveAssetId);
```

Handle a failed/cancelled finish in this caller with `accepted.id` still available.
After resolving the failure, retry only `finishPublicUpload` on that ID. Keep the
receipt out of a wrapper that loses it on error; see [durable recovery](sdks.md#pattern-used-in-the-language-recipes).

For a first CLI test, use the [executable public-upload example](https://github.com/kompressrcdn/clients/blob/main/sdk-js/examples/public-upload.mjs), which saves a receipt. [Private upload walkthrough](https://github.com/kompressrcdn/clients/blob/main/guides/private-upload.md) includes setup, output and resume instructions.

## Upload without optimization

For original-byte storage, replace the caller's upload call above with:

```js
const accepted = await files.uploadFile(path, { visibility: 'public', passthrough: true });
```

The same option is available on `uploadBlob` and `uploadBytes`. Keep the caller's receipt and the finish step. Follow [upload modes](uploads.md) for eligibility, confirmation, immediate readiness and private signing.

## Methods and shapes

`uploadFile(path, options)`, `uploadBlob(blob, filename, options)` and `uploadBytes(bytes, filename, options)` return acceptance with `id`. Status/readiness return API-style fields such as `cdn_url` and `can_generate_private_url`; success envelopes are removed.

For private delivery: `uploadFile(path, { visibility: 'private' })`, persist `id`, `waitUntilReady(id)`, then `generatePrivateUrl(id, { expiresIn: 3600 })` after authorization. Read `private_url` and `expires_at`.

Use `getUploadStatus`, `listUploads`, `iterateUploads` (`for await`), `listAssets`, `getAsset`, `deleteAsset` and `bulkDeleteAssets`. Listing uploads needs `projectId`. Inspect `batch.results[].accepted` for bulk outcomes.

Administration is `files.platform`: `listUsers`, `createUser`, `updateUser`, `suspendUser`, `reactivateUser`, `listUploadKeys`, `createUploadKey`, `rotateUploadKey`, `revokeUploadKey`. It requires a project key and eligible project/plan. Provisioning uses camelCase options such as `customerUserId`, `allowedVisibility` and `scopes`; responses retain fields such as `project_user.id` and `api_key`. See [security](security.md).

## Application details

- Constructor origins: `apiBaseUrl`, `uploadBaseUrl`. Request/wait budgets: `timeoutMs`; polling: `pollIntervalMs`; cancellation: `signal`. All these time values are milliseconds, except signing `expiresIn`, which is seconds.
- Catch `KompressrError`; preserve `kind`, `code`, `status`, `assetId`, `retryAfterMs`, `mayHaveSucceeded`. Resume on `WAIT_TIMEOUT`; never let a job retry blindly repeat an uncertain upload.
- Send browser uploads to your authenticated backend. The [Next.js route example](https://github.com/kompressrcdn/clients/blob/main/sdk-js/examples/next-route.ts) shows required application authentication hooks. Do not ship this package's project key in client components.
- For large files, prefer a regular local file/available Blob instead of building unnecessary in-memory copies. Respect your deployment's body/temp-storage limits.

[Full API](https://github.com/kompressrcdn/clients/blob/main/sdk-js/API.md) · [Guide](https://github.com/kompressrcdn/clients/blob/main/sdk-js/README.md) · [Examples](https://github.com/kompressrcdn/clients/tree/main/sdk-js/examples)
