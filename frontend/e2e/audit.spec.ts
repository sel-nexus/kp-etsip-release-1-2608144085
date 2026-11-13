/** Verify the auditor journey against live HTTP, downloaded CSV and persisted Mongo evidence. */
import { readFile } from 'node:fs/promises';
import { test, expect } from './fixtures';
import type { AuditRow, Page } from '../src/types';

/** Parse quoted CSV independently, including escaped quotes and embedded line breaks. */
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { cell += '"'; i += 1; }
      else quoted = !quoted;
    } else if (char === ',' && !quoted) { row.push(cell); cell = ''; }
    else if (char === '\n' && !quoted) { row.push(cell); rows.push(row); row = []; cell = ''; }
    else if (char !== '\r' || quoted) cell += char;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

test.describe('Auditor history', () => {
  test.use({ identityOptions: { role: 'Auditor', mustChangePassword: false }, expectedHttpErrors: [401,400] });
  for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
    test(`persisted login/edit review and filtered CSV at ${viewport.width}px`, async ({ page, identity, browserErrors }) => {
      await page.setViewportSize(viewport);
      await page.goto('/audit'); // sole entry; in-app transitions below use visible controls
      await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
      await page.getByLabel('Email').fill(identity.email);
      await page.getByLabel('Password', { exact: true }).fill(identity.password);
      const loginResponse = page.waitForResponse((response) => response.url().endsWith('/api/auth/login'));
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      const login = await loginResponse;
      expect(login.status()).toBe(200);
      const session = await login.json();
      expect(session.user.id).toBe(identity.id);
      await page.getByRole('link', { name: 'My profile', exact: true }).click();
      await page.getByLabel('Default landing page').selectOption('audit');
      const preferenceResponse = page.waitForResponse((response) => response.url().endsWith('/api/auth/preferences'));
      await page.getByRole('button', { name: 'Save preference' }).click();
      expect((await preferenceResponse).status()).toBe(200);
      await expect(page.getByText('Preference saved', { exact: true })).toBeVisible();
      const historyResponse = page.waitForResponse((response) => response.url().includes('/api/audit-logs'));
      await page.getByRole('link', { name: 'Audit history', exact: true }).click();
      expect((await historyResponse).status()).toBe(200);
      await page.getByLabel('User ID', { exact: true }).fill(identity.id);
      const from = new Date(Date.now() - 60 * 60 * 1000).toISOString();
      const to = new Date(Date.now() + 60 * 60 * 1000).toISOString();
      await page.getByLabel('From (UTC or offset)').fill(from);
      await page.getByLabel('To (UTC or offset)').fill(to);
      await page.getByLabel('Rows per page').selectOption('10');
      const filteredResponse = page.waitForResponse((response) => response.url().includes('/api/audit-logs'));
      await page.getByRole('button', { name: 'Apply filters' }).click();
      const filtered = await filteredResponse;
      expect(filtered.status()).toBe(200);
      const all: Page<AuditRow> = await filtered.json();
      expect(all.items.some((row) => row.action === 'login' && row.details === 'Sign-in succeeded')).toBe(true);
      expect(all.items.some((row) => row.action === 'edit' && row.details === 'Updated landing preference')).toBe(true);
      await expect(page.getByRole('table')).toContainText('Sign-in succeeded');
      await expect(page.getByRole('table')).toContainText('Updated landing preference');
      await page.getByLabel('Action', { exact: true }).selectOption('edit');
      const narrowedResponse = page.waitForResponse((response) => response.url().includes('/api/audit-logs'));
      await page.getByRole('button', { name: 'Apply filters' }).click();
      const narrowed = await narrowedResponse;
      expect(narrowed.status()).toBe(200);
      const result: Page<AuditRow> = await narrowed.json();
      expect(result.total).toBe(1);
      expect(result.items[0].userId).toBe(identity.id);
      const url = new URL(page.url());
      expect(url.searchParams.get('userId')).toBe(identity.id);
      expect(url.searchParams.get('action')).toBe('edit');
      expect(url.searchParams.get('from')).toBe(from);
      expect(url.searchParams.get('to')).toBe(to);
      const downloadEvent = page.waitForEvent('download');
      const csvResponse = page.waitForResponse((response) => response.url().includes('/api/audit-logs') && response.url().includes('format=csv'));
      await page.getByRole('button', { name: 'Export CSV' }).click();
      const exported = await csvResponse;
      expect(exported.status()).toBe(200);
      const download = await downloadEvent;
      expect(download.suggestedFilename()).toBe('audit-history.csv');
      const target = test.info().outputPath('audit-history.csv');
      await download.saveAs(target);
      const csv = parseCsv(await readFile(target, 'utf-8'));
      const columns = ['timestamp','userId','userName','action','entityType','entityId','details'] as const;
      expect(csv[0]).toEqual(columns);
      expect(csv.slice(1)).toEqual(result.items.map((row) => columns.map((key) => {
        const value = row[key] ?? '';
        return /^[=+\-@]/.test(value) ? `'${value}` : value;
      })));
      await identity.verifyAudit(all.items, result.total);
      await expect(page.getByText('CSV download started')).toBeVisible();
      await page.getByRole('link', { name: 'My profile', exact: true }).click();
      await page.getByRole('link', { name: 'Audit history', exact: true }).click();
      await page.getByLabel('User ID', { exact: true }).fill(identity.id);
      await page.getByLabel('Action', { exact: true }).selectOption('delete');
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await expect(page.getByText('No audit events match these filters.')).toBeVisible();
      await page.getByLabel('From (UTC or offset)').fill('2026-01-01T00:00:00');
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await expect(page.getByRole('alert')).toHaveText('Invalid audit filters');
      await page.getByRole('button', { name: 'Clear filters' }).click();
      await expect(page.getByRole('table')).toBeVisible();
      await page.screenshot({ path: test.info().outputPath('audit.png') });
      expect(browserErrors).toEqual([]);
    });
  }
});

for (const role of ['Executive','Portfolio Leader','Engineer','Read Only'] as const) {
  test.describe(`${role} audit denial`, () => {
    test.use({ identityOptions: { role, mustChangePassword: false }, expectedHttpErrors: [401,403] });
    test('hides audit navigation and rejects direct API export after real login', async ({ page, identity, browserErrors }) => {
      await page.goto('/audit');
      await page.getByLabel('Email').fill(identity.email);
      await page.getByLabel('Password', { exact: true }).fill(identity.password);
      const loginResponse = page.waitForResponse((response) => response.url().endsWith('/api/auth/login'));
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      const login = await loginResponse;
      expect(login.status()).toBe(200);
      const session = await login.json();
      await expect(page.getByRole('heading', { name: 'Authenticated session' })).toBeVisible();
      await expect(page.getByRole('link', { name: 'Audit history' })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Export CSV' })).toHaveCount(0);
      for (const suffix of ['', '?format=csv']) {
        const response = await page.request.get(`/api/audit-logs${suffix}`, { headers: { Authorization: `Bearer ${session.token}` } });
        expect(response.status()).toBe(403);
        expect((await response.json()).error.code).toBe('FORBIDDEN');
      }
      expect(browserErrors).toEqual([]);
    });
  });
}
