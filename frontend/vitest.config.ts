/** Run feature components in an isolated DOM, not browser journey specs. */
import { defineConfig } from 'vitest/config';
export default defineConfig({ esbuild: { jsx: 'automatic' }, test: { environment: 'jsdom', globals: true,
  setupFiles: ['./src/test/setup.ts'], include: ['src/**/*.test.tsx'], maxWorkers: 1 } });
