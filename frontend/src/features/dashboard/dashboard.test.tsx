/** Verify executive rendering, URL filters, failures and obsolete-response safety. */
import { render, screen, act, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import DashboardPage from './DashboardPage';
import { SessionProvider } from '../auth/SessionProvider';
import { AppRoutes } from '../../routes';
import { TOKEN_KEY } from '../../lib/api';
import type { Dashboard, SafeUser } from '../../types';
const populated: Dashboard = {
  metrics: { enterpriseQualityScore: 80, averageApplicationHealthScore: 81, automationMaturityScore: 51,
    openCriticalDefects: 7, applicationsAtRisk: 1, totalApplications: 2, totalPortfolios: 4 },
  portfolioComparisons: [{ portfolioId: '65b100000000000000000001', name: 'Backend Payments', qualityScore: 80, applicationsAtRisk: 1 }],
};
const empty: Dashboard = { metrics: { enterpriseQualityScore: null, averageApplicationHealthScore: null, automationMaturityScore: null,
  openCriticalDefects: 0, applicationsAtRisk: 0, totalApplications: 0, totalPortfolios: 4 }, portfolioComparisons: [] };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
/** Expose browser-style history actions without testing component internal state. */
function HistoryControls() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <aside>
      <output aria-label="Current URL">{location.pathname}{location.search}</output>
      <button onClick={() => navigate(-1)}>Back</button>
      <button onClick={() => navigate(1)}>Forward</button>
    </aside>
  );
}
const mount = (entry = '/dashboard') => {
  localStorage.setItem(TOKEN_KEY, 'dashboard-token');
  render(
    <MemoryRouter initialEntries={[entry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <DashboardPage />
      <HistoryControls />
    </MemoryRouter>,
  );
};
const metric = (label: string) => within(screen.getByLabelText('Executive metrics')).getByText(label).parentElement!.querySelector('dd');
describe('Executive dashboard', () => {
  it('redirects an anonymous dashboard entry to sign in', async () => {
    localStorage.removeItem(TOKEN_KEY);
    render(
      <MemoryRouter initialEntries={['/dashboard']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SessionProvider>
          <AppRoutes />
        </SessionProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'Executive dashboard' })).not.toBeInTheDocument();
  });
  it('renders seven backend metrics and persisted comparison labels with accessible table headers', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(populated));
    mount();
    await screen.findByRole('table');
    expect(screen.getByLabelText('Executive metrics').querySelectorAll('dd')).toHaveLength(7);
    for (const [label, value] of [['Enterprise quality score', '80'], ['Average application health score', '81'],
      ['Automation maturity score', '51'], ['Open critical defects', '7'], ['Applications at risk', '1'],
      ['Total applications', '2'], ['Total portfolios', '4']]) expect(metric(label)).toHaveTextContent(value);
    expect(within(screen.getByRole('table')).getByRole('rowheader', { name: 'Backend Payments' })).toBeVisible();
    expect(screen.getAllByRole('columnheader')).toHaveLength(3);
    expect(fetch.mock.calls[0][0]).toBe('/api/dashboard/executive?');
    expect(new Headers(fetch.mock.calls[0][1]?.headers).get('Authorization')).toBe('Bearer dashboard-token');
  });
  it('renders unavailable empty averages without changing independent portfolio totals', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(empty));
    mount();
    expect(await screen.findByText('No portfolios to compare.')).toBeVisible();
    expect(screen.getAllByText('Not available')).toHaveLength(3);
    expect(metric('Total applications')).toHaveTextContent('0');
    expect(metric('Total portfolios')).toHaveTextContent('4');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('shows loading until the response arrives', async () => {
    let finish!: (value: Response) => void;
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    mount();
    expect(screen.getByText('Loading dashboard…')).toHaveAttribute('role', 'status');
    expect(screen.queryByLabelText('Executive metrics')).not.toBeInTheDocument();
    await act(async () => finish(json(populated)));
    expect(await screen.findByRole('table')).toBeVisible();
    expect(screen.queryByText('Loading dashboard…')).not.toBeInTheDocument();
  });
  it.each([400, 403, 503])('shows safe server error %s and retries successfully', async (status) => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json({ error: {
      code: 'FAILED', message: 'Dashboard unavailable', fields: {},
    } }, status)).mockResolvedValue(json(populated));
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('Dashboard unavailable');
    expect(screen.queryByLabelText('Executive metrics')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry dashboard' }));
    expect(await screen.findByRole('table')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('surfaces network failure and preserves invalid URL filters for backend validation', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('offline'));
    mount('/dashboard?portfolioId=bad&unknown=x&riskLevel=Low&riskLevel=High');
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to reach the service');
    expect(fetch.mock.calls[0][0]).toContain('unknown=x&riskLevel=Low&riskLevel=High');
    expect(screen.getByLabelText('Filter portfolio ID')).toHaveValue('bad');
  });
  it('applies all three filters in the URL and restores controls on back/forward and clear', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(populated));
    mount('/dashboard?productArea=Initial');
    await screen.findByRole('table');
    await userEvent.type(screen.getByLabelText('Filter portfolio ID'), populated.portfolioComparisons[0].portfolioId);
    await userEvent.clear(screen.getByLabelText('Product area'));
    await userEvent.type(screen.getByLabelText('Product area'), 'Payments');
    await userEvent.selectOptions(screen.getByLabelText('Risk level'), 'High');
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    await waitFor(() => expect(fetch.mock.calls.at(-1)?.[0]).toContain('portfolioId=65b100000000000000000001&productArea=Payments&riskLevel=High'));
    expect(screen.getByLabelText('Current URL')).toHaveTextContent('riskLevel=High');
    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByLabelText('Product area')).toHaveValue('Initial');
    expect(screen.getByLabelText('Filter portfolio ID')).toHaveValue('');
    await userEvent.click(screen.getByRole('button', { name: 'Forward' }));
    expect(screen.getByLabelText('Risk level')).toHaveValue('High');
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(screen.getByLabelText('Current URL')).toHaveTextContent('/dashboard');
    expect(screen.getByLabelText('Product area')).toHaveValue('');
  });
  it('does not let an obsolete response replace newly filtered data', async () => {
    let finish!: (value: Response) => void;
    vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValue(json(empty));
    mount();
    await userEvent.type(screen.getByLabelText('Product area'), 'No match');
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    await screen.findByText('No portfolios to compare.');
    await act(async () => finish(json(populated)));
    expect(metric('Total applications')).toHaveTextContent('0');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('exposes dashboard navigation after restored identity', async () => {
    const user: SafeUser = { id: '65b000000000000000000001', name: 'Dashboard Engineer', email: 'dash@example.com',
      role: 'Engineer', portfolioAccess: [], status: 'Active', defaultLandingPage: null, mustChangePassword: false };
    localStorage.setItem(TOKEN_KEY, 'dashboard-token');
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => json(String(url).includes('/auth/me') ? user : populated));
    render(
      <MemoryRouter initialEntries={['/profile']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SessionProvider>
          <AppRoutes />
        </SessionProvider>
      </MemoryRouter>,
    );
    await userEvent.click(await screen.findByRole('link', { name: 'Dashboard' }));
    expect(await screen.findByRole('heading', { name: 'Executive dashboard' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page');
  });
});
