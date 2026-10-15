import { KompressrClient } from '@kompressr/sdk';

export const runtime = 'nodejs';
// Integrate these functions with your app; authentication and persistence are yours.
type Dependencies = {
  authorize: (request: Request) => Promise<void>;
  saveAsset: (id: number, request: Request) => Promise<void>;
};
export function createUploadHandler({ authorize, saveAsset }: Dependencies) {
  return async function POST(request: Request): Promise<Response> {
    await authorize(request);
    const form = await request.formData();
    const file = form.get('file');
    if (!(file instanceof File)) return Response.json({ error: 'file is required' }, { status: 400 });
    const files = new KompressrClient({ apiKey: process.env.KOMPRESSR_API_KEY! });
    const accepted = await files.uploadBlob(file, file.name, { visibility: 'public' });
    await saveAsset(accepted.id, request);
    // A short web request returns acceptance; a background job/status route waits.
    return Response.json({ asset_id: accepted.id, status: accepted.status }, { status: 202 });
  };
}
// In app/api/files/route.ts, export const POST = createUploadHandler(yourDependencies).
// Apply your app's file/body limits; request.formData() is unsuitable for huge bodies.
