/** Exercise account creation, assignment, editing and deactivation with real HTTP/Mongo. */
import { MongoClient, ObjectId } from 'mongodb';
import { compare } from 'bcryptjs';
import { randomBytes } from 'node:crypto';
import { loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
import { test as base, expect, navigateShell, signOutShell } from './fixtures';
const env = loadEnv('development', fileURLToPath(new URL('../', import.meta.url)), '');
const apiURL = process.env.E2E_API_URL || env.E2E_API_URL;
interface Accounts {
  email: string; password: string; name: string; parent: string; parentName: string;
  verify: (id: string, role: string, status: string, manager?: string | null, edits?: number, deactivations?: number) => Promise<void>;
}
const test = base.extend<{ accounts: Accounts }>({
  accounts: async ({ identity }, use) => {
    const databaseName = process.env.E2E_MONGODB_DB || env.E2E_MONGODB_DB;
    if (!databaseName?.startsWith('etsip_e2e_')) throw new Error('Use a disposable etsip_e2e_ database');
    const mongo = new MongoClient(process.env.E2E_MONGODB_URI || env.E2E_MONGODB_URI);
    await mongo.connect();
    const db = mongo.db(databaseName);
    const suffix = randomBytes(8).toString('hex');
    const parent = new ObjectId(); const now = new Date();
    const name = `User ${suffix}`; const email = `user-${suffix}@example.com`; const password = randomBytes(24).toString('base64url');
    const parentName = `Portfolio ${suffix}`;
    try {
      await db.collection('portfolios').insertOne({ _id: parent, name: parentName, ownerName: 'Browser owner', description: 'Browser portfolio',
        productArea: suffix, status: 'Active', createdAt: now, updatedAt: now });
      for (const role of ['Engineer', 'Read Only']) {
        await db.collection('roles').updateOne({ name: role }, { $setOnInsert: { name: role,
          permissions: role === 'Engineer' ? ['view', 'create', 'edit', 'export'] : ['view'], description: 'Browser role', createdAt: now, updatedAt: now } }, { upsert: true });
      }
      await use({ name, email, password, parent: parent.toHexString(), parentName,
        verify: async (id, role, status, manager = null, edits = 0, deactivations = 0) => {
          const row = await db.collection('users').findOne({ _id: new ObjectId(id) });
          expect(row?.email).toBe(email); expect(row?.role).toBe(role); expect(row?.status).toBe(status);
          expect(row?.name).toBe(name); expect(row?.managerName).toBe(manager);
          expect(row?.portfolioAccess).toEqual([parent]); expect(row?.mustChangePassword).toBe(false);
          expect(await compare(password, row?.passwordHash as string)).toBe(true);
          expect(row?.createdAt).toBeInstanceOf(Date);
          for (const [action, count] of [['create', 1], ['edit', edits], ['delete', deactivations]] as const) {
            expect(await db.collection('audit_logs').countDocuments({ entityId: new ObjectId(id), userId: new ObjectId(identity.id), action })).toBe(count);
          }
        },
      });
    } finally {
      const account = await db.collection('users').findOne({ email });
      if (account) {
        await db.collection('audit_logs').deleteMany({ $or: [{ entityId: account._id }, { userId: account._id }] });
        await db.collection('users').deleteOne({ _id: account._id });
      }
      await db.collection('portfolios').deleteOne({ _id: parent });
      await mongo.close();
    }
  },
});
for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test.describe(`Users journey ${viewport.width}px`, () => {
    test.use({ identityOptions: { role: 'Administrator', mustChangePassword: false }, expectedHttpErrors: [401] });
    test('creates assigns edits deactivates and denies the deactivated sign-in', async ({ page, request, identity, accounts, browserErrors }) => {
      await page.setViewportSize(viewport);
      await page.goto('/users'); // Only initial entry; all later navigation uses UI.
      await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
      await page.getByLabel('Email').fill(identity.email);
      await page.getByLabel('Password', { exact: true }).fill(identity.password);
      const authentication = page.waitForResponse((response) => response.url().endsWith('/api/auth/login'));
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      const authenticated = await authentication; expect(authenticated.status()).toBe(200); const admin = await authenticated.json();
      await navigateShell(page, 'Users');
      await page.getByRole('button', { name: 'Create user', exact: true }).click();
      const dialog = page.getByRole('dialog');
      await expect(dialog.getByLabel('Name', { exact: true })).toBeFocused();
      await expect(dialog.getByLabel(`${accounts.parentName} (Active)`)).toBeVisible();
      await dialog.getByRole('button', { name: 'Save user' }).click();
      await expect(dialog.getByLabel('Name', { exact: true })).toHaveAttribute('aria-invalid', 'true');
      await dialog.getByLabel('Name', { exact: true }).fill(accounts.name);
      await dialog.getByLabel('Email', { exact: true }).fill(accounts.email.toUpperCase());
      await dialog.getByLabel('Initial password').fill(accounts.password);
      await dialog.getByLabel(`${accounts.parentName} (Active)`).check();
      const creation = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/api/users'));
      await dialog.getByRole('button', { name: 'Save user' }).click();
      const created = await creation; expect(created.status()).toBe(201); let account = await created.json();
      expect(account.email).toBe(accounts.email); expect(account.passwordHash).toBeUndefined();
      await accounts.verify(account.id, 'Engineer', 'Active');
      await page.getByLabel('Search names or emails').fill(accounts.email);
      await page.getByLabel('Filter role').selectOption('Engineer');
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await expect(page).toHaveURL(/search=.*role=Engineer/);
      // List actions: cancelled edits/deactivation must not mutate HTTP or Mongo state.
      const headers = { Authorization: `Bearer ${admin.token}` };
      const verifyPersisted = async (role: string, status: string, manager: string | null, edits: number, deactivations: number) => {
        const response = await request.get(`${apiURL}/api/users/${account.id}`, { headers });
        expect(response.status()).toBe(200);
        const stored = await response.json();
        expect(stored).toMatchObject({ id: account.id, name: accounts.name, email: accounts.email, role, status, managerName: manager, portfolioAccess: [accounts.parent] });
        expect(stored.passwordHash).toBeUndefined();
        await accounts.verify(account.id, role, status, manager, edits, deactivations);
        return stored;
      };
      const row = page.getByRole('table', { name: 'User accounts' }).getByRole('row').filter({ has: page.getByRole('link', { name: accounts.name, exact: true }) });
      await row.getByRole('button', { name: `Edit ${accounts.name}`, exact: true }).click();
      await dialog.getByLabel('Manager name').fill('Cancelled list edit');
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await expect(dialog).toHaveCount(0);
      expect((await verifyPersisted('Engineer', 'Active', null, 0, 0)).updatedAt).toBe(account.updatedAt);
      await row.getByRole('button', { name: `Edit ${accounts.name}`, exact: true }).click();
      await expect(dialog.getByLabel('Initial password')).toHaveCount(0);
      await dialog.getByLabel('Manager name').fill('List Manager');
      const listEdit = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`/api/users/${account.id}`));
      await dialog.getByRole('button', { name: 'Save user' }).click();
      const listEdited = await listEdit; expect(listEdited.status()).toBe(200);
      expect(listEdited.request().postDataJSON().expectedUpdatedAt).toBe(account.updatedAt);
      expect(listEdited.request().postDataJSON().password).toBeUndefined();
      await expect(dialog).toHaveCount(0);
      account = await verifyPersisted('Engineer', 'Active', 'List Manager', 1, 0);
      await expect(row).toContainText('Active');
      await row.getByRole('button', { name: `Deactivate ${accounts.name}`, exact: true }).click();
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await expect(dialog).toHaveCount(0);
      expect((await verifyPersisted('Engineer', 'Active', 'List Manager', 1, 0)).updatedAt).toBe(account.updatedAt);
      await row.getByRole('button', { name: `Deactivate ${accounts.name}`, exact: true }).click();
      const listDelete = page.waitForResponse(response => response.request().method() === 'DELETE' && response.url().includes(`/api/users/${account.id}`));
      await dialog.getByRole('button', { name: 'Confirm deactivate' }).click();
      const listDeleted = await listDelete; expect(listDeleted.status()).toBe(200);
      expect(await listDeleted.json()).toEqual({ deactivated: true, id: account.id });
      await expect(dialog).toHaveCount(0);
      account = await verifyPersisted('Engineer', 'Inactive', 'List Manager', 1, 1);
      await expect(row).toContainText('Inactive');
      await expect(row.getByRole('button', { name: `Deactivate ${accounts.name}`, exact: true })).toHaveCount(0);
      await row.getByRole('link', { name: accounts.name, exact: true }).click();
      await expect(page.getByRole('heading', { name: accounts.name })).toBeVisible();
      await expect(page.getByText('local', { exact: true })).toBeVisible();
      await page.getByRole('button', { name: `Edit ${accounts.name}`, exact: true }).click();
      await expect(dialog.getByLabel('Initial password')).toHaveCount(0);
      await dialog.getByLabel('Manager name').fill('Cancelled detail edit');
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await expect(dialog).toHaveCount(0);
      expect((await verifyPersisted('Engineer', 'Inactive', 'List Manager', 1, 1)).updatedAt).toBe(account.updatedAt);
      await page.getByRole('button', { name: `Edit ${accounts.name}`, exact: true }).click();
      // Reactivate via the supported detail editor to exercise its deactivation too.
      await dialog.getByLabel('Status', { exact: true }).selectOption('Active');
      await dialog.getByLabel('Role', { exact: true }).selectOption('Read Only');
      await dialog.getByLabel('Manager name').fill('Browser Manager');
      const editing = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith(`/api/users/${account.id}`));
      await dialog.getByRole('button', { name: 'Save user' }).click();
      const edited = await editing; expect(edited.status()).toBe(200);
      expect(edited.request().postDataJSON().password).toBeUndefined();
      expect(edited.request().postDataJSON().expectedUpdatedAt).toBe(account.updatedAt);
      await expect(dialog).toHaveCount(0);
      account = await verifyPersisted('Read Only', 'Active', 'Browser Manager', 2, 1);
      await expect(page.getByText('Browser Manager', { exact: true })).toBeVisible();
      await page.getByRole('link', { name: 'Back to users' }).click();
      await expect(page.getByText('No users match these filters.')).toBeVisible();
      await page.getByRole('button', { name: 'Clear filters' }).click();
      await page.getByLabel('Search names or emails').fill(accounts.email);
      await page.getByRole('button', { name: 'Apply filters' }).click();
      const activeLogin = await request.post(`${apiURL}/api/auth/login`, { data: { email: accounts.email, password: accounts.password } });
      expect(activeLogin.status()).toBe(200); const active = await activeLogin.json();
      // Login intentionally updates lastLogin and updatedAt; cancel must preserve this new snapshot.
      account = await verifyPersisted('Read Only', 'Active', 'Browser Manager', 2, 1);
      await page.getByRole('link', { name: accounts.name, exact: true }).click();
      await expect(page.getByText('Browser Manager', { exact: true })).toBeVisible();
      await page.getByRole('button', { name: `Deactivate ${accounts.name}`, exact: true }).click();
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await expect(dialog).toHaveCount(0);
      expect((await verifyPersisted('Read Only', 'Active', 'Browser Manager', 2, 1)).updatedAt).toBe(account.updatedAt);
      await expect(page.getByRole('button', { name: `Deactivate ${accounts.name}`, exact: true })).toBeVisible();
      await page.getByRole('button', { name: `Deactivate ${accounts.name}`, exact: true }).click();
      const deletion = page.waitForResponse((response) => response.request().method() === 'DELETE' && response.url().includes(`/api/users/${account.id}`));
      await dialog.getByRole('button', { name: 'Confirm deactivate' }).click();
      const deactivated = await deletion; expect(deactivated.status()).toBe(200);
      expect(await deactivated.json()).toEqual({ deactivated: true, id: account.id });
      await expect(dialog).toHaveCount(0);
      await verifyPersisted('Read Only', 'Inactive', 'Browser Manager', 2, 2);
      await expect(page.getByRole('button', { name: `Deactivate ${accounts.name}`, exact: true })).toHaveCount(0);
      await expect(page.locator('dd').filter({ hasText: /^Inactive$/ })).toHaveText('Inactive');
      const persisted = await request.get(`${apiURL}/api/users/${account.id}`, { headers: { Authorization: `Bearer ${admin.token}` } });
      expect(persisted.status()).toBe(200); expect((await persisted.json()).status).toBe('Inactive');
      expect((await request.get(`${apiURL}/api/auth/me`, { headers: { Authorization: `Bearer ${active.token}` } })).status()).toBe(401);
      await signOutShell(page);
      await page.getByLabel('Email').fill(accounts.email);
      await page.getByLabel('Password', { exact: true }).fill(accounts.password);
      const denied = page.waitForResponse((response) => response.url().endsWith('/api/auth/login'));
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      expect((await denied).status()).toBe(401);
      await expect(page.getByRole('alert')).toHaveText('Unable to authenticate');
      await page.screenshot({ path: test.info().outputPath('users.png') });
      expect(browserErrors).toEqual([]);
    });
  });
}
