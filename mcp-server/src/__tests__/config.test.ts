import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

let directory: string;
const variables = ['KOMPRESSR_API_KEY', 'KOMPRESSR_PROJECT_ID', 'KOMPRESSR_API_URL', 'KOMPRESSR_UPLOAD_BASE_URL'];
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), 'kompressr-config-test-'));
  for (const key of variables) vi.stubEnv(key, undefined);
  vi.resetModules(); vi.doMock('node:os', () => ({ homedir: () => directory }));
});
afterEach(() => { vi.unstubAllEnvs(); vi.doUnmock('node:os'); vi.resetModules(); rmSync(directory, { recursive: true, force: true }); });
function saved(value: unknown) {
  mkdirSync(join(directory, '.kompressr'), { recursive: true });
  writeFileSync(join(directory, '.kompressr/config.json'), typeof value === 'string' ? value : JSON.stringify(value));
}

describe('isolated credential configuration', () => {
  it('accepts key-only configuration with the production pair', async () => {
    vi.stubEnv('KOMPRESSR_API_KEY', 'fixture');
    const { loadConfig } = await import('../config.js');
    expect(loadConfig()).toEqual({ api_key: 'fixture', project_id: undefined, api_url: 'https://kompressr.com', upload_url: 'https://uploads.kompressr.com' });
  });
  it('uses a custom origin and honors a distinct upload override', async () => {
    vi.stubEnv('KOMPRESSR_API_KEY', 'fixture'); vi.stubEnv('KOMPRESSR_API_URL', 'https://management.example.test');
    const { loadConfig } = await import('../config.js');
    expect(loadConfig()?.upload_url).toBe('https://management.example.test');
    vi.stubEnv('KOMPRESSR_UPLOAD_BASE_URL', 'http://127.0.0.1:4000');
    expect(loadConfig()?.upload_url).toBe('http://127.0.0.1:4000');
  });
  it('migrates the obsolete saved API subdomain without rewriting the credential', async () => {
    saved({ api_key: 'old-key', project_id: 'project', api_url: 'https://api.kompressr.com' });
    const { loadConfig } = await import('../config.js');
    expect(loadConfig()).toMatchObject({ api_key: 'old-key', api_url: 'https://kompressr.com', upload_url: 'https://uploads.kompressr.com' });
  });
  it('does not combine a new runtime key with the saved project or custom origin', async () => {
    saved({ api_key: 'saved', project_id: 'old-project', api_url: 'https://old.example', upload_url: 'https://old-upload.example' });
    vi.stubEnv('KOMPRESSR_API_KEY', 'new-key');
    const { loadConfig } = await import('../config.js');
    expect(loadConfig()).toMatchObject({ api_key: 'new-key', project_id: undefined, api_url: 'https://kompressr.com', upload_url: 'https://uploads.kompressr.com' });
  });
  it('inherits a saved project for the same key but resets uploads when API origin changes', async () => {
    saved({ api_key: 'saved', project_id: 'old-project', api_url: 'https://old.example', upload_url: 'https://old-upload.example' });
    vi.stubEnv('KOMPRESSR_API_KEY', 'saved'); vi.stubEnv('KOMPRESSR_API_URL', 'https://management.example.test');
    const { loadConfig } = await import('../config.js');
    expect(loadConfig()).toMatchObject({ project_id: 'old-project', upload_url: 'https://management.example.test' });
  });
  it.each(['not-json', { api_url: 'https://example.com' }, { api_key: 'saved', api_url: 'https://secret@example.com' }])('ignores malformed saved configuration', async value => {
    saved(value); const { loadConfig } = await import('../config.js'); expect(loadConfig()).toBeNull();
  });
  it('atomically replaces credentials with restricted file and directory permissions', async () => {
    const { saveConfig, loadConfig, getConfigPath } = await import('../config.js');
    saveConfig({ api_key: 'old-key', api_url: 'https://kompressr.com' });
    saveConfig({ api_key: 'new-key', api_url: 'https://management.example.test' });
    expect(loadConfig()?.api_key).toBe('new-key');
    expect(statSync(getConfigPath()).mode & 0o777).toBe(0o600);
    expect(statSync(join(directory, '.kompressr')).mode & 0o777).toBe(0o700);
    expect(readFileSync(getConfigPath(), 'utf8')).not.toContain('old-key');
  });
});
