/** Reduce Engineer access through the UI and prove existing-token enforcement in Mongo. */
import { MongoClient, ObjectId } from 'mongodb';
import { hash } from 'bcryptjs';
import { randomBytes } from 'node:crypto';
import { loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
import { test, expect } from './fixtures';
const env = loadEnv('development', fileURLToPath(new URL('../', import.meta.url)), '');
const apiURL = process.env.E2E_API_URL || env.E2E_API_URL;

test.describe('Bounded role administration', () => {
  test.use({ identityOptions: { role: 'Administrator', mustChangePassword: false }, expectedHttpErrors: [401, 409] });
  for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
    test(`edits restores and enforces existing Engineer token at ${viewport.width}px`, async ({ page, request, identity, browserErrors }) => {
      const databaseName = process.env.E2E_MONGODB_DB || env.E2E_MONGODB_DB;
      if (!databaseName?.startsWith('etsip_e2e_')) throw new Error('Use a disposable etsip_e2e_ database');
      const mongo = new MongoClient(process.env.E2E_MONGODB_URI || env.E2E_MONGODB_URI);
      await mongo.connect();
      const db = mongo.db(databaseName);
      const suffix = randomBytes(8).toString('hex');
      const userId = new ObjectId(); const portfolioId = new ObjectId(); const applicationId = new ObjectId();
      const password = randomBytes(24).toString('base64url'); const email = `roles-${suffix}@example.com`;
      const original = await db.collection('roles').findOne({ name: 'Engineer' });
      const now = new Date();
      try {
        // Test-only fixture setup; all role changes in the journey use real HTTP/UI.
        await db.collection('roles').updateOne({ name: 'Engineer' }, { $set: {
          permissions: ['view','create','edit','export'], updatedAt: now,
        }, $setOnInsert: { description: 'Application engineering', createdAt: now } }, { upsert: true });
        await db.collection('portfolios').insertOne({ _id: portfolioId, name: `Role portfolio ${suffix}`, ownerName: 'Test owner',
          description: 'Role enforcement fixture', productArea: suffix, status: 'Active', createdAt: now, updatedAt: now });
        await db.collection('applications').insertOne({ _id: applicationId, name: `Role application ${suffix}`, portfolioId,
          description: 'Role enforcement fixture', productArea: suffix, businessOwner: 'Test business', technologyOwner: 'Test technology',
          etsOwner: 'Test ETS', criticality: 'High', tier: 2, lifecycleStatus: 'Active', technologyStack: 'Python', repositoryUrl: null,
          pipelineUrl: null, applicationHealthScore: 80, qualityScore: 80, automationCoverage: 50, unitTestCoverage: 60,
          openDefects: 0, openCriticalDefects: 0, riskLevel: 'Low', createdAt: now, updatedAt: now });
        await db.collection('users').insertOne({ _id: userId, name: 'Role test Engineer', email, passwordHash: await hash(password, 12),
          role: 'Engineer', portfolioAccess: [portfolioId], status: 'Active', mustChangePassword: false, authSource: 'local',
          managerName: null, vendorIndicator: false, lastLogin: null, defaultLandingPage: null, createdAt: now, updatedAt: now });
        const engineerLogin = await request.post(`${apiURL}/api/auth/login`, { data: { email, password } });
        expect(engineerLogin.status()).toBe(200);
        const engineerHeaders = { Authorization: `Bearer ${(await engineerLogin.json()).token}` };
        const applicationURL = `${apiURL}/api/applications/${applicationId.toHexString()}`;
        expect((await request.put(applicationURL, { headers: engineerHeaders, data: { qualityScore: 81 } })).status()).toBe(200);
        await page.setViewportSize(viewport);
        await page.goto('/roles'); // sole browser entry; subsequent navigation clicks UI links
        await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
        await page.getByLabel('Email').fill(identity.email);
        await page.getByLabel('Password', { exact: true }).fill(identity.password);
        const loginResponse = page.waitForResponse((response) => response.url().endsWith('/api/auth/login'));
        await page.getByRole('button', { name: 'Sign in', exact: true }).click();
        const loggedIn = await loginResponse; expect(loggedIn.status()).toBe(200);
        const adminHeaders = { Authorization: `Bearer ${(await loggedIn.json()).token}` };
        const listResponse = page.waitForResponse((response) => response.url().endsWith('/api/roles') && response.request().method() === 'GET');
        await page.getByRole('link', { name: 'Roles', exact: true }).click();
        const listed = await listResponse; expect(listed.status()).toBe(200);
        const role = (await listed.json()).items.find((item: { name: string }) => item.name === 'Engineer');
        const form = page.getByRole('form', { name: 'Engineer permissions', exact: true });
        await expect(form).toContainText('Maximum allowed: view, create, edit, export.');
        await expect(form.getByRole('checkbox', { name: 'delete', exact: true })).toHaveCount(0);
        await form.getByRole('checkbox', { name: 'edit', exact: true }).uncheck();
        const savedResponse = page.waitForResponse((response) => response.url().endsWith(`/api/roles/${role.id}`) && response.request().method() === 'PUT');
        await form.getByRole('button', { name: 'Save Engineer permissions' }).click();
        const saved = await savedResponse; expect(saved.status()).toBe(200);
        expect(saved.request().postDataJSON().expectedUpdatedAt).toBe(role.updatedAt);
        await expect(form.getByText('Permissions saved', { exact: true })).toBeVisible();
        const stored = await db.collection('roles').findOne({ _id: new ObjectId(role.id) });
        expect(stored?.permissions).toEqual(['view','create','export']);
        expect(await db.collection('audit_logs').countDocuments({ userId: new ObjectId(identity.id), entityId: new ObjectId(role.id), action: 'permissionChange' })).toBe(1);
        const denied = await request.put(applicationURL, { headers: engineerHeaders, data: { qualityScore: 82 } });
        expect(denied.status()).toBe(403); expect((await denied.json()).error.code).toBe('FORBIDDEN');
        expect((await db.collection('applications').findOne({ _id: applicationId }))?.qualityScore).toBe(81);
        // A real concurrent editor changes the version; the UI must show conflict, not overwrite.
        expect((await request.put(`${apiURL}/api/roles/${role.id}`, { headers: adminHeaders, data: { permissions: ['view','export'] } })).status()).toBe(200);
        await form.getByRole('checkbox', { name: 'edit', exact: true }).check();
        const conflictResponse = page.waitForResponse((response) => response.url().endsWith(`/api/roles/${role.id}`) && response.status() === 409);
        await form.getByRole('button', { name: 'Save Engineer permissions' }).click();
        expect((await conflictResponse).status()).toBe(409);
        await expect(form.getByRole('alert')).toContainText('Role changed. Reload and try again.');
        await page.getByRole('button', { name: 'Reload roles' }).click();
        await expect(form.getByRole('checkbox', { name: 'edit', exact: true })).not.toBeChecked();
        await form.getByRole('checkbox', { name: 'edit', exact: true }).check();
        await form.getByRole('checkbox', { name: 'create', exact: true }).check();
        const restoreResponse = page.waitForResponse((response) => response.url().endsWith(`/api/roles/${role.id}`) && response.request().method() === 'PUT');
        await form.getByRole('button', { name: 'Save Engineer permissions' }).click();
        expect((await restoreResponse).status()).toBe(200);
        expect(new Set((await db.collection('roles').findOne({ _id: new ObjectId(role.id) }))?.permissions)).toEqual(new Set(['view','create','edit','export']));
        expect((await request.put(applicationURL, { headers: engineerHeaders, data: { qualityScore: 83 } })).status()).toBe(200);
        expect((await db.collection('applications').findOne({ _id: applicationId }))?.qualityScore).toBe(83);
        await page.getByRole('link', { name: 'Session', exact: true }).click();
        await page.getByRole('link', { name: 'Roles', exact: true }).click();
        await expect(form.getByRole('checkbox', { name: 'edit', exact: true })).toBeChecked();
        await page.screenshot({ path: test.info().outputPath('roles.png') });
        expect(browserErrors).toEqual([]);
      } finally {
        if (original) await db.collection('roles').replaceOne({ _id: original._id }, original);
        else await db.collection('roles').deleteOne({ name: 'Engineer' });
        await db.collection('applications').deleteOne({ _id: applicationId });
        await db.collection('portfolios').deleteOne({ _id: portfolioId });
        await db.collection('users').deleteOne({ _id: userId });
        await db.collection('audit_logs').deleteMany({ userId });
        await mongo.close();
      }
    });
  }
});
