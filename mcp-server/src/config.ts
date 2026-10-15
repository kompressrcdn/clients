import { readFileSync, writeFileSync, mkdirSync, existsSync, chmodSync, renameSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';
import { resolveEndpoints } from '@kompressr/sdk';

export interface KompressrConfig { api_key: string; project_id?: string; api_url: string; upload_url?: string }
const CONFIG_DIR = join(homedir(), '.kompressr');
const CONFIG_FILE = join(CONFIG_DIR, 'config.json');
function normalize(value: KompressrConfig): KompressrConfig {
  const apiBaseUrl = value.api_url === 'https://api.kompressr.com' ? 'https://kompressr.com' : value.api_url;
  const endpoints = resolveEndpoints({ apiBaseUrl, uploadBaseUrl: value.upload_url });
  return { api_key: value.api_key, project_id: value.project_id, api_url: endpoints.apiBaseUrl, upload_url: endpoints.uploadBaseUrl };
}
export function loadConfig(): KompressrConfig | null {
  let saved: KompressrConfig | undefined;
  if (existsSync(CONFIG_FILE)) {
    try {
      const value = JSON.parse(readFileSync(CONFIG_FILE, 'utf8'));
      if (value && typeof value.api_key === 'string' && value.api_key.trim()) saved = normalize(value);
    } catch { /* Do not expose malformed saved configuration or credentials. */ }
  }
  const envKey = process.env.KOMPRESSR_API_KEY;
  if (envKey) {
    const sameCredential = saved?.api_key === envKey;
    return normalize({ api_key: envKey,
      project_id: process.env.KOMPRESSR_PROJECT_ID ?? (sameCredential ? saved?.project_id : undefined),
      api_url: process.env.KOMPRESSR_API_URL ?? (sameCredential ? saved?.api_url : undefined) ?? 'https://kompressr.com',
      upload_url: process.env.KOMPRESSR_UPLOAD_BASE_URL ?? (sameCredential && !process.env.KOMPRESSR_API_URL ? saved?.upload_url : undefined),
    });
  }
  if (!saved) return null;
  return normalize({ ...saved, project_id: process.env.KOMPRESSR_PROJECT_ID ?? saved.project_id,
    api_url: process.env.KOMPRESSR_API_URL ?? saved.api_url,
    upload_url: process.env.KOMPRESSR_UPLOAD_BASE_URL ?? (process.env.KOMPRESSR_API_URL ? undefined : saved.upload_url),
  });
}
export function saveConfig(config: KompressrConfig): void {
  const normalized = normalize(config);
  mkdirSync(CONFIG_DIR, { recursive: true, mode: 0o700 }); chmodSync(CONFIG_DIR, 0o700);
  const temporary = join(CONFIG_DIR, `.config-${process.pid}-${crypto.randomUUID()}.tmp`);
  try { writeFileSync(temporary, JSON.stringify(normalized, null, 2) + '\n', { mode: 0o600, flag: 'wx' }); renameSync(temporary, CONFIG_FILE); chmodSync(CONFIG_FILE, 0o600); }
  finally { rmSync(temporary, { force: true }); }
}
export function getConfigPath(): string { return CONFIG_FILE; }
