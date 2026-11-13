/** Generate disposable credentials and capture browser faults before entry. */
import { test as base, expect } from '@playwright/test';
import { MongoClient, ObjectId } from 'mongodb';
import { hash } from 'bcryptjs';
import { randomBytes } from 'node:crypto';
import { loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
const env = loadEnv('development', fileURLToPath(new URL('../', import.meta.url)), '');
interface IdentityFixture { email: string; password: string; id: string; name: string }
export const test = base.extend<{ identity: IdentityFixture; browserErrors: string[] }>({
  identity: async ({}, use) => {
    const databaseName = process.env.E2E_MONGODB_DB || env.E2E_MONGODB_DB;
    if (!databaseName?.startsWith('etsip_e2e_')) throw new Error('Use a disposable etsip_e2e_ database');
    const client = new MongoClient(process.env.E2E_MONGODB_URI || env.E2E_MONGODB_URI);
    await client.connect();
    const db = client.db(databaseName);
    const now = new Date();
    const id = new ObjectId();
    const identity = { id: id.toHexString(), email: `auth-${randomBytes(8).toString('hex')}@example.com`, password: randomBytes(24).toString('base64url'), name: 'Browser Test Engineer' };
    try {
      await db.collection('roles').updateOne({ name: 'Engineer' }, { $setOnInsert: { name: 'Engineer', permissions: ['view','create','edit','export'], description: 'Test engineer', createdAt: now, updatedAt: now } }, { upsert: true });
      await db.collection('users').insertOne({ _id: id, name: identity.name, email: identity.email, passwordHash: await hash(identity.password, 12), role: 'Engineer', portfolioAccess: [], status: 'Active', lastLogin: null, authSource: 'local', managerName: null, vendorIndicator: false, mustChangePassword: false, defaultLandingPage: null, createdAt: now, updatedAt: now });
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
  browserErrors: [async ({ page }, use) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('console', (message) => {
      // Chromium emits a network console diagnostic for the explicitly tested 401.
      if (message.type() === 'error' && !message.text().includes('401 (Unauthorized)')) errors.push(message.text());
    });
    await use(errors);
    expect(errors).toEqual([]);
  }, { auto: true }],
});
export { expect };
