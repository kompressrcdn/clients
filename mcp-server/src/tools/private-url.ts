import { z } from 'zod';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import type { KompressrClient } from '../client.js';
import { KompressrError } from '@kompressr/sdk';
import { failure, NOT_CONFIGURED, readAnnotations, result } from './result.js';

export function generatePrivateUrlTool(server: McpServer, client: KompressrClient, isConfigured: () => boolean): void {
  server.tool('generate_private_url', 'Generate a fresh expiring URL after private upload processing and application access checks. Scoped keys only sign their own identity private uploads. Expiry does not delete the asset.', {
    asset_id: z.union([z.number().int().positive().max(Number.MAX_SAFE_INTEGER), z.string().regex(/^[1-9]\d*$/)]),
    expires_in: z.number().int().min(60).max(604800).optional().default(3600),
    variant: z.enum(['webp', 'avif']).optional().default('webp'),
  }, readAnnotations, async ({ asset_id, expires_in, variant }) => {
    if (!isConfigured()) return { isError: true, content: [{ type: 'text' as const, text: NOT_CONFIGURED }] };
    try {
      const response = await client.generatePrivateUrl(asset_id, expires_in, variant);
      if (!response.success || !response.data) throw new KompressrError(response.error ?? 'Private URL generation failed.', { kind: 'api', code: 'API_ERROR' });
      return result({ ...response.data }, `Private URL: ${response.data.private_url}\nExpires at: ${response.data.expires_at}\nVariant: ${response.data.variant}`);
    } catch (error) { return failure(error); }
  });
}
