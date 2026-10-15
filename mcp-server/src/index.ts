#!/usr/bin/env node
import { serveStdio } from "./stdio.js";
import { loadConfig } from "./config.js";
import { KompressrClient } from "./client.js";
import { createServer } from "./server.js";

const config = loadConfig();
const client = new KompressrClient(
  config?.api_url ?? process.env.KOMPRESSR_API_URL ?? "https://kompressr.com",
  config?.api_key, config?.project_id,
  config?.upload_url ?? process.env.KOMPRESSR_UPLOAD_BASE_URL,
);
await serveStdio(createServer(client));
