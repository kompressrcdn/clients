import { z } from 'zod';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import type { KompressrClient } from '../client.js';
import { KompressrError } from '@kompressr/sdk';
import { failure, NOT_CONFIGURED, readAnnotations, result } from './result.js';

export function getAssetStatusTool(server: McpServer, client: KompressrClient, isConfigured: () => boolean): void {
  server.tool('get_asset_status', 'Inspect processing status and delivery information. Scoped keys only read uploads owned by their identity. A URL is ready only for active processed assets.', {
    asset_id: z.union([z.number().int().positive().max(Number.MAX_SAFE_INTEGER), z.string().regex(/^[1-9]\d*$/)]),
  }, readAnnotations, async ({ asset_id }) => {
    if (!isConfigured()) return { isError: true, content: [{ type: 'text' as const, text: NOT_CONFIGURED }] };
    try {
      const response = await client.getStatus(asset_id);
      if (!response.success || !response.data) throw new KompressrError(response.error ?? 'Status check failed.', { kind: 'api', code: 'API_ERROR' });
      const asset = response.data, ready = asset.status === 'processed' && asset.deletion_status === 'active';
      const lines = [`Asset ID: ${asset.id}`, `Status: ${asset.status}`, `Deletion status: ${asset.deletion_status}`, `Visibility: ${asset.visibility}`];
      if (ready && asset.visibility === 'public') lines.push(`CDN URL: ${asset.cdn_url}`);
      else if (ready) lines.push('Generate a fresh private link after verifying access.');
      else lines.push('This asset is not ready to share.');
      if (ready) lines.push(`Optimized size: ${(asset.kompressd_size / 1024).toFixed(1)} KB`, `Savings: ${asset.savings_percent.toFixed(1)}%`);
      return result({ ...asset, ready }, lines.join('\n'));
    } catch (error) { return failure(error); }
  });
}
