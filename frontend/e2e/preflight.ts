/** Capture representative real rendered interface states for source-level review. */
import { chromium } from '@playwright/test';
import { MongoClient } from 'mongodb';
import { hash } from 'bcryptjs';
import { randomBytes } from 'node:crypto';
import { writeFile, mkdir } from 'node:fs/promises';
const browser = await chromium.launch({ headless: true });
const mongo = new MongoClient(process.env.E2E_MONGODB_URI!);
await mongo.connect();
const db = mongo.db(process.env.E2E_MONGODB_DB!);
const password = randomBytes(24).toString('base64url');
const now = new Date();
await db.collection('roles').updateOne({ name: 'Administrator' }, { $setOnInsert: { name: 'Administrator', permissions: ['view','create','edit','delete','export','administer'], description: 'Preflight', createdAt: now, updatedAt: now } }, { upsert: true });
const result = await db.collection('users').insertOne({ name: 'Preflight reviewer', email: 'preflight@example.com', passwordHash: await hash(password, 12), role: 'Administrator', portfolioAccess: [], status: 'Active', mustChangePassword: false, authSource: 'local', lastLogin: null, managerName: null, vendorIndicator: false, createdAt: now, updatedAt: now });
const captures: string[] = [];
await mkdir('../ui-screenshots', { recursive: true });
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } });
    await page.goto(process.env.E2E_BASE_URL!);
    await page.getByLabel('Email', { exact: true }).fill('preflight@example.com');
    await page.getByLabel('Password', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.getByRole('heading', { name: 'Authenticated session' }).waitFor();
    for (const destination of ['Dashboard', 'Portfolios', 'Applications']) {
      if (width < 1024) await page.getByRole('button', { name: 'Open navigation' }).click();
      const scope = width < 1024 ? page.getByRole('dialog', { name: 'Navigation' }) : page.locator('.desktop-navigation');
      await scope.getByRole('link', { name: destination, exact: true }).click();
      await page.getByRole('heading', { name: destination === 'Dashboard' ? 'Executive dashboard' : destination, exact: true }).waitFor();
      await page.waitForLoadState('networkidle');
      const cdp = await page.context().newCDPSession(page);
      const tree = await cdp.send('Accessibility.getFullAXTree');
      const styles = await page.evaluate(() => ({ font: getComputedStyle(document.body).fontFamily, background: getComputedStyle(document.body).backgroundColor, width: document.documentElement.scrollWidth, viewport: innerWidth }));
      captures.push(`${width}px ${destination}\nAccessibility\n${JSON.stringify(tree.nodes.map(node => ({ role: node.role?.value, name: node.name?.value })), null, 2)}\nStyles\n${JSON.stringify(styles)}\nHTML\n${await page.content()}`);
      await page.screenshot({ path: `../ui-screenshots/${width}-${destination}.png`, fullPage: true });
    }
    await page.close();
  }
  await writeFile('../ui-preflight.txt', captures.join('\n\n'), 'utf8');
} finally {
  await db.collection('users').deleteOne({ _id: result.insertedId });
  await db.collection('audit_logs').deleteMany({ userId: result.insertedId });
  await mongo.close();
  await browser.close();
}
