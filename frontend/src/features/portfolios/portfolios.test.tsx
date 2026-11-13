/** Exercise portfolio UI behavior through the real HTTP client with component-level network stubs. */
import { act, render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { SessionProvider } from '../auth/SessionProvider';
import { AppRoutes } from '../../routes';
import { TOKEN_KEY } from '../../lib/api';
import type { Portfolio, SafeUser } from '../../types';
const user: SafeUser = {
  id: '65b000000000000000000001', name: 'Test Admin', email: 'admin@example.com', role: 'Administrator',
  portfolioAccess: [], status: 'Active', defaultLandingPage: null, mustChangePassword: false,
};
const portfolio: Portfolio = {
  id: '65b100000000000000000001', name: 'Payments', ownerName: 'Owner', description: 'Services',
  productArea: 'Finance', status: 'Active', applicationCount: 0, qualityScore: null,
  createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z',
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const page = (items = [portfolio], total = items.length, number = 1) => ({ items, page: number, pageSize: 25, total });
/** Expose navigable URL state in the test DOM. */
function Location() {
  const location = useLocation();
  return (
    <output aria-label="URL">{location.pathname}{location.search}</output>
  );
}
/** Mount the actual route, session and API layers. */
function mount(identity = user, entry = '/portfolios', response = page()) {
  localStorage.setItem(TOKEN_KEY, 'test-token');
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json(identity)).mockResolvedValueOnce(json(response));
  render(
    <MemoryRouter initialEntries={[entry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <SessionProvider>
        <AppRoutes />
        <Location />
      </SessionProvider>
    </MemoryRouter>,
  );
  return fetch;
}
/** Fill required business fields using their visible labels. */
async function fillForm() {
  await userEvent.type(screen.getByLabelText('Name'), 'New portfolio');
  await userEvent.type(screen.getByLabelText('Owner name'), 'New owner');
  await userEvent.type(screen.getByLabelText('Product area'), 'Area');
  await userEvent.type(screen.getByLabelText('Description'), 'Description');
}
describe('Portfolio inventory', () => {
  it('renders safe derived values, detail link and URL-backed AND filters/paging', async () => {
    const fetch = mount(user, '/portfolios?search=Pay&status=Active&productArea=Finance');
    expect(await screen.findByRole('link', { name: 'Payments' })).toHaveAttribute('href', `/portfolios/${portfolio.id}`);
    expect(screen.getByText('Not available')).toBeVisible();
    expect(screen.getByLabelText('Search names')).toHaveValue('Pay');
    expect(screen.getByLabelText('Filter status')).toHaveValue('Active');
    expect(screen.getByLabelText('Filter product area')).toHaveValue('Finance');
    fetch.mockResolvedValueOnce(json(page([portfolio], 60)));
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    await screen.findByText('Page 1 of 3 · 60 results');
    expect(screen.getByLabelText('URL').textContent).toContain('page=1');
    fetch.mockResolvedValueOnce(json(page([portfolio], 60, 2)));
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Page 2 of 3 · 60 results');
    expect(screen.getByLabelText('URL').textContent).toContain('page=2');
    fetch.mockResolvedValueOnce(json(page()));
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await screen.findByRole('link', { name: 'Payments' });
    expect(screen.getByLabelText('URL').textContent).toBe('/portfolios');
  });
  it.each(['Executive', 'Portfolio Leader', 'Engineer', 'Auditor', 'Read Only'] as const)(
    'keeps %s portfolio actions read-only', async (role) => {
      mount({ ...user, role });
      await screen.findByRole('link', { name: 'Payments' });
      expect(screen.queryByRole('button', { name: 'Create portfolio' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Edit Payments' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Delete Payments' })).not.toBeInTheDocument();
    },
  );
  it('covers loading, failed request, retry and scoped empty state', async () => {
    const fetch = mount();
    await screen.findByRole('link', { name: 'Payments' });
    let done!: (response: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; }));
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    // An unchanged URL does not refetch; change a filter to activate the pending request.
    await userEvent.type(screen.getByLabelText('Search names'), 'Missing');
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    expect(screen.getByText('Loading portfolios…')).toBeVisible();
    await act(async () => done(json({ error: { code: 'DEPENDENCY_UNAVAILABLE', message: 'Unavailable' } }, 503)));
    expect(await screen.findByRole('alert')).toHaveTextContent('Unavailable');
    fetch.mockResolvedValueOnce(json(page([])));
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No portfolios match these filters.')).toBeVisible();
    fetch.mockResolvedValueOnce(json(page([])));
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(await screen.findByText('No portfolios available in your scope.')).toBeVisible();
  });
  it('validates each create field, traps focus, closes by Escape and restores trigger focus', async () => {
    const fetch = mount();
    const trigger = await screen.findByRole('button', { name: 'Create portfolio' });
    await userEvent.click(trigger);
    expect(screen.getByLabelText('Name')).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByLabelText('Name')).toHaveFocus();
    await userEvent.click(screen.getByRole('button', { name: 'Save portfolio' }));
    expect(screen.getAllByText('This field is required')).toHaveLength(4);
    expect(screen.getByLabelText('Description')).toHaveAttribute('aria-invalid', 'true');
    expect(fetch).toHaveBeenCalledTimes(2);
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(document.body.style.overflow).toBe('');
  });
  it('shows create conflict then saves with pending and success feedback and exact write fields', async () => {
    const fetch = mount();
    await userEvent.click(await screen.findByRole('button', { name: 'Create portfolio' }));
    await fillForm();
    fetch.mockResolvedValueOnce(json({ error: { code: 'CONFLICT', message: 'Record already exists' } }, 409));
    await userEvent.click(screen.getByRole('button', { name: 'Save portfolio' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Record already exists');
    expect(screen.getByLabelText('Name')).toHaveValue('New portfolio');
    let done!: (response: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; })).mockResolvedValueOnce(json(page()));
    await userEvent.click(screen.getByRole('button', { name: 'Save portfolio' }));
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
    expect(JSON.parse(fetch.mock.calls[3][1]?.body as string)).toEqual({
      name: 'New portfolio', ownerName: 'New owner', productArea: 'Area', description: 'Description', status: 'Active',
    });
    expect(fetch.mock.calls[3][1]?.method).toBe('POST');
    await act(async () => done(json(portfolio, 201)));
    expect(await screen.findByText('Portfolio created')).toBeVisible();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('edits existing values with expectedUpdatedAt and preserves form on a stale failure', async () => {
    const fetch = mount();
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Payments' }));
    expect(screen.getByLabelText('Name')).toHaveValue('Payments');
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'Archived');
    fetch.mockResolvedValueOnce(json({ error: { code: 'CONFLICT', message: 'Reload and try again' } }, 409));
    await userEvent.click(screen.getByRole('button', { name: 'Save portfolio' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Reload and try again');
    expect(JSON.parse(fetch.mock.calls[2][1]?.body as string).expectedUpdatedAt).toBe(portfolio.updatedAt);
    fetch.mockResolvedValueOnce(json({ ...portfolio, status: 'Archived' })).mockResolvedValueOnce(json(page()));
    await userEvent.click(screen.getByRole('button', { name: 'Save portfolio' }));
    expect(await screen.findByText('Portfolio updated')).toBeVisible();
    expect(fetch.mock.calls[3][1]?.method).toBe('PUT');
  });
  it('requires confirmation, shows reference rejection and only claims delete success after HTTP success', async () => {
    const fetch = mount();
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Payments' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Referenced portfolios cannot be deleted');
    fetch.mockResolvedValueOnce(json({ error: { code: 'CONFLICT', message: 'Portfolio is referenced' } }, 409));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Portfolio is referenced');
    expect(screen.getByRole('dialog')).toBeVisible();
    expect(fetch.mock.calls[2][1]?.method).toBe('DELETE');
    expect(String(fetch.mock.calls[2][0])).toContain('expectedUpdatedAt=');
    fetch.mockResolvedValueOnce(json({ deleted: true, id: portfolio.id })).mockResolvedValueOnce(json(page([])));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
    expect(await screen.findByText('Portfolio deleted')).toBeVisible();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('clicks through detail with related summaries, no unfinished app link and return navigation', async () => {
    const fetch = mount();
    const app = { id: '65b200000000000000000001', name: 'Payment API', criticality: 'High', tier: 2, lifecycleStatus: 'Active', riskLevel: 'Low' };
    fetch.mockResolvedValueOnce(json({ portfolio, applications: [app] })).mockResolvedValueOnce(json({ ...page([], 1), items: [app] }));
    await userEvent.click(await screen.findByRole('link', { name: 'Payments' }));
    expect(await screen.findByRole('heading', { name: 'Payments' })).toBeVisible();
    expect(screen.getByText('Services')).toBeVisible();
    expect(screen.getByText('Payment API')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Payment API' })).toHaveAttribute('href', `/applications/${app.id}`);
    fetch.mockResolvedValueOnce(json(page()));
    await userEvent.click(screen.getByRole('link', { name: 'Back to portfolios' }));
    expect(await screen.findByRole('heading', { name: 'Portfolios' })).toBeVisible();
  });
  it('renders detail failure and retries to an empty related page', async () => {
    const fetch = mount();
    fetch.mockResolvedValueOnce(json({ error: { code: 'NOT_FOUND', message: 'Portfolio not found' } }, 404))
      .mockResolvedValueOnce(json({ error: { code: 'NOT_FOUND', message: 'Portfolio not found' } }, 404));
    await userEvent.click(await screen.findByRole('link', { name: 'Payments' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Portfolio not found');
    fetch.mockResolvedValueOnce(json({ portfolio, applications: [] })).mockResolvedValueOnce(json(page([])));
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No related applications on this page.')).toBeVisible();
  });
  it('resolves the completed portfolio landing preference on login restoration', async () => {
    mount({ ...user, defaultLandingPage: 'portfolios' }, '/login');
    expect(await screen.findByRole('heading', { name: 'Portfolios' })).toBeVisible();
    expect(screen.getByLabelText('URL')).toHaveTextContent('/portfolios');
  });
});
