/** Verify real portfolio UI journeys, HTTP contracts, scope and Mongo persistence without mocks. */
import { randomBytes } from 'node:crypto';
import { MongoClient, ObjectId } from 'mongodb';
import { loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
import type { Page as BrowserPage } from '@playwright/test';
import { test as base, expect } from './fixtures';
const env = loadEnv('development', fileURLToPath(new URL('../', import.meta.url)), '');
const apiURL = process.env.E2E_API_URL || env.E2E_API_URL;
interface JourneyData {
  name: string;
  assignedId: string;
  hiddenId: string;
  assignedName: string;
  hiddenName: string;
  appName: string;
  verify: (id: string, name: string, status: string) => Promise<void>;
  verifyDeleted: (id: string) => Promise<void>;
  assign: () => Promise<void>;
}
const test = base.extend<{ portfolioData: JourneyData }>({
  portfolioData: async ({ identity }, use) => {
    const databaseName = process.env.E2E_MONGODB_DB || env.E2E_MONGODB_DB;
    if (!databaseName?.startsWith('etsip_e2e_')) throw new Error('Use a disposable etsip_e2e_ database');
    const mongo = new MongoClient(process.env.E2E_MONGODB_URI || env.E2E_MONGODB_URI);
    await mongo.connect();
    const db = mongo.db(databaseName);
    const suffix = randomBytes(8).toString('hex');
    const name = `Journey ${suffix}`;
    const assignedId = new ObjectId();
    const hiddenId = new ObjectId();
    const appId = new ObjectId();
    const now = new Date();
    const assignedName = `Assigned ${suffix}`;
    const hiddenName = `Hidden ${suffix}`;
    const appName = `Related ${suffix}`;
    try {
      await db.collection('portfolios').insertMany([
        { _id: assignedId, name: assignedName, ownerName: 'Test owner', description: 'Assigned services', productArea: suffix,
          status: 'Active', createdAt: now, updatedAt: now },
        { _id: hiddenId, name: hiddenName, ownerName: 'Hidden owner', description: 'Hidden services', productArea: suffix,
          status: 'Active', createdAt: now, updatedAt: now },
      ]);
      await db.collection('applications').insertOne({
        _id: appId, name: appName, description: 'Browser fixture app', portfolioId: assignedId, productArea: suffix,
        businessOwner: 'Test owner', technologyOwner: 'Test owner', etsOwner: 'Test owner', criticality: 'High', tier: 2,
        lifecycleStatus: 'Active', technologyStack: 'Python', repositoryUrl: null, pipelineUrl: null,
        applicationHealthScore: 80, qualityScore: 81, automationCoverage: 70, unitTestCoverage: 75,
        openDefects: 2, openCriticalDefects: 1, riskLevel: 'Low', createdAt: now, updatedAt: now,
      });
      await use({
        name, assignedId: assignedId.toHexString(), hiddenId: hiddenId.toHexString(), assignedName, hiddenName, appName,
        verify: async (id, expectedName, status) => {
          const row = await db.collection('portfolios').findOne({ _id: new ObjectId(id) });
          expect(row?.name).toBe(expectedName);
          expect(row?.status).toBe(status);
          expect(row?.createdAt).toBeInstanceOf(Date);
          expect(row?.updatedAt).toBeInstanceOf(Date);
          expect(row?.qualityScore).toBeUndefined();
          expect(row?.applicationCount).toBeUndefined();
          expect(await db.collection('audit_logs').countDocuments({ entityId: new ObjectId(id), userId: new ObjectId(identity.id) }))
            .toBeGreaterThan(0);
        },
        verifyDeleted: async (id) => {
          expect(await db.collection('portfolios').findOne({ _id: new ObjectId(id) })).toBeNull();
          expect(await db.collection('audit_logs').countDocuments({ entityId: new ObjectId(id), action: 'delete' })).toBe(1);
        },
        assign: async () => {
          await db.collection('users').updateOne({ _id: new ObjectId(identity.id) }, { $set: { portfolioAccess: [assignedId] } });
        },
      });
    } finally {
      await db.collection('applications').deleteOne({ _id: appId });
      await db.collection('portfolios').deleteMany({ $or: [{ _id: { $in: [assignedId, hiddenId] } }, { name: { $in: [name, `${name} edited`] } }] });
      await mongo.close();
    }
  },
});
/** Enter once and then sign in through the displayed credential form. */
async function signIn(page: BrowserPage, email: string, password: string) {
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  const response = page.waitForResponse((result) => result.url().endsWith('/api/auth/login'));
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const login = await response;
  expect(login.status()).toBe(200);
  return login.json();
}
for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test.describe(`Administrator portfolio journey ${viewport.width}px`, () => {
    test.use({ identityOptions: { role: 'Administrator', mustChangePassword: false }, expectedHttpErrors: [401, 409] });
    test('creates edits filters reviews and safely deletes persisted portfolios', async ({ page, identity, portfolioData, browserErrors }) => {
      await page.setViewportSize(viewport);
      await page.goto('/portfolios'); // sole entry; all later route changes click visible links
      await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
      await signIn(page, identity.email, identity.password);
      const listResponse = page.waitForResponse((response) => response.url().includes('/api/portfolios?'));
      await page.getByRole('link', { name: 'Portfolios', exact: true }).click();
      const listed = await listResponse;
      expect(listed.status()).toBe(200);
      expect((await listed.json()).total).toBeGreaterThanOrEqual(2);
      const trigger = page.getByRole('button', { name: 'Create portfolio', exact: true });
      await trigger.click();
      const dialog = page.getByRole('dialog');
      await expect(page.getByLabel('Name', { exact: true })).toBeFocused();
      await page.keyboard.press('Shift+Tab');
      await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
      await page.keyboard.press('Escape');
      await expect(trigger).toBeFocused();
      await trigger.click();
      await dialog.getByRole('button', { name: 'Save portfolio' }).click();
      await expect(dialog.getByText('This field is required')).toHaveCount(4);
      await page.getByLabel('Name', { exact: true }).fill(portfolioData.name);
      await page.getByLabel('Owner name').fill('Browser owner');
      await page.getByLabel('Product area', { exact: true }).fill('Browser area');
      await page.getByLabel('Description').fill('Persisted browser portfolio');
      const creation = page.waitForResponse((response) => response.url().endsWith('/api/portfolios') && response.request().method() === 'POST');
      await dialog.getByRole('button', { name: 'Save portfolio' }).click();
      const created = await creation;
      expect(created.status()).toBe(201);
      const item = await created.json();
      expect(item.name).toBe(portfolioData.name);
      expect(item.applicationCount).toBe(0);
      expect(item.qualityScore).toBeNull();
      await expect(page.getByText('Portfolio created', { exact: true })).toBeVisible();
      await portfolioData.verify(item.id, portfolioData.name, 'Active');
      await page.getByLabel('Search names').fill(portfolioData.name);
      await page.getByLabel('Filter status').selectOption('Active');
      await page.getByLabel('Filter product area').fill('Browser area');
      const filter = page.waitForResponse((response) => response.url().includes('/api/portfolios?search='));
      await page.getByRole('button', { name: 'Apply filters' }).click();
      const filtered = await filter;
      expect(filtered.status()).toBe(200);
      expect((await filtered.json()).total).toBe(1);
      await expect(page).toHaveURL(/status=Active/);
      await page.getByRole('button', { name: `Edit ${portfolioData.name}`, exact: true }).click();
      await page.getByLabel('Name', { exact: true }).fill(`${portfolioData.name} edited`);
      await page.getByLabel('Status', { exact: true }).selectOption('Archived');
      const edit = page.waitForResponse((response) => response.url().endsWith(`/api/portfolios/${item.id}`) && response.request().method() === 'PUT');
      await dialog.getByRole('button', { name: 'Save portfolio' }).click();
      const edited = await edit;
      expect(edited.status()).toBe(200);
      expect((await edited.json()).status).toBe('Archived');
      expect(edited.request().postDataJSON().expectedUpdatedAt).toBe(item.updatedAt);
      await expect(page.getByText('Portfolio updated', { exact: true })).toBeVisible();
      await expect(page.getByText('No portfolios match these filters.')).toBeVisible();
      await portfolioData.verify(item.id, `${portfolioData.name} edited`, 'Archived');
      await page.getByLabel('Filter status').selectOption('Archived');
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await page.getByRole('link', { name: `${portfolioData.name} edited`, exact: true }).click();
      await expect(page.getByRole('heading', { name: `${portfolioData.name} edited` })).toBeVisible();
      await expect(page.getByText('Persisted browser portfolio', { exact: true })).toBeVisible();
      await expect(page.getByText('No related applications on this page.')).toBeVisible();
      await page.getByRole('link', { name: 'Back to portfolios' }).click();
      await page.getByLabel('Search names').fill(portfolioData.assignedName);
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await page.getByRole('link', { name: portfolioData.assignedName, exact: true }).click();
      await expect(page.getByText(portfolioData.appName, { exact: true })).toBeVisible();
      await expect(page.getByRole('link', { name: portfolioData.appName })).toHaveCount(0);
      await page.getByRole('link', { name: 'Back to portfolios' }).click();
      await page.getByLabel('Search names').fill(portfolioData.assignedName);
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await page.getByRole('button', { name: `Delete ${portfolioData.assignedName}`, exact: true }).click();
      const reference = page.waitForResponse((response) => response.request().method() === 'DELETE');
      await dialog.getByRole('button', { name: 'Confirm delete' }).click();
      const rejected = await reference;
      expect(rejected.status()).toBe(409);
      expect((await rejected.json()).error.code).toBe('CONFLICT');
      await expect(dialog.getByRole('alert')).toContainText('referenced');
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await page.getByLabel('Search names').fill(`${portfolioData.name} edited`);
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await page.getByRole('button', { name: `Delete ${portfolioData.name} edited`, exact: true }).click();
      const deletion = page.waitForResponse((response) => response.request().method() === 'DELETE');
      await dialog.getByRole('button', { name: 'Confirm delete' }).click();
      const deleted = await deletion;
      expect(deleted.status()).toBe(200);
      expect(await deleted.json()).toEqual({ deleted: true, id: item.id });
      await expect(page.getByText('Portfolio deleted', { exact: true })).toBeVisible();
      await portfolioData.verifyDeleted(item.id);
      await page.screenshot({ path: test.info().outputPath('portfolios.png') });
      expect(browserErrors).toEqual([]);
    });
  });
  test.describe(`Engineer portfolio scope journey ${viewport.width}px`, () => {
    test.use({ identityOptions: { role: 'Engineer', mustChangePassword: false }, expectedHttpErrors: [401, 404] });
    test('moves from empty scope to assigned browse and rejects guessed IDs over real HTTP', async ({ page, request, identity, portfolioData, browserErrors }) => {
      await page.setViewportSize(viewport);
      await page.goto('/portfolios');
      const login = await signIn(page, identity.email, identity.password);
      await page.getByRole('link', { name: 'Portfolios', exact: true }).click();
      await expect(page.getByText('No portfolios available in your scope.')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Create portfolio' })).toHaveCount(0);
      await portfolioData.assign();
      await page.getByRole('link', { name: 'Session', exact: true }).click();
      const scoped = page.waitForResponse((response) => response.url().includes('/api/portfolios?'));
      await page.getByRole('link', { name: 'Portfolios', exact: true }).click();
      const listed = await scoped;
      expect(listed.status()).toBe(200);
      const body = await listed.json();
      expect(body.total).toBe(1);
      expect(body.items[0].id).toBe(portfolioData.assignedId);
      expect(body.items[0].qualityScore).toBe(81);
      await expect(page.getByRole('link', { name: portfolioData.hiddenName })).toHaveCount(0);
      await page.getByRole('link', { name: portfolioData.assignedName, exact: true }).click();
      await expect(page.getByText(portfolioData.appName, { exact: true })).toBeVisible();
      for (const suffix of ['', '/applications']) {
        const denied = await request.get(`${apiURL}/api/portfolios/${portfolioData.hiddenId}${suffix}`, {
          headers: { Authorization: `Bearer ${login.token}` },
        });
        expect(denied.status()).toBe(404);
        expect((await denied.json()).error.code).toBe('NOT_FOUND');
      }
      await page.getByRole('link', { name: 'Back to portfolios' }).click();
      await page.getByRole('link', { name: 'My profile', exact: true }).click();
      await page.getByLabel('Default landing page').selectOption('portfolios');
      const preference = page.waitForResponse((response) => response.url().endsWith('/api/auth/preferences'));
      await page.getByRole('button', { name: 'Save preference' }).click();
      expect((await preference).status()).toBe(200);
      await expect(page.getByText('Preference saved', { exact: true })).toBeVisible();
      await page.getByRole('button', { name: 'Sign out' }).click();
      await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
      await signIn(page, identity.email, identity.password);
      await expect(page.getByRole('heading', { name: 'Portfolios' })).toBeVisible();
      await expect(page.getByRole('link', { name: portfolioData.assignedName, exact: true })).toBeVisible();
      await page.screenshot({ path: test.info().outputPath('portfolios.png') });
      expect(browserErrors).toEqual([]);
    });
  });
}
