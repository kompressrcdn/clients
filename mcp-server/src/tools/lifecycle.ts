import { z } from 'zod';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import type { KompressrClient } from '../client.js';
import { failure, NOT_CONFIGURED, readAnnotations, result } from './result.js';

const id = z.union([z.number().int().positive().max(Number.MAX_SAFE_INTEGER), z.string().regex(/^[1-9]\d*$/)]).describe('Positive numeric asset ID; not a URL or external customer ID');
export function lifecycleTools(server: McpServer, client: KompressrClient, isConfigured: () => boolean): void {
  server.tool('wait_for_asset', 'Wait within a bounded time budget for an active upload to process. A timeout preserves the asset ID; resume rather than reupload. Private uploads need generate_private_url after readiness.', {
    asset_id: id, timeout_ms: z.number().int().min(1).max(120_000).optional().default(120_000),
  }, readAnnotations, async ({ asset_id, timeout_ms }, context) => {
    if (!isConfigured()) return { isError: true, content: [{ type: 'text' as const, text: NOT_CONFIGURED }] };
    try { const response = await client.waitUntilReady(asset_id, timeout_ms, context.signal); return result({ ...response.data, ready: true }, 'Processing complete. Use the public delivery URL, or generate a fresh private link after verifying access.'); }
    catch (error) { return failure(error); }
  });
  server.tool('get_asset_deletion_status', 'Inspect processing/deletion state and storage credits for an asset ID. File removal completion does not certify that all caches have cleared.', { asset_id: id }, readAnnotations, async ({ asset_id }) => {
    if (!isConfigured()) return { isError: true, content: [{ type: 'text' as const, text: NOT_CONFIGURED }] };
    try { const state = await client.getAssetDeletionStatus(asset_id); return result({ ...state }, `Deletion status: ${state.deletion_status}. Cached copies may remain until cache invalidation completes.`); }
    catch (error) { return failure(error); }
  });
  const destructive = { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: true };
  server.tool('delete_asset', 'Permanently delete one explicit asset ID. Irreversible; no restore or cancellation. Scoped keys need explicit delete permission. Acceptance starts background cleanup; cached/offline copies may remain.', { asset_id: id }, destructive, async ({ asset_id }) => {
    if (!isConfigured()) return { isError: true, content: [{ type: 'text' as const, text: NOT_CONFIGURED }] };
    try { const state = await client.deleteAsset(asset_id); return result({ ...state }, `Permanent deletion ${state.deletion_status === 'deleted' ? 'completed file removal' : 'accepted'}. Use get_asset_deletion_status for progress; caches may remain.`); }
    catch (error) { return failure(error); }
  });
  server.tool('bulk_delete_assets', 'Permanently delete 1–100 explicit asset IDs. Inspect each result: a successful HTTP request can contain failed items. Scoped keys require delete permission. No query-based deletion or undo.', {
    asset_ids: z.array(z.number().int().positive().max(Number.MAX_SAFE_INTEGER)).min(1).max(100),
  }, destructive, async ({ asset_ids }) => {
    if (!isConfigured()) return { isError: true, content: [{ type: 'text' as const, text: NOT_CONFIGURED }] };
    try { const response = await client.bulkDeleteAssets(asset_ids); return result({ ...response }, `${response.counts.accepted} accepted; ${response.counts.failed} failed. Inspect each result and retry only selected unsuccessful IDs. Cached copies may remain.`); }
    catch (error) { return failure(error); }
  });
}
