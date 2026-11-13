/** Write-only real browser journeys for scoped executive inventory measures. */
import { MongoClient, ObjectId } from 'mongodb';
import { randomBytes } from 'node:crypto';
import { loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
import { test as base, expect, navigateShell } from './fixtures';
import type { Dashboard } from '../src/types';
const env = loadEnv('development', fileURLToPath(new URL('../', import.meta.url)), '');
interface DashboardInventory {
  ids: string[];
  names: string[];
  area: string;
  verify: (response: Dashboard, filters?: Record<string, string>) => Promise<void>;
  emptyScope: () => Promise<void>;
}
const test = base.extend<{ inventory: DashboardInventory }>({
  inventory: async ({ identity }, use) => {
    const databaseName = process.env.E2E_MONGODB_DB || env.E2E_MONGODB_DB;
    if (!databaseName?.startsWith('etsip_e2e_')) throw new Error('Use a disposable etsip_e2e_ database');
    const mongo = new MongoClient(process.env.E2E_MONGODB_URI || env.E2E_MONGODB_URI);
    await mongo.connect();
    const db = mongo.db(databaseName);
    const ids = [new ObjectId(), new ObjectId(), new ObjectId(), new ObjectId()];
    const area = randomBytes(8).toString('hex');
    const names = ['Payments', 'Claims', 'Empty', 'Hidden'].map((name) => `${name} ${area}`);
    const now = new Date();
    try {
      await db.collection('portfolios').insertMany(ids.map((id, index) => ({ _id: id, name: names[index],
        productArea: 'Different portfolio area', ownerName: 'Browser owner', description: 'Test dashboard',
        status: index === 2 ? 'Archived' : 'Active', createdAt: now, updatedAt: now })));
      await db.collection('applications').insertMany([
        { portfolioId: ids[0], qualityScore: 79, applicationHealthScore: 80, automationCoverage: 50, openCriticalDefects: 3, riskLevel: 'High' },
        { portfolioId: ids[0], qualityScore: 80, applicationHealthScore: 81, automationCoverage: 51, openCriticalDefects: 4, riskLevel: 'Low' },
        { portfolioId: ids[1], qualityScore: 0, applicationHealthScore: 100, automationCoverage: 100, openCriticalDefects: 2, riskLevel: 'Medium' },
        { portfolioId: ids[3], qualityScore: 100, applicationHealthScore: 0, automationCoverage: 0, openCriticalDefects: 99, riskLevel: 'High' },
      ].map((row, index) => ({ ...row, name: `Dashboard app ${index} ${area}`, productArea: area,
        description: 'Browser application', businessOwner: 'Test', technologyOwner: 'Test', etsOwner: 'Test',
        criticality: 'High', tier: 2, lifecycleStatus: 'Active', technologyStack: 'Python', repositoryUrl: null,
        pipelineUrl: null, unitTestCoverage: 0, openDefects: 100, createdAt: now, updatedAt: now })));
      await db.collection('users').updateOne({ _id: new ObjectId(identity.id) }, { $set: { portfolioAccess: ids.slice(0, 3) } });
      await use({ ids: ids.map(String), names, area,
        emptyScope: async () => {
          await db.collection('users').updateOne({ _id: new ObjectId(identity.id) }, { $set: { portfolioAccess: [] } });
        },
        verify: async (response, filters = {}) => {
          // Independently requery persisted facts, then compute expectations without production helpers.
          const user = await db.collection('users').findOne({ _id: new ObjectId(identity.id) });
          const scope = user!.portfolioAccess as ObjectId[];
          const rows = await db.collection('applications').find({ $and: [{ portfolioId: { $in: scope } },
            ...Object.entries(filters).map(([key, value]) => ({ [key]: key === 'portfolioId' ? new ObjectId(value) : value }))] }).toArray();
          const mean = (field: string) => rows.length ? Math.floor(rows.reduce((sum, row) => sum + Number(row[field]), 0) / rows.length + 0.5) : null;
          expect(response.metrics).toEqual({ enterpriseQualityScore: mean('qualityScore'), averageApplicationHealthScore: mean('applicationHealthScore'),
            automationMaturityScore: mean('automationCoverage'), openCriticalDefects: rows.reduce((sum, row) => sum + row.openCriticalDefects, 0),
            applicationsAtRisk: rows.filter((row) => row.riskLevel === 'High').length, totalApplications: rows.length,
            totalPortfolios: await db.collection('portfolios').countDocuments({ _id: { $in: scope } }) });
          const represented = [...new Set(rows.map((row) => String(row.portfolioId)))];
          expect(response.portfolioComparisons).toHaveLength(represented.length);
          for (const comparison of response.portfolioComparisons) {
            const portfolio = await db.collection('portfolios').findOne({ _id: new ObjectId(comparison.portfolioId) });
            const apps = rows.filter((row) => String(row.portfolioId) === comparison.portfolioId);
            expect(comparison.name).toBe(portfolio!.name);
            expect(comparison.qualityScore).toBe(Math.floor(apps.reduce((sum, row) => sum + row.qualityScore, 0) / apps.length + 0.5));
            expect(comparison.applicationsAtRisk).toBe(apps.filter((row) => row.riskLevel === 'High').length);
          }
        },
      });
    } finally {
      await db.collection('applications').deleteMany({ portfolioId: { $in: ids } });
      await db.collection('portfolios').deleteMany({ _id: { $in: ids } });
      await mongo.close();
    }
  },
});
for (const width of [1280, 390]) {
  test.describe(`Dashboard ${width}px`, () => {
    test.use({ expectedHttpErrors: [401, 400] });
    test('filters compares persists URL and shows empty and no-scope states', async ({ page, identity, inventory, browserErrors }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.goto('/dashboard'); // Only entry; subsequent navigation is through visible UI.
      await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
      await page.getByLabel('Email').fill(identity.email);
      await page.getByLabel('Password', { exact: true }).fill(identity.password);
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      const initial = page.waitForResponse((response) => response.url().includes('/api/dashboard/executive'));
      await navigateShell(page, 'Dashboard');
      const initialResponse = await initial;
      expect(initialResponse.status()).toBe(200);
      const initialData: Dashboard = await initialResponse.json();
      await inventory.verify(initialData);
      for (const [key, value] of Object.entries(initialData.metrics)) {
        await expect(page.locator(`[data-metric="${key}"]`)).toHaveText(value === null ? 'Not available' : String(value));
      }
      for (const row of initialData.portfolioComparisons) {
        const rendered = page.getByRole('row', { name: `${row.name} ${row.qualityScore} ${row.applicationsAtRisk}`, exact: true });
        await expect(rendered).toBeVisible();
      }
      await expect(page.getByText(inventory.names[3], { exact: true })).toHaveCount(0);
      await page.getByLabel('Filter portfolio ID').fill(inventory.ids[0]);
      await page.getByLabel('Product area').fill(inventory.area);
      await page.getByLabel('Risk level').selectOption('High');
      const filtering = page.waitForResponse((response) => response.url().includes('/api/dashboard/executive?portfolioId='));
      await page.getByRole('button', { name: 'Apply filters' }).click();
      const filteredResponse = await filtering;
      expect(filteredResponse.status()).toBe(200);
      const filtered: Dashboard = await filteredResponse.json();
      await inventory.verify(filtered, { portfolioId: inventory.ids[0], productArea: inventory.area, riskLevel: 'High' });
      await expect(page).toHaveURL(/riskLevel=High/);
      for (const [key, value] of Object.entries(filtered.metrics)) {
        await expect(page.locator(`[data-metric="${key}"]`)).toHaveText(value === null ? 'Not available' : String(value));
      }
      for (const row of filtered.portfolioComparisons) {
        await expect(page.getByRole('row', {
          name: `${row.name} ${row.qualityScore} ${row.applicationsAtRisk}`, exact: true,
        })).toBeVisible();
      }
      const reload = page.waitForResponse((response) => response.url().includes('/api/dashboard/executive?portfolioId='));
      await page.reload();
      await inventory.verify(await (await reload).json(), {
        portfolioId: inventory.ids[0], productArea: inventory.area, riskLevel: 'High',
      });
      await expect(page.getByLabel('Filter portfolio ID')).toHaveValue(inventory.ids[0]);
      await expect(page.getByLabel('Product area')).toHaveValue(inventory.area);
      await expect(page.getByLabel('Risk level')).toHaveValue('High');
      await navigateShell(page, 'My profile');
      const returned = page.waitForResponse((response) => response.url().includes('/api/dashboard/executive'));
      await navigateShell(page, 'Dashboard');
      await inventory.verify(await (await returned).json());
      await page.getByLabel('Filter portfolio ID').fill(inventory.ids[2]);
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await expect(page.getByText('Not available', { exact: true })).toHaveCount(3);
      await expect(page.locator('[data-metric="totalPortfolios"]')).toHaveText('3');
      await expect(page.getByText('No portfolios to compare.')).toBeVisible();
      await page.getByLabel('Filter portfolio ID').fill('bad');
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await expect(page.getByRole('alert')).toHaveText('Invalid dashboard filters');
      await page.getByRole('button', { name: 'Retry dashboard' }).click();
      await expect(page.getByRole('alert')).toHaveText('Invalid dashboard filters');
      await inventory.emptyScope();
      const noScope = page.waitForResponse((response) => response.url().includes('/api/dashboard/executive?') && !response.url().includes('portfolioId='));
      await page.getByRole('button', { name: 'Clear filters' }).click();
      await inventory.verify(await (await noScope).json());
      await expect(page.locator('[data-metric="totalPortfolios"]')).toHaveText('0');
      await expect(page.getByText('No applications match your filters within your scope.')).toBeVisible();
      await page.screenshot({ path: test.info().outputPath('dashboard.png') });
      expect(browserErrors).toEqual([]);
    });
  });
}
