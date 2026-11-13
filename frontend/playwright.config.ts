/** Keep browser tests tier-local, single-worker, and backed by live HTTP servers. */
import { defineConfig } from '@playwright/test';
import { loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('.', import.meta.url));
const env = loadEnv('development', root, '');
const baseURL = process.env.E2E_BASE_URL || env.E2E_BASE_URL;
const apiURL = process.env.E2E_API_URL || env.E2E_API_URL;
export default defineConfig({ testDir: './e2e', workers: 1, fullyParallel: false,
  use: { baseURL, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: [
    { command: 'cd ../backend && "$HOME/venvs/app/bin/python" -m uvicorn api.main:app --host 127.0.0.1 --port 8000',
      cwd: root, url: `${apiURL}/api/health`, reuseExistingServer: false, env: { MONGODB_DB: process.env.E2E_MONGODB_DB || env.E2E_MONGODB_DB, MONGODB_URI: process.env.E2E_MONGODB_URI || env.E2E_MONGODB_URI, SEED_ON_STARTUP: 'false' } },
    { command: 'node node_modules/vite/bin/vite.js', cwd: root, url: baseURL, reuseExistingServer: true },
  ],
});
