import { z } from 'zod';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import type { KompressrClient } from '../client.js';
import { KompressrClient as SDK, KompressrError } from '@kompressr/sdk';
import { saveConfig, getConfigPath } from '../config.js';
import { failure, result } from './result.js';

export function verifyEmailTool(server: McpServer, client: KompressrClient, apiUrl: string, onConfigured?: () => void): void {
  let verifying = false;
  server.tool('verify_email', 'Verify an email token and save credentials locally. Refuses to replace an already configured runtime.', {
    token: z.string().min(1),
  }, { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true }, async ({ token }) => {
    if (client.isConfigured() || verifying) return failure(new KompressrError('Credentials are already configured. Use a separate MCP configuration for account setup.', { kind: 'validation', code: 'ALREADY_CONFIGURED' }));
    verifying = true;
    try {
      const response = await client.verifyEmail(token);
      if (!response.success) return failure(new KompressrError('Email verification failed. Check the token or sign in at Kompressr.', { kind: 'api', code: 'VERIFICATION_FAILED' }));
      if (!response.api_key || !response.project_id) return result({ verified: true, configured: false }, 'Email verified, but no project key was issued. Sign in to your Kompressr dashboard to configure a project key. The 30-day free trial includes 100 image uploads total, shared across API, SDKs, MCP and dashboard. This allowance does not renew monthly.');
      // Validate before persistence. A save failure does not leave a configured runtime.
      new SDK({ apiKey: response.api_key, projectId: response.project_id, apiBaseUrl: apiUrl, uploadBaseUrl: client.uploadUrl });
      saveConfig({ api_key: response.api_key, project_id: response.project_id, api_url: apiUrl, upload_url: client.uploadUrl });
      client.setCredentials(response.api_key, response.project_id); onConfigured?.();
      return result({ verified: true, configured: true }, `Email verified. Credentials saved to ${getConfigPath()}. The 30-day free trial includes 100 image uploads total, shared across API, SDKs, MCP and dashboard. This allowance does not renew monthly.`);
    } catch (error) { return failure(error); }
    finally { verifying = false; }
  });
}
