import { KompressrClient, KompressrError } from '@kompressr/sdk';
import { writeFile } from 'node:fs/promises';

const path = process.argv[2];
if (!path || !process.env.KOMPRESSR_API_KEY) throw new Error('Usage: KOMPRESSR_API_KEY=... node public-upload.mjs FILE');
const files = new KompressrClient({ apiKey: process.env.KOMPRESSR_API_KEY, apiBaseUrl: process.env.KOMPRESSR_API_URL, uploadBaseUrl: process.env.KOMPRESSR_UPLOAD_BASE_URL });
const accepted = await files.uploadFile(path, { visibility: 'public' });
// Save before waiting so a timeout never loses the accepted upload.
const receipt = process.env.KOMPRESSR_RECEIPT_PATH ?? `kompressr-upload-${accepted.id}.receipt.json`;
console.log(`Accepted asset ${accepted.id}; save this ID even if writing the receipt fails.`);
await writeFile(receipt, JSON.stringify({ asset_id: accepted.id, api_base_url: files.apiBaseUrl }) + '\n', { mode: 0o600, flag: 'wx' });
console.log(`Accepted asset ${accepted.id}; receipt saved to ${receipt}.`);
try {
  const ready = await files.waitUntilReady(accepted.id);
  console.log(ready.cdn_url);
} catch (error) {
  if (error instanceof KompressrError && error.code === 'WAIT_TIMEOUT') console.error(`Still processing; resume getUploadStatus(${accepted.id}) using the saved receipt.`);
  else throw error;
}
