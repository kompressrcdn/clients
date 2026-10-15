import { readFileSync } from 'node:fs';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import type { KompressrClient } from './client.js';
import { registerTool } from './tools/register.js';
import { verifyEmailTool } from './tools/verify.js';
import { uploadAssetTool } from './tools/upload.js';
import { getAssetStatusTool } from './tools/status.js';
import { listAssetsTool } from './tools/list.js';
import { generatePrivateUrlTool } from './tools/private-url.js';
import { lifecycleTools } from './tools/lifecycle.js';

export function createServer(client: KompressrClient): McpServer {
  const { version } = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  const server = new McpServer({ name: 'kompressr', version });
  const configured = () => client.isConfigured();
  registerTool(server, client);
  verifyEmailTool(server, client, client.apiUrl);
  uploadAssetTool(server, client, configured); getAssetStatusTool(server, client, configured);
  listAssetsTool(server, client, configured); generatePrivateUrlTool(server, client, configured);
  lifecycleTools(server, client, configured);
  return server;
}
