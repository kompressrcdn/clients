import { z } from 'zod';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import type { KompressrClient } from '../client.js';
import { KompressrError } from '@kompressr/sdk';
import { failure, result } from './result.js';

export function registerTool(server: McpServer, client: KompressrClient): void {
  server.tool('register', 'Create an account and send a verification email. API uploads require a paid plan. Cannot replace an already configured runtime.', {
    email: z.email(), password: z.string().min(8),
  }, { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true }, async ({ email, password }) => {
    if (client.isConfigured()) return failure(new KompressrError('Credentials are already configured. Use a separate MCP configuration for account setup.', { kind: 'validation', code: 'ALREADY_CONFIGURED' }));
    try {
      const response = await client.register(email, password);
      if (!response.success) return failure(new KompressrError('Account registration failed. Check your input or sign in at Kompressr.', { kind: 'api', code: 'REGISTRATION_FAILED' }));
      return result({ success: true, next_step: 'verify_email' }, 'Account created. Check your inbox and call verify_email with the token from the verification link. API uploads require a paid plan.');
    } catch (error) { return failure(error); }
  });
}
