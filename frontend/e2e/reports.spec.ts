/** Real UI report/download journeys; intentionally not executed in this slice. */
import { readFile } from 'node:fs/promises';
import { test, expect } from './fixtures';
import type { ApplicationReportRow, PortfolioReportRow, Page } from '../src/types';
import { applicationColumns, portfolioColumns } from '../src/features/reports/reportApi';
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { cell += '"'; i += 1; }
      else quoted = !quoted;
    } else if (char === ',' && !quoted) { row.push(cell); cell = ''; }
    else if (char === '\n' && !quoted) { row.push(cell); rows.push(row); row = []; cell = ''; }
    else if (char !== '\r' || quoted) cell += char;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}


for (const role of ['Engineer','Portfolio Leader','Administrator','Executive','Auditor','Read Only'] as const) {
  test.describe(`${role} scoped reports`,()=>{
    test.use({identityOptions:{role,mustChangePassword:false},expectedHttpErrors:[401,400,403]});
    for (const width of [1280,390]) {
      test(`tables, filters and persisted CSV at ${width}px`,async({page,identity,browserErrors})=>{
        const scope=await identity.reportInventory();
        await page.setViewportSize({width,height:844});
        await page.goto('/reports');
        await expect(page.getByRole('heading',{name:'Sign in'})).toBeVisible();
        for (const resource of ['applications','portfolios']) expect((await page.request.get(`/api/reports/${resource}`)).status()).toBe(401);
        await page.getByLabel('Email').fill(identity.email);
        await page.getByLabel('Password',{exact:true}).fill(identity.password);
        const loginResponse=page.waitForResponse(r=>r.url().endsWith('/api/auth/login'));
        await page.getByRole('button',{name:'Sign in',exact:true}).click();
        const session=await (await loginResponse).json();
        await page.getByRole('link',{name:'Reports',exact:true}).click();
        await expect(page.getByRole('heading',{name:'Application report'})).toBeVisible();
        for (const resource of ['applications','portfolios'] as const) {
          if(resource==='portfolios') await page.getByRole('link',{name:'Portfolio report',exact:true}).click();
          await page.getByLabel('productArea',{exact:true}).fill(identity.id);
          await page.getByLabel('Rows per page').selectOption('10');
          const filteredResponse=page.waitForResponse(r=>r.url().includes(`/api/reports/${resource}?`)&&!r.url().includes('format=csv'));
          await page.getByRole('button',{name:'Apply filters'}).click();
          const result:Page<ApplicationReportRow|PortfolioReportRow>=await (await filteredResponse).json();
          expect(result.total).toBe(resource==='applications'?12:1);
          await expect(page.getByRole('table')).toContainText(result.items[0].name);
          expect(new URL(page.url()).searchParams.get('productArea')).toBe(identity.id);
          const api=await page.request.get(`/api/reports/${resource}?productArea=${identity.id}&pageSize=100`,{headers:{Authorization:`Bearer ${session.token}`}});
          expect(api.status()).toBe(200);
          const all:Page<ApplicationReportRow|PortfolioReportRow>=await api.json();
          expect(all.items.some(row=>'portfolioId' in row ? row.portfolioId===scope.hidden : row.id===scope.hidden)).toBe(false);
          if(resource==='applications') {
            const next=page.waitForResponse(r=>r.url().includes('/api/reports/applications?')&&r.url().includes('page=2'));
            await page.getByRole('button',{name:'Next',exact:true}).click();
            expect((await (await next).json()).items).toHaveLength(2);
          }
          if(role==='Read Only') {
            await expect(page.getByRole('button',{name:'Export CSV'})).toHaveCount(0);
            const denied=await page.request.get(`/api/reports/${resource}?format=csv`,{headers:{Authorization:`Bearer ${session.token}`}});
            expect(denied.status()).toBe(403);
            await identity.verifyReport(resource,all.items,0);
          } else {
            const downloadEvent=page.waitForEvent('download');
            await page.getByRole('button',{name:'Export CSV'}).click();
            const download=await downloadEvent;
            expect(download.suggestedFilename()).toBe(resource==='applications'?'application-report.csv':'portfolio-report.csv');
            const target=test.info().outputPath(`${resource}.csv`);
            await download.saveAs(target);
            const csv=parseCsv(await readFile(target,'utf-8'));
            const columns=resource==='applications'?applicationColumns:portfolioColumns;
            expect(csv[0]).toEqual(columns);
            expect(csv.slice(1)).toEqual(all.items.map(row=>columns.map(key=>{
              const value=String((row as unknown as Record<string,unknown>)[key]??'');
              return /^[=+\-@]/.test(value)?`'${value}`:value;
            })));
            await expect(page.getByText('CSV download started')).toBeVisible();
            await identity.verifyReport(resource,all.items,1);
          }
        }
        await page.getByRole('link',{name:'Applications',exact:true}).click();
        await page.getByLabel('Filter portfolio ID').fill(scope.visible);
        await page.getByRole('button',{name:'Apply filters'}).click();
        await expect(page.getByRole('table')).toBeVisible();
        if(role==='Read Only') {
          await expect(page.getByRole('button',{name:'Export CSV'})).toHaveCount(0);
          expect((await page.request.get('/api/applications?format=csv',{headers:{Authorization:`Bearer ${session.token}`}})).status()).toBe(403);
        } else {
          const download=page.waitForEvent('download');
          await page.getByRole('button',{name:'Export CSV'}).click();
          expect((await download).suggestedFilename()).toBe('application-report.csv');
        }
        await page.getByRole('link',{name:'Reports',exact:true}).click();
        await page.getByLabel('search',{exact:true}).fill('No such report application');
        await page.getByRole('button',{name:'Apply filters'}).click();
        await expect(page.getByText('No applications match your scope and filters.')).toBeVisible();
        await page.getByLabel('portfolioId',{exact:true}).fill('bad');
        await page.getByRole('button',{name:'Apply filters'}).click();
        await expect(page.getByRole('alert')).toHaveText('Invalid report filters');
        await page.getByRole('button',{name:'Clear filters'}).click();
        await expect(page.getByRole('table')).toBeVisible();
        await page.screenshot({path:test.info().outputPath('reports.png')});
        expect(browserErrors).toEqual([]);
      });
    }
  });
}
