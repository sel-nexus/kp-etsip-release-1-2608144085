/** Exercise engineer creation/editing and admin deletion with real HTTP and Mongo requery. */
import { MongoClient, ObjectId } from 'mongodb';
import { randomBytes } from 'node:crypto';
import { loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
import { test as base, expect } from './fixtures';
const env = loadEnv('development', fileURLToPath(new URL('../', import.meta.url)), '');
const apiURL = process.env.E2E_API_URL || env.E2E_API_URL;
interface Inventory {
  name: string; parentId: string; parentName: string; hiddenId: string;
  assign: (empty?: boolean) => Promise<void>;
  promote: () => Promise<void>;
  verify: (id: string, quality: number) => Promise<void>;
  verifyDeleted: (id: string) => Promise<void>;
}
const test = base.extend<{ inventory: Inventory }>({
  inventory: async ({ identity }, use) => {
    const databaseName = process.env.E2E_MONGODB_DB || env.E2E_MONGODB_DB;
    if (!databaseName?.startsWith('etsip_e2e_')) throw new Error('Use a disposable etsip_e2e_ database');
    const mongo = new MongoClient(process.env.E2E_MONGODB_URI || env.E2E_MONGODB_URI);
    await mongo.connect();
    const db = mongo.db(databaseName);
    const suffix = randomBytes(8).toString('hex');
    const parentId = new ObjectId(); const hiddenId = new ObjectId(); const now = new Date();
    const name = `Application ${suffix}`; const parentName = `Portfolio ${suffix}`;
    try {
      await db.collection('portfolios').insertMany([parentId, hiddenId].map((id) => ({
        _id: id, name: id.equals(parentId) ? parentName : `Hidden ${suffix}`, description: 'Browser inventory', ownerName: 'Browser owner',
        productArea: suffix, status: 'Active', createdAt: now, updatedAt: now,
      })));
      await db.collection('roles').updateOne({ name: 'Administrator' }, { $setOnInsert: {
        name: 'Administrator', permissions: ['view', 'create', 'edit', 'delete', 'export', 'administer'], description: 'Test administrator', createdAt: now, updatedAt: now,
      } }, { upsert: true });
      await use({
        name, parentId: parentId.toHexString(), parentName, hiddenId: hiddenId.toHexString(),
        assign: async (empty = false) => {
          await db.collection('users').updateOne({ _id: new ObjectId(identity.id) }, { $set: { portfolioAccess: empty ? [] : [parentId] } });
        },
        promote: async () => {
          await db.collection('users').updateOne({ _id: new ObjectId(identity.id) }, { $set: { role: 'Administrator', portfolioAccess: [] } });
        },
        verify: async (id, quality) => {
          const row = await db.collection('applications').findOne({ _id: new ObjectId(id) });
          expect(row?.name).toBe(name); expect(row?.portfolioId).toEqual(parentId); expect(row?.qualityScore).toBe(quality);
          expect(row?.pipelineUrl).toBeNull(); expect(row?.createdAt).toBeInstanceOf(Date);
          expect(await db.collection('audit_logs').countDocuments({ entityId: new ObjectId(id), userId: new ObjectId(identity.id) })).toBeGreaterThan(0);
        },
        verifyDeleted: async (id) => {
          expect(await db.collection('applications').findOne({ _id: new ObjectId(id) })).toBeNull();
          expect(await db.collection('audit_logs').countDocuments({ entityId: new ObjectId(id), action: 'delete' })).toBe(1);
        },
      });
    } finally {
      await db.collection('applications').deleteMany({ portfolioId: { $in: [parentId, hiddenId] } });
      await db.collection('portfolios').deleteMany({ _id: { $in: [parentId, hiddenId] } });
      await mongo.close();
    }
  },
});
for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test.describe(`Application journey ${viewport.width}px`, () => {
    test.use({ expectedHttpErrors: [401, 404, 400] });
    test('creates edits traverses parent links and deletes only as admin', async ({ page, request, identity, inventory, browserErrors }) => {
      await inventory.assign();
      await page.setViewportSize(viewport);
      await page.goto('/applications'); // sole entry, all subsequent navigation uses UI controls
      await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
      await page.getByLabel('Email').fill(identity.email);
      await page.getByLabel('Password', { exact: true }).fill(identity.password);
      const authentication = page.waitForResponse((response) => response.url().endsWith('/api/auth/login'));
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      const authenticated = await authentication; expect(authenticated.status()).toBe(200);
      const login = await authenticated.json();
      await page.getByRole('link', { name: 'Applications', exact: true }).click();
      await page.getByRole('button', { name: 'Create application' }).click();
      const dialog = page.getByRole('dialog');
      await expect(dialog.getByLabel('Name', { exact: true })).toBeFocused();
      await expect(dialog.getByRole('option', { name: inventory.parentName })).toHaveCount(1);
      await page.keyboard.press('Shift+Tab');
      await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
      await dialog.getByRole('button', { name: 'Save application' }).click();
      await expect(dialog.getByLabel('Name', { exact: true })).toHaveAttribute('aria-invalid', 'true');
      for (const [label, value] of Object.entries({ Name: inventory.name, Description: 'Browser application', 'Product area': 'Browser area',
        'Business owner': 'Business', 'Technology owner': 'Technology', 'ETS owner': 'ETS', 'Technology stack': 'Python' })) {
        await dialog.getByLabel(label, { exact: true }).fill(value);
      }
      await dialog.getByLabel('Portfolio', { exact: true }).selectOption(inventory.parentId);
      await dialog.getByLabel('Quality score').fill('101');
      await dialog.getByRole('button', { name: 'Save application' }).click();
      await expect(dialog.getByText('Use an integer from 0 to 100')).toBeVisible();
      await dialog.getByLabel('Quality score').fill('79');
      const creation = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/api/applications'));
      await dialog.getByRole('button', { name: 'Save application' }).click();
      const created = await creation; expect(created.status()).toBe(201); const item = await created.json();
      expect(item.name).toBe(inventory.name); await inventory.verify(item.id, 79);
      await page.getByLabel('Search names').fill(inventory.name);
      const filtered = page.waitForResponse((response) => response.url().includes('/api/applications?search='));
      await page.getByRole('button', { name: 'Apply filters' }).click();
      expect((await filtered).status()).toBe(200);
      await page.getByRole('link', { name: inventory.name, exact: true }).click();
      await expect(page.getByText('Browser application', { exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Delete application' })).toHaveCount(0);
      await page.getByRole('button', { name: 'Edit application' }).click();
      await dialog.getByLabel('Quality score').fill('83');
      const editing = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith(`/api/applications/${item.id}`));
      await dialog.getByRole('button', { name: 'Save application' }).click();
      const edited = await editing; expect(edited.status()).toBe(200);
      expect(edited.request().postDataJSON().expectedUpdatedAt).toBe(item.updatedAt);
      await inventory.verify(item.id, 83);
      await expect(page.getByText('Application updated', { exact: true })).toBeVisible();
      await page.getByRole('link', { name: inventory.parentName, exact: true }).click();
      await expect(page.getByRole('heading', { name: inventory.parentName })).toBeVisible();
      await page.getByRole('link', { name: inventory.name, exact: true }).click();
      await expect(page.getByRole('heading', { name: inventory.name })).toBeVisible();
      const persisted = await request.get(`${apiURL}/api/applications/${item.id}`, { headers: { Authorization: `Bearer ${login.token}` } });
      expect(persisted.status()).toBe(200); expect((await persisted.json()).qualityScore).toBe(83);
      const hidden = await request.put(`${apiURL}/api/applications/${item.id}`, {
        headers: { Authorization: `Bearer ${login.token}` }, data: { portfolioId: inventory.hiddenId },
      });
      expect(hidden.status()).toBe(404); await inventory.verify(item.id, 83);
      await page.getByRole('link', { name: 'Back to applications' }).click();
      await page.getByLabel('Filter portfolio ID').fill('invalid');
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await expect(page.getByRole('alert')).toHaveText('Invalid application filters');
      await page.getByRole('button', { name: 'Clear filters' }).click();
      await inventory.assign(true);
      await page.getByRole('link', { name: 'Session', exact: true }).click();
      await page.getByRole('button', { name: 'Refresh identity' }).click();
      await page.getByRole('link', { name: 'Applications', exact: true }).click();
      await expect(page.getByText('No applications available in your scope.')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Create application' })).toHaveCount(0);
      await inventory.promote();
      await page.getByRole('button', { name: 'Sign out' }).click();
      await page.getByLabel('Email').fill(identity.email);
      await page.getByLabel('Password', { exact: true }).fill(identity.password);
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      await page.getByRole('link', { name: 'Applications', exact: true }).click();
      await page.getByLabel('Search names').fill(inventory.name);
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await page.getByRole('link', { name: inventory.name, exact: true }).click();
      await page.getByRole('button', { name: 'Delete application' }).click();
      const deletion = page.waitForResponse((response) => response.request().method() === 'DELETE');
      await dialog.getByRole('button', { name: 'Confirm delete' }).click();
      const deleted = await deletion; expect(deleted.status()).toBe(200); expect(await deleted.json()).toEqual({ deleted: true, id: item.id });
      await inventory.verifyDeleted(item.id);
      await page.screenshot({ path: test.info().outputPath('applications.png') });
      expect(browserErrors).toEqual([]);
    });
  });
}
