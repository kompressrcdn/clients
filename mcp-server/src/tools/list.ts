import { z } from 'zod';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import type { KompressrClient } from '../client.js';
import { KompressrError } from '@kompressr/sdk';
import { failure, NOT_CONFIGURED, readAnnotations, result } from './result.js';

export function listAssetsTool(server: McpServer, client: KompressrClient, isConfigured: () => boolean): void {
  server.tool('list_assets', 'List uploaded files in the configured project, with pagination and processing/deletion filters. A scoped key lists only its identity uploads. KOMPRESSR_PROJECT_ID is required.', {
    page: z.number().int().positive().optional().default(1), limit: z.number().int().min(1).max(100).optional().default(20),
    visibility: z.enum(['public', 'private']).optional(), external_id: z.string().max(512).optional(),
    status: z.enum(['pending', 'processing', 'processed', 'failed', 'unprocessable']).optional(),
    deletion_status: z.enum(['active', 'deleting', 'deleted', 'legacy_deleted']).optional(),
    data: z.record(z.string().max(64), z.string().max(512)).optional(),
  }, readAnnotations, async ({ page, limit, visibility, external_id, status, deletion_status, data }) => {
    if (!isConfigured()) return { isError: true, content: [{ type: 'text' as const, text: NOT_CONFIGURED }] };
    try {
      const response = await client.listAssets(limit, { page, visibility, externalId: external_id, status, deletionStatus: deletion_status, data });
      if (!response.success || !response.data) throw new KompressrError(response.error ?? 'Listing failed.', { kind: 'api', code: 'API_ERROR' });
      const nextPage = response.page! * response.limit! < response.total! && response.data.length ? response.page! + 1 : null;
      const lines = [`Page ${response.page}: ${response.data.length} uploads (${response.total} total).`];
      for (const asset of response.data) lines.push(`- ID ${asset.id}: ${asset.original_name?.trim() || 'Unnamed file'}; ${asset.status}; ${asset.visibility}; ${asset.deletion_status}`);
      if (nextPage) lines.push(`Use page=${nextPage} to continue.`);
      return result({ ...response, next_page: nextPage }, lines.join('\n'));
    } catch (error) { return failure(error); }
  });
}
