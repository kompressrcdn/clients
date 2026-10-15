import { KompressrClient, type UploadAsset } from '@kompressr/sdk';

export async function uploadPublicFile(path: string, saveId: (id: number) => Promise<void>): Promise<UploadAsset> {
  const files = new KompressrClient({ apiKey: process.env.KOMPRESSR_API_KEY! });
  const accepted = await files.uploadFile(path, { visibility: 'public' });
  await saveId(accepted.id);
  return files.waitUntilReady(accepted.id);
}
