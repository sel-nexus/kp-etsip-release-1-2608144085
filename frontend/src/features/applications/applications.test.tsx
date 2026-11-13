/** Verify application UI contracts through actual routes and the shared HTTP client. */
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { SessionProvider } from '../auth/SessionProvider';
import { AppRoutes } from '../../routes';
import { TOKEN_KEY } from '../../lib/api';
import { applicationLabels } from './applicationApi';
import type { ApplicationDetail, SafeUser, Portfolio } from '../../types';
const portfolio: Portfolio = {
  id: '65b100000000000000000001', name: 'Payments', description: 'Services', ownerName: 'Owner', productArea: 'Payments',
  status: 'Active', applicationCount: 1, qualityScore: 79, createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z',
};
const application: ApplicationDetail = {
  id: '65b200000000000000000001', name: 'Payment API', description: 'Core service', portfolioId: portfolio.id, productArea: 'Payments',
  businessOwner: 'Business', technologyOwner: 'Technology', etsOwner: 'ETS', criticality: 'High', tier: 2, lifecycleStatus: 'Active',
  technologyStack: 'Python', repositoryUrl: 'https://example.com/repo', pipelineUrl: null, applicationHealthScore: 82, qualityScore: 79,
  automationCoverage: 65, unitTestCoverage: 72, openDefects: 4, openCriticalDefects: 1, riskLevel: 'Medium',
  createdAt: portfolio.createdAt, updatedAt: portfolio.updatedAt, portfolio,
};
const user: SafeUser = {
  id: '65b000000000000000000001', name: 'Engineer', email: 'engineer@example.com', role: 'Engineer', portfolioAccess: [portfolio.id],
  status: 'Active', defaultLandingPage: null, mustChangePassword: false,
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const page = (items: unknown[] = [application], total = items.length, number = 1) => ({ items, total, page: number, pageSize: 25 });
/** Restore a real session context and exercise implemented feature routes. */
function mount(identity = user, entry = '/applications', response: unknown = page(), status = 200) {
  localStorage.setItem(TOKEN_KEY, 'test-token');
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json(identity)).mockResolvedValueOnce(json(response, status));
  render(
    <MemoryRouter initialEntries={[entry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </MemoryRouter>,
  );
  return fetch;
}
/** Fill required text fields through stable semantic labels. */
async function fill() {
  for (const key of ['name', 'description', 'productArea', 'businessOwner', 'technologyOwner', 'etsOwner', 'technologyStack'] as const) {
    await userEvent.type(screen.getByLabelText(applicationLabels[key], { exact: true }), application[key]);
  }
  await userEvent.selectOptions(screen.getByLabelText('Portfolio', { exact: true }), portfolio.id);
}
describe('Applications', () => {
  it.each(['Administrator', 'Portfolio Leader', 'Engineer', 'Executive', 'Auditor', 'Read Only'] as const)(
    'honors %s create/edit/delete boundaries', async (role) => {
      const fetch = mount({ ...user, role });
      await screen.findByRole('link', { name: 'Payment API' });
      expect(Boolean(screen.queryByRole('button', { name: 'Create application' }))).toBe(['Administrator', 'Portfolio Leader', 'Engineer'].includes(role));
      fetch.mockResolvedValueOnce(json(application));
      await userEvent.click(screen.getByRole('link', { name: 'Payment API' }));
      await screen.findByRole('heading', { name: 'Payment API' });
      expect(Boolean(screen.queryByRole('button', { name: 'Edit application' }))).toBe(['Administrator', 'Portfolio Leader', 'Engineer'].includes(role));
      expect(Boolean(screen.queryByRole('button', { name: 'Delete application' }))).toBe(role === 'Administrator');
      expect(screen.getByRole('link', { name: 'Payments' })).toHaveAttribute('href', `/portfolios/${portfolio.id}`);
      expect(screen.getByText('Python')).toBeVisible();
      expect(screen.getByText('Not provided')).toBeVisible();
    },
  );
  it('shows empty scope and no create action for an unassigned engineer', async () => {
    mount({ ...user, portfolioAccess: [] }, '/applications', page([]));
    expect(await screen.findByText('No applications available in your scope.')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Create application' })).not.toBeInTheDocument();
  });
  it('preserves URL filters and pagination and handles loading/error/retry/empty', async () => {
    const fetch = mount(user, '/applications?search=Pay&criticality=High');
    await screen.findByRole('link', { name: 'Payment API' });
    expect(screen.getByLabelText('Search names')).toHaveValue('Pay');
    let done!: (response: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; }));
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    expect(screen.getByText('Loading applications…')).toBeVisible();
    await act(async () => done(json({ error: { code: 'INVALID_FILTER', message: 'Invalid filters' } }, 400)));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid filters');
    fetch.mockResolvedValueOnce(json(page([], 0)));
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No applications match these filters.')).toBeVisible();
    fetch.mockResolvedValueOnce(json(page([application], 60)));
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await screen.findByText('Page 1 of 3 · 60 results');
    fetch.mockResolvedValueOnce(json(page([application], 60, 2)));
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Page 2 of 3 · 60 results');
    expect(String(fetch.mock.calls.at(-1)?.[0])).toContain('page=2');
  });
  it('validates complete fields and bounds, traps focus and restores the create trigger', async () => {
    const fetch = mount();
    fetch.mockResolvedValueOnce(json(page([portfolio])));
    const trigger = await screen.findByRole('button', { name: 'Create application' });
    await userEvent.click(trigger);
    await screen.findByRole('option', { name: 'Payments' });
    expect(screen.getByLabelText('Name', { exact: true })).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await userEvent.click(screen.getByRole('button', { name: 'Save application' }));
    expect(screen.getByLabelText('Name', { exact: true })).toHaveAttribute('aria-invalid', 'true');
    await fill();
    await userEvent.clear(screen.getByLabelText('Quality score'));
    await userEvent.type(screen.getByLabelText('Quality score'), '101');
    await userEvent.type(screen.getByLabelText('Repository URL'), 'javascript:alert(1)');
    await userEvent.click(screen.getByRole('button', { name: 'Save application' }));
    expect(screen.getByText('Use an integer from 0 to 100')).toBeVisible();
    expect(screen.getByText('Enter a valid HTTP or HTTPS URL')).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(3);
    await userEvent.keyboard('{Escape}');
    expect(trigger).toHaveFocus();
    expect(document.body.style.overflow).toBe('');
  });
  it('retains create values on conflict and saves exact complete typed fields after pending success', async () => {
    const fetch = mount();
    fetch.mockResolvedValueOnce(json(page([portfolio])));
    await userEvent.click(await screen.findByRole('button', { name: 'Create application' }));
    await screen.findByRole('option', { name: 'Payments' });
    await fill();
    fetch.mockResolvedValueOnce(json({ error: { code: 'CONFLICT', message: 'Duplicate application' } }, 409));
    await userEvent.click(screen.getByRole('button', { name: 'Save application' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Duplicate application');
    let done!: (response: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; })).mockResolvedValueOnce(json(page()));
    await userEvent.click(screen.getByRole('button', { name: 'Save application' }));
    expect(screen.getByRole('button', { name: 'Save application' })).toBeDisabled();
    const body = JSON.parse(fetch.mock.calls.at(-1)?.[1]?.body as string);
    expect(Object.keys(body).sort()).toEqual(Object.keys(applicationLabels).sort());
    expect(body.qualityScore).toBe(0); expect(body.pipelineUrl).toBeNull();
    expect(new Headers(fetch.mock.calls.at(-1)?.[1]?.headers).get('Authorization')).toBe('Bearer test-token');
    await act(async () => done(json(application, 201)));
    expect(await screen.findByText('Application created')).toBeVisible();
  });
  it('edits with expected timestamp and keeps values on audit failure before successful refresh', async () => {
    const fetch = mount(user, `/applications/${application.id}`, application);
    fetch.mockResolvedValueOnce(json(page([portfolio])));
    await userEvent.click(await screen.findByRole('button', { name: 'Edit application' }));
    await screen.findByRole('option', { name: 'Payments' });
    await userEvent.clear(screen.getByLabelText('Quality score'));
    await userEvent.type(screen.getByLabelText('Quality score'), '83');
    fetch.mockResolvedValueOnce(json({ error: { code: 'AUDIT_WRITE_FAILED', message: 'Audit failed' } }, 503));
    await userEvent.click(screen.getByRole('button', { name: 'Save application' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Audit failed');
    expect(JSON.parse(fetch.mock.calls.at(-1)?.[1]?.body as string).expectedUpdatedAt).toBe(application.updatedAt);
    expect(screen.getByLabelText('Quality score')).toHaveValue(83);
    fetch.mockResolvedValueOnce(json({ ...application, qualityScore: 83 })).mockResolvedValueOnce(json({ ...application, qualityScore: 83 }));
    await userEvent.click(screen.getByRole('button', { name: 'Save application' }));
    expect(await screen.findByText('Application updated')).toBeVisible();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('requires admin confirmation and retains dialog on stale deletion then navigates after success', async () => {
    const fetch = mount({ ...user, role: 'Administrator' }, `/applications/${application.id}`, application);
    await userEvent.click(await screen.findByRole('button', { name: 'Delete application' }));
    fetch.mockResolvedValueOnce(json({ error: { code: 'CONFLICT', message: 'Stale version' } }, 409));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Stale version');
    expect(String(fetch.mock.calls.at(-1)?.[0])).toContain('expectedUpdatedAt=');
    fetch.mockResolvedValueOnce(json({ deleted: true, id: application.id })).mockResolvedValueOnce(json(page([])));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
    expect(await screen.findByText('No applications available in your scope.')).toBeVisible();
  });
  it('retries hidden detail failure and resolves completed application landing preferences', async () => {
    const fetch = mount(user, `/applications/${application.id}`, { error: { code: 'NOT_FOUND', message: 'Application not found' } }, 404);
    expect(await screen.findByRole('alert')).toHaveTextContent('Application not found');
    fetch.mockResolvedValueOnce(json(application));
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('heading', { name: 'Payment API' })).toBeVisible();
  });
  it('restores completed application landing preference', async () => {
    mount({ ...user, defaultLandingPage: 'applications' }, '/login');
    expect(await screen.findByRole('heading', { name: 'Applications' })).toBeVisible();
  });
});
