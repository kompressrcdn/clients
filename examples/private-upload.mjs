import { KompressrClient, KompressrError } from '@kompressr/sdk';
import { writeFile } from 'node:fs/promises';

// Run locally with a test file. The final output contains a private delivery URL.
let assetId;
try {
  const args = process.argv.slice(2);
  const resume = args[0] === '--resume';
  if ((!resume && (args.length !== 1 || args[0].startsWith('--'))) ||
      (resume && (args.length !== 2 || !/^[1-9]\d*$/.test(args[1])))) {
    throw new Error('Usage: node private-upload.mjs FILE | --resume ASSET_ID');
  }
  if (resume) {
    const resumeId = Number(args[1]);
    if (!Number.isSafeInteger(resumeId)) throw new Error('ASSET_ID must be a safe positive integer.');
    assetId = resumeId;
  }
  if (!process.env.KOMPRESSR_API_KEY?.trim()) throw new Error('Set KOMPRESSR_API_KEY in your local .env file.');
  const timeoutMs = Number(process.env.KOMPRESSR_WAIT_TIMEOUT_MS ?? 120_000);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs <= 0) throw new Error('KOMPRESSR_WAIT_TIMEOUT_MS must be a positive integer.');
  const files = new KompressrClient({
    apiKey: process.env.KOMPRESSR_API_KEY,
    // Optional overrides for a custom deployment or local test fixtures.
    apiBaseUrl: process.env.KOMPRESSR_API_URL,
    uploadBaseUrl: process.env.KOMPRESSR_UPLOAD_BASE_URL,
  });

  if (!resume) {
    const accepted = await files.uploadFile(args[0], { visibility: 'private' });
    assetId = accepted.id;
    // Print the ID before local I/O, so it remains recoverable if the disk is full.
    console.log(`Accepted asset ${assetId}.`);
    const receipt = `kompressr-upload-${assetId}.receipt.json`;
    await writeFile(receipt, JSON.stringify({ asset_id: assetId, api_base_url: files.apiBaseUrl }) + '\n', { mode: 0o600, flag: 'wx' });
    console.log(`Saved ${receipt}.`);
  }

  const ready = await files.waitUntilReady(assetId, { timeoutMs });
  if (ready.visibility !== 'private') throw new Error('This example only signs private assets. Check the saved asset ID.');
  const link = await files.generatePrivateUrl(assetId, { expiresIn: 3600 });
  console.log(`Ready. Private link expires at ${link.expires_at}:`);
  console.log(link.private_url);
} catch (error) {
  if (error instanceof KompressrError) {
    assetId ??= error.assetId;
    console.error(`${error.code}: ${error.message}`);
    if (error.mayHaveSucceeded && !assetId) {
      console.error('The upload may have been accepted. Check this identity’s recent uploads before trying again.');
    }
  } else {
    // Do not dump SDK request objects, credentials or private URLs on failure.
    console.error(error instanceof Error ? error.message : 'The example failed.');
  }
  if (assetId) {
    console.error(`Keep asset ${assetId}. After resolving the error, resume with the same identity and API origin:`);
    console.error(`node --env-file=.env private-upload.mjs --resume ${assetId}`);
  }
  process.exitCode = 1;
}
