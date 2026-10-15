import { Readable, Writable } from 'node:stream';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';

/** Close the protocol on EOF/broken pipes so request signals abort transfers. */
export async function serveStdio(server: McpServer, input: Readable = process.stdin, output: Writable = process.stdout): Promise<void> {
  const transport = new StdioServerTransport(input, output);
  let closing = false;
  const stop = () => {
    if (closing) return;
    closing = true;
    void server.close().catch(() => {});
  };
  const detach = () => {
    input.off('end', stop); input.off('close', stop); input.off('error', stop);
    output.off('close', stop); output.off('error', stop);
  };
  input.once('end', stop); input.once('close', stop); input.once('error', stop);
  output.once('close', stop); output.once('error', stop);
  transport.onclose = detach;
  try {
    await server.connect(transport);
    if (input.readableEnded || input.destroyed || output.destroyed) stop();
  } catch (error) {
    detach();
    throw error;
  }
}
