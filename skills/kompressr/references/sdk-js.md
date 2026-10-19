# JavaScript and TypeScript

Node.js 22+. ESM, CommonJS and TypeScript declarations are provided. This release does not certify browsers, edge runtimes, Bun, Deno or React Native. Use a Node backend route/job for React, Next.js or other frontend applications.

```sh
npm install @kompressr/sdk
```

Integration helper; `saveAssetId` is supplied by your application and must persist before resolving:

```js
import { KompressrClient } from '@kompressr/sdk';

const files = new KompressrClient({
  apiKey: process.env.KOMPRESSR_API_KEY,
  projectId: process.env.KOMPRESSR_PROJECT_ID,
});

export async function uploadPublic(path, saveAssetId) {
  const accepted = await files.uploadFile(path, { visibility: 'public' });
  await saveAssetId(accepted.id);
  const ready = await files.waitUntilReady(accepted.id);
  return ready.cdn_url;
}
```

For a first CLI test, use the [executable public-upload example](https://github.com/kompressrcdn/clients/blob/main/sdk-js/examples/public-upload.mjs), which saves a receipt. [Private upload walkthrough](https://github.com/kompressrcdn/clients/blob/main/guides/private-upload.md) includes setup, output and resume instructions.

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
