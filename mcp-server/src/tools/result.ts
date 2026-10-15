import { KompressrError } from '@kompressr/sdk';
export const NOT_CONFIGURED = 'Set KOMPRESSR_API_KEY (project or scoped key) or use register and verify_email. API uploads require a paid plan. KOMPRESSR_PROJECT_ID is also required for upload listing.';
export function result(data: Record<string, unknown>, text: string) {
  return { content: [{ type: 'text' as const, text }, { type: 'text' as const, text: JSON.stringify(data) }], structuredContent: data };
}
export function failure(error: unknown) {
  const message = error instanceof KompressrError ? error.message : 'The operation failed. Check your input, configuration and connection.';
  const details = error instanceof KompressrError ? error.toJSON() : { code: 'REQUEST_FAILED', message };
  return { ...result(details, message), isError: true };
}
export const readAnnotations = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true };
