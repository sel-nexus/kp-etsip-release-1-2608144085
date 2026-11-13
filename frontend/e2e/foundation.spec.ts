/** Exercise six real seeded roles on desktop and mobile with no mocked transport. */
import { seededTest as test, expect } from './fixtures';
import { randomBytes } from 'node:crypto';
const roles = [
  { name:'Administrator', email:'admin', scope:[] },
  { name:'Executive', email:'executive', scope:[] },
  { name:'Portfolio Leader', email:'portfolio-leader', scope:['Payments','Customer Platform'] },
  { name:'Engineer', email:'engineer', scope:['Payments'] },
  { name:'Auditor', email:'auditor', scope:[] },
  { name:'Read Only', email:'read-only', scope:['Data & Analytics'] },
];
for (const mobile of [false, true]) {
  test.describe(mobile ? 'mobile seeded foundation' : 'desktop seeded foundation', () => {
    test.use({ viewport:mobile?{width:390,height:844}:{width:1440,height:1000} });
    for (const role of roles) {
      test(`${role.name} sees authorized inventory, dashboard and reports`, async ({ page, seededRelease }) => {
        await page.goto('/login');
        await page.getByLabel('Email', {exact:true}).fill(`${role.email}@ketsip.local`);
        await page.getByLabel('Password', {exact:true}).fill(seededRelease.password(role.name==='Administrator'));
        await page.getByRole('button', {name:'Sign in',exact:true}).click();
        await expect(page.getByRole('heading', {name:/^(Authenticated session|Secure your account)$/})).toBeVisible();
        if (role.name==='Administrator' && await page.getByRole('heading', {name:'Secure your account'}).isVisible()) {
          const replacement = randomBytes(24).toString('base64url');
          await page.getByLabel('Current password', {exact:true}).fill(seededRelease.password(true));
          await page.getByLabel('New password', {exact:true}).fill(replacement);
          await page.getByLabel('Confirm new password', {exact:true}).fill(replacement);
          await page.getByRole('button', {name:'Change password',exact:true}).click();
          await expect(page.getByRole('heading', {name:'Secure your account'})).toHaveCount(0);
        }
        await expect(page.getByRole('heading', {name:'Authenticated session'})).toBeVisible();
        /** Open actual responsive navigation after entry, then use real link controls. */
        const navigate = async (label: string) => {
          if (mobile) await page.getByRole('button', {name:'Open navigation'}).click();
          const nav = mobile ? page.getByRole('dialog', {name:'Navigation'}).getByRole('navigation') : page.getByRole('navigation', {name:'Session navigation'});
          await nav.getByRole('link', {name:label,exact:true}).click();
          if (mobile) await expect(page.getByRole('dialog')).toHaveCount(0);
        };
        if (mobile) {
          const trigger = page.getByRole('button', {name:'Open navigation'});
          await trigger.click();
          await expect(page.getByRole('button', {name:'Close navigation'})).toBeFocused();
          await page.keyboard.press('Shift+Tab');
          await expect(page.getByRole('dialog').getByRole('button', {name:'Sign out'})).toBeFocused();
          await page.keyboard.press('Escape');
          await expect(trigger).toBeFocused();
          await trigger.click();
        }
        const nav = mobile ? page.getByRole('dialog').getByRole('navigation') : page.getByRole('navigation', {name:'Session navigation'});
        await expect(nav.getByRole('link',{name:'Users',exact:true})).toHaveCount(role.name==='Administrator'?1:0);
        await expect(nav.getByRole('link',{name:'Roles',exact:true})).toHaveCount(role.name==='Administrator'?1:0);
        await expect(nav.getByRole('link',{name:'Audit history',exact:true})).toHaveCount(['Administrator','Auditor'].includes(role.name)?1:0);
        if (mobile) await page.keyboard.press('Escape');
        const visibleParents = seededRelease.portfolios.filter(row=>!role.scope.length || role.scope.includes(row.name));
        const visibleIds = visibleParents.map(row=>row.id);
        const visibleApps = seededRelease.inventory.filter(row=>visibleIds.includes(row.portfolioId));
        await navigate('Portfolios');
        for (const portfolio of seededRelease.portfolios) {
          await expect(page.getByRole('main').getByRole('link',{name:portfolio.name,exact:true})).toHaveCount(visibleIds.includes(portfolio.id)?1:0);
        }
        await navigate('Applications');
        for (const app of seededRelease.inventory) {
          await expect(page.getByRole('main').getByRole('link',{name:app.name,exact:true})).toHaveCount(visibleIds.includes(app.portfolioId)?1:0);
        }
        await navigate('Dashboard');
        await expect(page.locator('[data-metric=totalApplications]')).toHaveText(String(visibleApps.length));
        await expect(page.locator('[data-metric=totalPortfolios]')).toHaveText(String(visibleParents.length));
        const mean = (key:'qualityScore'|'applicationHealthScore'|'automationCoverage') => Math.floor(visibleApps.reduce((sum,row)=>sum+row[key],0)/visibleApps.length+0.5);
        await expect(page.locator('[data-metric=enterpriseQualityScore]')).toHaveText(String(mean('qualityScore')));
        await expect(page.locator('[data-metric=averageApplicationHealthScore]')).toHaveText(String(mean('applicationHealthScore')));
        await expect(page.locator('[data-metric=automationMaturityScore]')).toHaveText(String(mean('automationCoverage')));
        await expect(page.locator('[data-metric=openCriticalDefects]')).toHaveText(String(visibleApps.reduce((sum,row)=>sum+row.openCriticalDefects,0)));
        await expect(page.locator('[data-metric=applicationsAtRisk]')).toHaveText(String(visibleApps.filter(row=>row.riskLevel==='High').length));
        await page.getByLabel('Product area',{exact:true}).fill('No such demo area');
        await page.getByRole('button',{name:'Apply filters',exact:true}).click();
        await expect(page.locator('[data-metric=totalApplications]')).toHaveText('0');
        await expect(page.locator('[data-metric=enterpriseQualityScore]')).toHaveText('Not available');
        await expect(page.locator('[data-metric=totalPortfolios]')).toHaveText(String(visibleParents.length));
        await navigate('Reports');
        await expect(page.getByRole('heading',{name:'Application report'})).toBeVisible();
        for (const app of seededRelease.inventory) {
          await expect(page.getByRole('main').getByRole('link',{name:app.name,exact:true})).toHaveCount(visibleIds.includes(app.portfolioId)?1:0);
        }
        await expect(page.getByRole('button',{name:'Export CSV',exact:true})).toHaveCount(role.name==='Read Only'?0:1);
        if (role.name!=='Read Only') {
          const download = page.waitForEvent('download');
          await page.getByRole('button',{name:'Export CSV',exact:true}).click();
          expect((await download).suggestedFilename()).toContain('.csv');
          await expect(page.getByRole('status').filter({hasText:'CSV download started'})).toBeVisible();
        }
        await page.getByRole('navigation',{name:'Report navigation'}).getByRole('link',{name:'Portfolio report',exact:true}).click();
        for (const portfolio of seededRelease.portfolios) {
          await expect(page.getByRole('main').getByRole('link',{name:portfolio.name,exact:true})).toHaveCount(visibleIds.includes(portfolio.id)?1:0);
        }
        if (mobile) {
          expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
          await page.getByRole('button',{name:'Open navigation'}).click();
          await page.getByRole('dialog').getByRole('button',{name:'Sign out'}).click();
        } else await page.getByRole('button',{name:'Sign out'}).click();
        await expect(page.getByRole('heading',{name:'Sign in'})).toBeVisible();
      });
    }
  });
}
