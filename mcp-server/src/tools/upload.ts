import { z } from 'zod';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import type { KompressrClient } from '../client.js';
import { VALID_QUALITIES } from '../constants.js';
import { failure, NOT_CONFIGURED, result } from './result.js';
import { KompressrError } from '@kompressr/sdk';

export function uploadAssetTool(server: McpServer, client: KompressrClient, isConfigured: () => boolean): void {
  server.tool('upload_asset', 'Upload a supported image, video, PDF, font or text asset. Acceptance is not readiness: wait for processed before sharing. Project-user scoped upload keys restrict uploads to their identity. The 30-day free trial includes 100 image uploads total, shared across API, SDKs, MCP and dashboard. This allowance does not renew monthly.', {
    file_path: z.string().optional().describe('Local file path; provide exactly one file source'),
    file_url: z.string().url().optional().describe('HTTP(S) file downloaded on the MCP machine, then uploaded'),
    quality: z.enum(VALID_QUALITIES).optional().describe('Video quality only; availability depends on the plan'),
    visibility: z.enum(['public', 'private']).optional(),
    private_url_expires_in: z.number().int().min(60).max(604800).optional(),
    data: z.record(z.string(), z.union([z.string().max(512), z.number().finite(), z.boolean(), z.null()])).optional().describe('At most five scalar fields; UTF-8/encoded size limits apply'),
  }, { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true }, async ({ file_path, file_url, quality, visibility, private_url_expires_in, data }, context) => {
    if (!isConfigured()) return { isError: true, content: [{ type: 'text' as const, text: NOT_CONFIGURED }] };
    if (!!file_path === !!file_url) return failure(new KompressrError('Provide exactly one of file_path or file_url.', { kind: 'validation', code: 'INVALID_ARGUMENT' }));
    try {
      const options = { quality, visibility, privateUrlExpiresIn: private_url_expires_in, data, signal: context.signal };
      const response = file_path ? await client.uploadFile(file_path, options) : await client.uploadFromUrl(file_url!, options);
      if (!response.success || !response.data) throw new KompressrError(response.error ?? 'Upload failed.', { kind: 'api', code: 'API_ERROR' });
      const asset = response.data;
      const ready = asset.status === 'processed' && asset.deletion_status === 'active';
      const text = [`Upload accepted. Asset ID: ${asset.asset_id}`, `Status: ${asset.status}`, `Visibility: ${asset.visibility}`, `Original size: ${(asset.original_size / 1024).toFixed(1)} KB`,
        ready ? (asset.visibility === 'private' ? 'Generate a fresh private link after verifying access.' : `CDN URL: ${asset.cdn_url}`) : 'Save the asset ID. Call wait_for_asset or get_asset_status before sharing a delivery link.'];
      if (response.warning) text.push(`Warning: ${response.warning}`);
      return result({ ...asset, ready }, text.join('\n'));
    } catch (error) { return failure(error); }
  });
}
