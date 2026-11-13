/** Generate disposable credentials and capture browser faults before entry. */
import { test as base, expect } from '@playwright/test';
import { MongoClient, ObjectId } from 'mongodb';
import { hash, compare } from 'bcryptjs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { homedir } from 'node:os';
import { randomBytes } from 'node:crypto';
import { loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
import type { RoleName, AuditRow, ApplicationReportRow, PortfolioReportRow } from '../src/types';
const env = loadEnv('development', fileURLToPath(new URL('../', import.meta.url)), '');
interface IdentityFixture {
  email: string; password: string; id: string; name: string;
  verifyAudit: (rows: AuditRow[], count: number) => Promise<void>;
  verifyProfile: (password: string, landing: string) => Promise<void>;
  reportInventory: () => Promise<{ visible: string; hidden: string }>;
  verifyReport: (resource: 'applications' | 'portfolios', rows: Array<ApplicationReportRow | PortfolioReportRow>, exports: number) => Promise<void>;
}
interface IdentityOptions { role: RoleName; mustChangePassword: boolean }

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
    const reportIds: ObjectId[] = [];
    const identity: IdentityFixture = {
      reportInventory: async () => {
        const visible = new ObjectId(); const hidden = new ObjectId();
        reportIds.push(visible, hidden);
        await db.collection('portfolios').insertMany([visible,hidden].map((portfolioId,index) => ({_id:portfolioId,name:`Report ${id}-${index}`,ownerName:'Test owner',description:'Fake fixture',productArea:id.toHexString(),status:'Active',createdAt:now,updatedAt:now})));
        await db.collection('applications').insertMany(Array.from({length:13},(_,index)=>({name:`Report ${id} App ${index.toString().padStart(2,'0')}`,description:'Fake fixture',portfolioId:index===12?hidden:visible,productArea:id.toHexString(),businessOwner:'Test',technologyOwner:'Test',etsOwner:'Test',criticality:'High',tier:2,lifecycleStatus:'Active',technologyStack:'Python',repositoryUrl:null,pipelineUrl:null,applicationHealthScore:82,qualityScore:79,automationCoverage:65,unitTestCoverage:72,openDefects:4,openCriticalDefects:1,riskLevel:'Medium',createdAt:now,updatedAt:now})));
        await db.collection('users').updateOne({_id:id},{$set:{portfolioAccess:[visible]}});
        return {visible:visible.toHexString(),hidden:hidden.toHexString()};
      },
      verifyReport: async (resource,rows,exports) => {
        for (const row of rows) {
          const stored = await db.collection(resource).findOne({_id:new ObjectId(row.id)});
          expect(stored?.name).toBe(row.name);
          for (const [key,value] of Object.entries(row)) {
            if (key==='id') continue;
            if (key==='applicationCount') expect(value).toBe(await db.collection('applications').countDocuments({portfolioId:stored?._id}));
            else if (key==='qualityScore' && resource==='portfolios') { expect(value).toBe(79); expect(stored?.qualityScore).toBeUndefined(); }
            else expect(key==='portfolioId'?stored?.[key].toHexString():stored?.[key]).toBe(value);
          }
        }
        const events = await db.collection('audit_logs').find({userId:id,action:'export',entityType:resource==='applications'?'application':'portfolio'}).toArray();
        expect(events).toHaveLength(exports);
        if (exports) expect(events.at(-1)?.details).toContain(`${rows.length} rows`);
      },
      verifyAudit: async (rows, count) => {
      const events = await db.collection('audit_logs').find({ userId: id }).toArray();
      expect(events.some((event) => event.action === 'login' && event.details === 'Sign-in succeeded')).toBe(true);
      expect(events.some((event) => event.action === 'edit' && event.details === 'Updated landing preference')).toBe(true);
      const exported = events.filter((event) => event.action === 'export');
      expect(exported).toHaveLength(1);
      expect(exported[0].entityType).toBe('audit');
      expect(exported[0].details).toContain(`${count} rows`);
      for (const row of rows) {
        const stored = await db.collection('audit_logs').findOne({ _id: new ObjectId(row.id) });
        expect(stored?.userId?.toHexString()).toBe(row.userId);
        expect(stored?.details).toBe(row.details);
        expect(stored?.action).toBe(row.action);
        expect(stored?.timestamp.toISOString()).toBe(new Date(row.timestamp).toISOString());
      }
    }, verifyProfile: async (password, landing) => {
      const stored = await db.collection('users').findOne({ _id: id });
      expect(stored?.mustChangePassword).toBe(false);
      expect(stored?.defaultLandingPage).toBe(landing);
      expect(await compare(password, stored?.passwordHash as string)).toBe(true);
      expect(await db.collection('audit_logs').countDocuments({ userId: id, action: 'edit' })).toBeGreaterThanOrEqual(2);
    }, id: id.toHexString(), email: `auth-${randomBytes(8).toString('hex')}@example.com`, password: randomBytes(24).toString('base64url'), name: 'Browser Test Engineer' };
    try {
      await db.collection('roles').updateOne({ name: identityOptions.role }, { $setOnInsert: { name: identityOptions.role, permissions: identityOptions.role === 'Administrator' ? ['view','create','edit','delete','export','administer'] : identityOptions.role === 'Read Only' ? ['view'] : ['Auditor','Executive'].includes(identityOptions.role) ? ['view','export'] : ['view','create','edit','export'], description: 'Test engineer', createdAt: now, updatedAt: now } }, { upsert: true });
      await db.collection('users').insertOne({ _id: id, name: identity.name, email: identity.email, passwordHash: await hash(identity.password, 12), role: identityOptions.role, portfolioAccess: [], status: 'Active', lastLogin: null, authSource: 'local', managerName: null, vendorIndicator: false, mustChangePassword: identityOptions.mustChangePassword, defaultLandingPage: null, createdAt: now, updatedAt: now });
      await use(identity);
      const stored = await db.collection('users').findOne({ _id: id });
      expect(stored?.lastLogin).toBeInstanceOf(Date);
      expect(await db.collection('audit_logs').countDocuments({ userId: id, details: 'Sign-in succeeded' })).toBeGreaterThan(0);
    } finally {
      await db.collection('applications').deleteMany({portfolioId:{$in:reportIds}});
      await db.collection('portfolios').deleteMany({_id:{$in:reportIds}});
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

/** Seed through the Python service, keeping credentials strictly in the test process. */
export const seededTest = test.extend<{ seededRelease: { password: (admin: boolean) => string; inventory: Array<{ name: string; portfolioId: string; qualityScore: number; applicationHealthScore: number; automationCoverage: number; openCriticalDefects: number; riskLevel: string }>; portfolios: Array<{ id: string; name: string }>; restoreAdmin: () => Promise<void> } }>({
  seededRelease: async ({}, use) => {
    const databaseName = process.env.E2E_MONGODB_DB || env.E2E_MONGODB_DB;
    const uri = process.env.E2E_MONGODB_URI || env.E2E_MONGODB_URI;
    if (!databaseName?.startsWith('etsip_e2e_') || !uri) throw new Error('Seed browser tests require a disposable configured Mongo database');
    const backendRoot = fileURLToPath(new URL('../../backend/', import.meta.url));
    const backendEnv = loadEnv('development', backendRoot, '');
    const adminPassword = process.env.SEED_ADMIN_PASSWORD || backendEnv.SEED_ADMIN_PASSWORD;
    const demoPassword = process.env.SEED_DEMO_PASSWORD || backendEnv.SEED_DEMO_PASSWORD;
    if (!adminPassword || !demoPassword) throw new Error('Seed browser credentials must be configured');
    try {
      await promisify(execFile)(`${homedir()}/venvs/app/bin/python`, ['-m', 'api.seed.runner'], {
        cwd: backendRoot, env: { ...process.env, MONGODB_DB: databaseName, MONGODB_URI: uri,
          SEED_ADMIN_PASSWORD: adminPassword, SEED_DEMO_PASSWORD: demoPassword },
      });
    } catch { throw new Error('Seed CLI failed; check secure seed configuration and Mongo readiness'); }
    const client = new MongoClient(uri);
    try {
      await client.connect();
      const db = client.db(databaseName);
      const portfolios = await db.collection('portfolios').find({ name: { $in: ['Payments','Customer Platform','Data & Analytics'] } }).toArray();
      expect(portfolios).toHaveLength(3);
      const inventory = await db.collection('applications').find({ portfolioId: { $in: portfolios.map(row=>row._id) } }).toArray();
      expect(inventory).toHaveLength(10);
      const admin = await db.collection('users').findOne({ email:'admin@ketsip.local' });
      if (!admin) throw new Error('Seed administrator missing');
      const restoreAdmin = async () => {
        await db.collection('users').updateOne({ _id:admin._id }, { $set:{ passwordHash:admin.passwordHash, mustChangePassword:admin.mustChangePassword, defaultLandingPage:admin.defaultLandingPage } });
      };
      try {
        await use({ password:(isAdmin)=>isAdmin?adminPassword:demoPassword,
          portfolios:portfolios.map(row=>({id:row._id.toHexString(),name:row.name as string})),
          inventory:inventory.map(row=>({name:row.name as string,portfolioId:row.portfolioId.toHexString(),qualityScore:row.qualityScore as number,
            applicationHealthScore:row.applicationHealthScore as number,automationCoverage:row.automationCoverage as number,
            openCriticalDefects:row.openCriticalDefects as number,riskLevel:row.riskLevel as string})), restoreAdmin });
      } finally { await restoreAdmin(); }
    } finally { await client.close(); }
  },
});
