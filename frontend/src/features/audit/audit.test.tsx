/** Exercise real audit client decoding, URL state and role-only navigation. */
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { SessionProvider } from '../auth/SessionProvider';
import { AppRoutes } from '../../routes';
import { TOKEN_KEY } from '../../lib/api';
import { auditApi } from './auditApi';
import type { SafeUser, AuditRow } from '../../types';

const auditor: SafeUser = { id: '65b000000000000000000001', name: 'Test Auditor', email: 'audit@example.com',
  role: 'Auditor', portfolioAccess: [], status: 'Active', defaultLandingPage: null, mustChangePassword: false };
const row: AuditRow = { id: '65b500000000000000000001', timestamp: '2026-01-01T00:00:00Z', userId: null,
  userName: 'Unknown account', action: 'login', entityType: 'user', entityId: null, details: 'Sign-in failed' };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const page = (items = [row], current = 1, total = 11) => ({ items, page: current, pageSize: 10, total });

/** Mount the actual session/router/client with only the network boundary mocked. */
function mount(user = auditor, entry = '/audit', response = json(page())) {
  localStorage.setItem(TOKEN_KEY, 'audit-token');
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json(user)).mockResolvedValueOnce(response);
  render(
    <MemoryRouter initialEntries={[entry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </MemoryRouter>,
  );
  return fetch;
}

describe('Audit history', () => {
  it.each(['Auditor', 'Administrator'] as const)('renders safe rows and accessible incoming navigation for %s', async (role) => {
    const fetch = mount({ ...auditor, role });
    expect(await screen.findByRole('table', { name: 'Audit events' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Audit history' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('Unknown account')).toBeVisible();
    expect(screen.getAllByText('—')).toHaveLength(2);
    expect(screen.getByText('Sign-in failed')).toBeVisible();
    expect(screen.getAllByRole('columnheader')).toHaveLength(7);
    expect(fetch.mock.calls[1][0]).toBe('/api/audit-logs?');
    expect(new Headers(fetch.mock.calls[1][1]?.headers).get('Authorization')).toBe('Bearer audit-token');
  });
  it.each(['Executive','Engineer','Portfolio Leader','Read Only'] as const)('denies %s direct entry and hides audit navigation without history requests', async (role) => {
    const fetch = mount({ ...auditor, role });
    await screen.findByRole('heading', { name: 'Authenticated session' });
    expect(screen.queryByRole('link', { name: 'Audit history' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Export CSV' })).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('hydrates URL filters, narrows all criteria, retains them in pagination and clears explicitly', async () => {
    const fetch = mount(auditor, `/audit?userId=${auditor.id}&action=edit&from=2026-01-01T00%3A00%3A00Z&to=2026-01-03T00%3A00%3A00Z&pageSize=10`);
    await screen.findByRole('table');
    expect(screen.getByLabelText('User ID')).toHaveValue(auditor.id);
    expect(screen.getByLabelText('Action')).toHaveValue('edit');
    expect(screen.getByLabelText('From (UTC or offset)')).toHaveValue('2026-01-01T00:00:00Z');
    fetch.mockResolvedValueOnce(json(page([row],2)));
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText('Page 2 of 2 · 11 results')).toBeVisible();
    let requested = new URL(String(fetch.mock.calls[2][0]), 'http://test');
    expect(requested.searchParams.get('page')).toBe('2');
    expect(requested.searchParams.get('action')).toBe('edit');
    expect(requested.searchParams.get('to')).toBe('2026-01-03T00:00:00Z');
    await userEvent.selectOptions(screen.getByLabelText('Action'), 'login');
    fetch.mockResolvedValueOnce(json(page([],1,0)));
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    expect(await screen.findByText('No audit events match these filters.')).toBeVisible();
    requested = new URL(String(fetch.mock.calls[3][0]), 'http://test');
    expect(requested.searchParams.get('page')).toBe('1');
    expect(requested.searchParams.get('userId')).toBe(auditor.id);
    expect(requested.searchParams.get('action')).toBe('login');
    fetch.mockResolvedValueOnce(json(page()));
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await screen.findByRole('table');
    expect(fetch.mock.calls[4][0]).toBe('/api/audit-logs?');
    expect(screen.getByLabelText('User ID')).toHaveValue('');
  });
  it('shows pending read, safe failure and retry without stale table data', async () => {
    const fetch = mount(auditor, '/audit', json({ error: { message: 'Invalid audit filters' } }, 400));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid audit filters');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    let done!: (value: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; }));
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(screen.getByText('Loading audit history…')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Export CSV' })).toBeDisabled();
    await act(async () => done(json(page())));
    expect(await screen.findByRole('table')).toBeVisible();
  });
  it('starts real blob download with matching filters and shows pending/success feedback', async () => {
    const fetch = mount(auditor, '/audit?action=edit&page=2&pageSize=10');
    await screen.findByRole('table');
    const create = vi.fn((_blob: Blob) => 'blob:audit');
    const revoke = vi.fn();
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    let anchor: HTMLAnchorElement | null = null;
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { anchor = this; });
    let done!: (value: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; }));
    await userEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    expect(screen.getByRole('button', { name: 'Exporting CSV…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Apply filters' })).toBeDisabled();
    expect(fetch.mock.calls[2][0]).toBe('/api/audit-logs?action=edit&page=2&pageSize=10&format=csv');
    expect(new Headers(fetch.mock.calls[2][1]?.headers).get('Authorization')).toBe('Bearer audit-token');
    await act(async () => done(new Response('timestamp,userId\r\n', { headers: { 'Content-Type': 'text/csv; charset=utf-8' } })));
    expect(await screen.findByText('CSV download started')).toBeVisible();
    expect(create.mock.calls[0][0]).toBeInstanceOf(Blob);
    expect(anchor!.download).toBe('audit-history.csv');
    expect(anchor!.getAttribute('href')).toBe('blob:audit');
    expect(document.querySelector('a[download]')).toBeNull();
    await waitFor(() => expect(revoke).toHaveBeenCalledWith('blob:audit'), { timeout: 2000 });
  });
  it.each([403,503])('shows export failure %s without claiming download and allows retry', async (status) => {
    const fetch = mount();
    await screen.findByRole('table');
    fetch.mockResolvedValueOnce(json({ error: { message: 'Export unavailable' } }, status));
    await userEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Export unavailable');
    expect(screen.queryByText('CSV download started')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export CSV' })).toBeEnabled();
  });
  it('routes the completed audit landing preference through login entry', async () => {
    mount({ ...auditor, defaultLandingPage: 'audit' }, '/login');
    expect(await screen.findByRole('table')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Audit history' })).toBeVisible();
  });
  it('clears invalid session when CSV export returns 401', async () => {
    const fetch = mount();
    await screen.findByRole('table');
    fetch.mockResolvedValueOnce(json({ error: { message: 'Unable to authenticate' } }, 401));
    await userEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeVisible();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });
  it('rejects network failure, malformed errors and successful non-CSV responses', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('network'));
    await expect(auditApi.download(new URLSearchParams())).rejects.toThrow('Unable to reach the service');
    fetch.mockResolvedValueOnce(new Response('not json', { status: 503 }));
    await expect(auditApi.download(new URLSearchParams())).rejects.toThrow('Export failed');
    fetch.mockResolvedValueOnce(json({ items: [] }));
    await expect(auditApi.download(new URLSearchParams())).rejects.toThrow('did not return CSV');
  });
});
