/** Generate disposable credentials and capture browser faults before entry. */
import { test as base, expect } from '@playwright/test';
import { MongoClient, ObjectId } from 'mongodb';
import { hash, compare } from 'bcryptjs';
import { randomBytes } from 'node:crypto';
import { loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
const env = loadEnv('development', fileURLToPath(new URL('../', import.meta.url)), '');
interface IdentityFixture {
  email: string; password: string; id: string; name: string;
  verifyProfile: (password: string, landing: string) => Promise<void>;
}
interface IdentityOptions { role: 'Engineer' | 'Administrator'; mustChangePassword: boolean }

export const test = base.extend<{ identity: IdentityFixture; browserErrors: string[]; identityOptions: IdentityOptions; expectedHttpErrors: number[] }>({
  identityOptions: [{ role: 'Engineer', mustChangePassword: false }, { option: true }],
  expectedHttpErrors: [[401], { option: true }],
  identity: async ({ identityOptions }, use) => {
    const databaseName = process.env.E2E_MONGODB_DB || env.E2E_MONGODB_DB;
    if (!databaseName?.startsWith('etsip_e2e_')) throw new Error('Use a disposable etsip_e2e_ database');
    const client = new MongoClient(process.env.E2E_MONGODB_URI || env.E2E_MONGODB_URI);
    await client.connect();
    const db = client.db(databaseName);
    const now = new Date();
    const id = new ObjectId();
    const identity: IdentityFixture = { verifyProfile: async (password, landing) => {
      const stored = await db.collection('users').findOne({ _id: id });
      expect(stored?.mustChangePassword).toBe(false);
      expect(stored?.defaultLandingPage).toBe(landing);
      expect(await compare(password, stored?.passwordHash as string)).toBe(true);
      expect(await db.collection('audit_logs').countDocuments({ userId: id, action: 'edit' })).toBeGreaterThanOrEqual(2);
    }, id: id.toHexString(), email: `auth-${randomBytes(8).toString('hex')}@example.com`, password: randomBytes(24).toString('base64url'), name: 'Browser Test Engineer' };
    try {
      await db.collection('roles').updateOne({ name: identityOptions.role }, { $setOnInsert: { name: identityOptions.role, permissions: identityOptions.role === 'Administrator' ? ['view','create','edit','delete','export','administer'] : ['view','create','edit','export'], description: 'Test engineer', createdAt: now, updatedAt: now } }, { upsert: true });
      await db.collection('users').insertOne({ _id: id, name: identity.name, email: identity.email, passwordHash: await hash(identity.password, 12), role: identityOptions.role, portfolioAccess: [], status: 'Active', lastLogin: null, authSource: 'local', managerName: null, vendorIndicator: false, mustChangePassword: identityOptions.mustChangePassword, defaultLandingPage: null, createdAt: now, updatedAt: now });
      await use(identity);
      const stored = await db.collection('users').findOne({ _id: id });
      expect(stored?.lastLogin).toBeInstanceOf(Date);
      expect(await db.collection('audit_logs').countDocuments({ userId: id, details: 'Sign-in succeeded' })).toBeGreaterThan(0);
    } finally {
      await db.collection('users').deleteOne({ _id: id });
      await db.collection('audit_logs').deleteMany({ userId: id });
      await client.close();
    }
  },
  browserErrors: [async ({ page, expectedHttpErrors }, use) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('console', (message) => {
      // Chromium emits a network console diagnostic for the explicitly tested 401.
      if (message.type() === 'error' && !expectedHttpErrors.some((status) => message.text().includes(`status of ${status} (`))) errors.push(message.text());
    });
    await use(errors);
    expect(errors).toEqual([]);
  }, { auto: true }],
});
export { expect };
