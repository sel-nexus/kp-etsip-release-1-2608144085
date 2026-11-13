/** Verify user administration interactions through real routes and client contracts. */
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { SessionProvider } from '../auth/SessionProvider';
import { AppRoutes } from '../../routes';
import { TOKEN_KEY } from '../../lib/api';
import { availablePortfolios } from './userApi';
import { UserForm } from './UserForm';
import type { AdminUser, SafeUser, Portfolio } from '../../types';
const identity: SafeUser = { id: '65b000000000000000000001', name: 'Admin', email: 'admin@example.com', role: 'Administrator',
  portfolioAccess: [], status: 'Active', defaultLandingPage: null, mustChangePassword: false };
const account: AdminUser = { id: '65b300000000000000000001', name: 'Demo Account', email: 'demo@example.com', role: 'Engineer',
  portfolioAccess: [], status: 'Active', managerName: null, vendorIndicator: false, lastLogin: null, authSource: 'local',
  mustChangePassword: false, createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z' };
const portfolio: Portfolio = { id: '65b100000000000000000001', name: 'Payments', status: 'Active', ownerName: 'Owner',
  description: 'Test', productArea: 'Test', applicationCount: 0, qualityScore: null, createdAt: account.createdAt, updatedAt: account.updatedAt };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const page = (items: unknown[] = [account], total = items.length, number = 1) => ({ items, total, page: number, pageSize: 25 });
/** Expose shareable URL state without accessing component internals. */
function Location() {
  const location = useLocation();
  return <output aria-label="URL">{location.pathname}{location.search}</output>;
}
/** Mount the actual shell, session, account router and HTTP client. */
function mount(user = identity, entry = '/users', response: unknown = page()) {
  localStorage.setItem(TOKEN_KEY, 'test-token');
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json(user)).mockResolvedValueOnce(json(response));
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
/** Fill creation fields using accessible labels. */
async function fillCreate() {
  await userEvent.type(screen.getByLabelText('Name', { exact: true }), 'New Account');
  await userEvent.type(screen.getByLabelText('Email', { exact: true }), 'NEW@example.com');
  await userEvent.type(screen.getByLabelText('Initial password'), 'test-secret');
}
describe('User administration', () => {
  it('returns all assignment pages through the real client, including an empty inventory', async () => {
    const later = { ...portfolio, id: '65b100000000000000000002', name: 'Later portfolio' };
    localStorage.setItem(TOKEN_KEY, 'test-token');
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json({ ...page([portfolio], 2), pageSize: 100 }))
      .mockResolvedValueOnce(json({ ...page([later], 2, 2), pageSize: 100 }));
    await expect(availablePortfolios()).resolves.toEqual([portfolio, later]);
    expect(fetch.mock.calls.map(([url]) => new URL(String(url), 'http://test').search)).toEqual([
      '?page=1&pageSize=100', '?page=2&pageSize=100',
    ]);
    for (const [, init] of fetch.mock.calls) expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer test-token');
    fetch.mockResolvedValueOnce(json(page([])));
    await expect(availablePortfolios()).resolves.toEqual([]);
    expect(fetch).toHaveBeenCalledTimes(3);
  });
  it.each([1, 2])('rejects inconsistent empty assignment page %s without returning partial results or requesting another page', async (emptyPage) => {
    const fetch = vi.spyOn(globalThis, 'fetch');
    if (emptyPage === 2) fetch.mockResolvedValueOnce(json(page([portfolio], 2)));
    fetch.mockResolvedValueOnce(json(page([], 2, emptyPage)));
    await expect(availablePortfolios()).rejects.toThrow('Portfolio inventory changed. Retry loading assignments.');
    expect(fetch).toHaveBeenCalledTimes(emptyPage);
    expect(String(fetch.mock.calls.at(-1)?.[0])).toContain(`page=${emptyPage}&pageSize=100`);
  });
  it('keeps assignment writes blocked until all pages load and submits both selected portfolios', async () => {
    const later = { ...portfolio, id: '65b100000000000000000002', name: 'Later portfolio' };
    let done!: (response: Response) => void;
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json(page([portfolio], 2)))
      .mockImplementationOnce(() => new Promise((resolve) => { done = resolve; }));
    const saved = vi.fn();
    render(<UserForm onSaved={saved} onCancel={vi.fn()} />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(screen.getByText('Loading available portfolios…')).toBeVisible();
    expect(screen.queryByLabelText('Payments (Active)')).not.toBeInTheDocument();
    await fillCreate();
    const save = screen.getByRole('button', { name: 'Save user' });
    expect(save).toBeDisabled();
    await userEvent.click(save);
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST' || init?.method === 'PUT')).toEqual([]);
    expect(saved).not.toHaveBeenCalled();
    await act(async () => done(json(page([later], 2, 2))));
    expect(screen.queryByText('Loading available portfolios…')).not.toBeInTheDocument();
    expect(save).toBeEnabled();
    await userEvent.click(screen.getByLabelText('Payments (Active)'));
    await userEvent.click(screen.getByLabelText('Later portfolio (Active)'));
    expect(screen.getByLabelText('Payments (Active)')).toBeChecked();
    expect(screen.getByLabelText('Later portfolio (Active)')).toBeChecked();
    fetch.mockResolvedValueOnce(json(account, 201));
    await userEvent.click(save);
    await waitFor(() => expect(saved).toHaveBeenCalledWith(account));
    expect(fetch.mock.calls[2][1]?.method).toBe('POST');
    expect(JSON.parse(fetch.mock.calls[2][1]?.body as string)).toEqual({ name: 'New Account', email: 'new@example.com',
      password: 'test-secret', role: 'Engineer', portfolioAccess: [portfolio.id, later.id], status: 'Active', managerName: null, vendorIndicator: false });
  });
  it.each(['service failure', 'inconsistent empty page'])('shows safe feedback for later assignment %s and preserves fields through retry', async (failure) => {
    const message = failure === 'service failure' ? 'Portfolio unavailable' : 'Portfolio inventory changed. Retry loading assignments.';
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json(page([portfolio], 2)))
      .mockResolvedValueOnce(failure === 'service failure' ? json({ error: { message } }, 503) : json(page([], 2, 2)));
    const saved = vi.fn();
    render(<UserForm onSaved={saved} onCancel={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.queryByText('No available portfolios.')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Payments (Active)')).not.toBeInTheDocument();
    await fillCreate();
    const save = screen.getByRole('button', { name: 'Save user' });
    expect(save).toBeDisabled();
    await userEvent.click(save);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST' || init?.method === 'PUT')).toEqual([]);
    expect(saved).not.toHaveBeenCalled();
    let done!: (response: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; }));
    await userEvent.click(screen.getByRole('button', { name: 'Retry portfolios' }));
    expect(screen.getByText('Loading available portfolios…')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(save).toBeDisabled();
    expect(String(fetch.mock.calls[2][0])).toContain('page=1&pageSize=100');
    await act(async () => done(json(page([portfolio]))));
    expect(save).toBeEnabled();
    expect(screen.getByLabelText('Name', { exact: true })).toHaveValue('New Account');
    expect(screen.getByLabelText('Initial password')).toHaveValue('test-secret');
    await userEvent.click(screen.getByLabelText('Payments (Active)'));
    fetch.mockResolvedValueOnce(json(account, 201));
    await userEvent.click(save);
    await waitFor(() => expect(saved).toHaveBeenCalledWith(account));
    expect(JSON.parse(fetch.mock.calls[3][1]?.body as string)).toMatchObject({ name: 'New Account', password: 'test-secret', portfolioAccess: [portfolio.id] });
  });
  it('renders safe detail, URL filters and pagination and return navigation', async () => {
    const fetch = mount(identity, '/users?search=Demo&role=Engineer&status=Active');
    await screen.findByRole('link', { name: account.name });
    expect(screen.getByRole('link', { name: /^Users$/ })).toBeVisible();
    expect(screen.getByLabelText('Filter role')).toHaveValue('Engineer');
    fetch.mockResolvedValueOnce(json(page([account], 60)));
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    await screen.findByText('Page 1 of 3 · 60 results');
    fetch.mockResolvedValueOnce(json(page([account], 60, 2)));
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Page 2 of 3 · 60 results');
    expect(screen.getByLabelText('URL')).toHaveTextContent('page=2');
    fetch.mockResolvedValueOnce(json(account));
    await userEvent.click(screen.getByRole('link', { name: account.name }));
    expect(await screen.findByRole('heading', { name: account.name })).toBeVisible();
    expect(screen.getByText('local')).toBeVisible();
    expect(screen.getByText('Not set')).toBeVisible();
    expect(screen.queryByLabelText('Initial password')).not.toBeInTheDocument();
    fetch.mockResolvedValueOnce(json(page()));
    await userEvent.click(screen.getByRole('link', { name: 'Back to users' }));
    await screen.findByRole('heading', { name: 'Users' });
    expect(screen.getByLabelText('URL')).toHaveTextContent('page=2');
  });
  it.each(['Engineer', 'Executive', 'Portfolio Leader', 'Auditor', 'Read Only'] as const)('denies %s UI navigation', async (role) => {
    mount({ ...identity, role });
    await screen.findByRole('heading', { name: 'Authenticated session' });
    expect(screen.queryByRole('link', { name: /^Users$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create user' })).not.toBeInTheDocument();
  });
  it('validates create fields, fetches assignments and shows pending/success state', async () => {
    const fetch = mount();
    await screen.findByRole('link', { name: account.name });
    fetch.mockResolvedValueOnce(json(page([portfolio])));
    await userEvent.click(screen.getByRole('button', { name: 'Create user' }));
    await screen.findByLabelText('Payments (Active)');
    await userEvent.click(screen.getByRole('button', { name: 'Save user' }));
    expect(screen.getByLabelText('Name', { exact: true })).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('Initial password is required')).toBeVisible();
    await fillCreate();
    await userEvent.click(screen.getByLabelText('Payments (Active)'));
    await userEvent.selectOptions(screen.getByLabelText('Role', { exact: true }), 'Portfolio Leader');
    let done!: (value: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; })).mockResolvedValueOnce(json(page()));
    await userEvent.click(screen.getByRole('button', { name: 'Save user' }));
    expect(screen.getByText('Saving account…')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Save user' })).toBeDisabled();
    const body = JSON.parse(fetch.mock.calls[3][1]?.body as string);
    expect(body).toEqual({ name: 'New Account', email: 'new@example.com', password: 'test-secret', role: 'Portfolio Leader',
      portfolioAccess: [portfolio.id], status: 'Active', managerName: null, vendorIndicator: false });
    expect(fetch.mock.calls[3][1]?.method).toBe('POST');
    await act(async () => done(json(account, 201)));
    expect(await screen.findByText('User created')).toBeVisible();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it.each(['a'.repeat(73), 'é'.repeat(36) + 'a'])('blocks passwords exceeding 72 UTF-8 bytes: %s', async (password) => {
    const fetch = mount();
    await screen.findByRole('link', { name: account.name });
    fetch.mockResolvedValueOnce(json(page([])));
    await userEvent.click(screen.getByRole('button', { name: 'Create user' }));
    await screen.findByText('No available portfolios.');
    await fillCreate();
    const input = screen.getByLabelText('Initial password');
    await userEvent.clear(input);
    await userEvent.type(input, password);
    await userEvent.click(screen.getByRole('button', { name: 'Save user' }));
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('Password exceeds bcrypt byte limit')).toBeVisible();
    expect(fetch.mock.calls).toHaveLength(3);
    await userEvent.clear(input);
    await userEvent.type(input, 'é'.repeat(36));
    fetch.mockResolvedValueOnce(json(account, 201)).mockResolvedValueOnce(json(page()));
    await userEvent.click(screen.getByRole('button', { name: 'Save user' }));
    expect(await screen.findByText('User created')).toBeVisible();
    expect(JSON.parse(fetch.mock.calls[3][1]?.body as string).password).toBe('é'.repeat(36));
  });
  it.each(['<script>window.usersXss=1</script>', '<img src=x onerror="window.usersXss=1">'])('renders account and search markup as inert text: %s', async (text) => {
    const alert = vi.spyOn(window, 'alert').mockImplementation(() => undefined);
    const row = { ...account, name: text, managerName: text };
    const fetch = mount(identity, '/users', page([row]));
    const link = await screen.findByRole('link', { name: text });
    expect(link.textContent).toBe(text);
    expect(link.childElementCount).toBe(0);
    await userEvent.type(screen.getByLabelText('Search names or emails'), text);
    fetch.mockResolvedValueOnce(json(page([row])));
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    await screen.findByRole('link', { name: text });
    expect(new URL(String(fetch.mock.calls[2][0]), 'http://test').searchParams.get('search')).toBe(text);
    expect(screen.getByLabelText('Search names or emails')).toHaveValue(text);
    fetch.mockResolvedValueOnce(json(row));
    await userEvent.click(screen.getByRole('link', { name: text }));
    const heading = await screen.findByRole('heading', { name: text });
    expect(heading.textContent).toBe(text);
    expect(heading.childElementCount).toBe(0);
    expect(document.querySelector('.identity-details')?.textContent).toContain(text);
    fetch.mockResolvedValueOnce(json(page([])));
    await userEvent.click(screen.getByRole('button', { name: `Edit ${text}` }));
    await screen.findByText('No available portfolios.');
    expect(screen.getByLabelText('Name', { exact: true })).toHaveValue(text);
    expect(screen.getByLabelText('Manager name')).toHaveValue(text);
    expect(document.querySelector('script, img, [onerror]')).toBeNull();
    expect(Reflect.get(window, 'usersXss')).toBeUndefined();
    expect(alert).not.toHaveBeenCalled();
  });
  it('edits role/access without any password and keeps fields on conflict', async () => {
    const fetch = mount();
    await screen.findByRole('link', { name: account.name });
    fetch.mockResolvedValueOnce(json(page([portfolio])));
    await userEvent.click(screen.getByRole('button', { name: 'Edit Demo Account' }));
    await screen.findByLabelText('Payments (Active)');
    expect(screen.queryByLabelText('Initial password')).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Role', { exact: true }), 'Read Only');
    await userEvent.click(screen.getByLabelText('Payments (Active)'));
    fetch.mockResolvedValueOnce(json({ error: { code: 'CONFLICT', message: 'Reload required' } }, 409));
    await userEvent.click(screen.getByRole('button', { name: 'Save user' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Reload required');
    const body = JSON.parse(fetch.mock.calls[3][1]?.body as string);
    expect(body.expectedUpdatedAt).toBe(account.updatedAt);
    expect(body.role).toBe('Read Only'); expect(body.portfolioAccess).toEqual([portfolio.id]);
    expect(body.password).toBeUndefined();
    expect(screen.getByLabelText('Role', { exact: true })).toHaveValue('Read Only');
    fetch.mockResolvedValueOnce(json(account)).mockResolvedValueOnce(json(page()));
    await userEvent.click(screen.getByRole('button', { name: 'Save user' }));
    expect(await screen.findByText('User updated')).toBeVisible();
  });
  it('requires deactivation confirmation and does not claim success on partial audit failure', async () => {
    const fetch = mount();
    await userEvent.click(await screen.findByRole('button', { name: 'Deactivate Demo Account' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Account history is retained');
    fetch.mockResolvedValueOnce(json({ error: { code: 'AUDIT_WRITE_FAILED', message: 'Audit unavailable' } }, 503));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm deactivate' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Audit unavailable');
    expect(screen.queryByText('User deactivated')).not.toBeInTheDocument();
    expect(fetch.mock.calls[2][1]?.method).toBe('DELETE');
    expect(String(fetch.mock.calls[2][0])).toContain('expectedUpdatedAt=');
    fetch.mockResolvedValueOnce(json({ deactivated: true, id: account.id })).mockResolvedValueOnce(json(page([{ ...account, status: 'Inactive' }])));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm deactivate' }));
    expect(await screen.findByText('User deactivated')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Deactivate Demo Account' })).not.toBeInTheDocument();
  });
  it('handles loading list failure retry and empty results', async () => {
    const fetch = mount();
    await screen.findByRole('link', { name: account.name });
    let done!: (value: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; }));
    await userEvent.type(screen.getByLabelText('Search names or emails'), 'Missing');
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    expect(screen.getByText('Loading users…')).toBeVisible();
    await act(async () => done(json({ error: { message: 'Unavailable' } }, 503)));
    expect(await screen.findByRole('alert')).toHaveTextContent('Unavailable');
    fetch.mockResolvedValueOnce(json(page([])));
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No users match these filters.')).toBeVisible();
    fetch.mockResolvedValueOnce(json(page()));
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await screen.findByRole('link', { name: account.name });
    expect(screen.getByLabelText('URL')).toHaveTextContent('/users');
  });
  it('blocks writes when assignment loading fails and permits retry', async () => {
    const fetch = mount();
    await screen.findByRole('link', { name: account.name });
    fetch.mockResolvedValueOnce(json({ error: { message: 'Portfolio unavailable' } }, 503));
    await userEvent.click(screen.getByRole('button', { name: 'Create user' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Portfolio unavailable');
    expect(screen.getByRole('button', { name: 'Save user' })).toBeDisabled();
    fetch.mockResolvedValueOnce(json(page([])));
    await userEvent.click(screen.getByRole('button', { name: 'Retry portfolios' }));
    await screen.findByText('No available portfolios.');
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('resolves the completed users landing preference', async () => {
    mount({ ...identity, defaultLandingPage: 'users' }, '/login');
    expect(await screen.findByRole('heading', { name: 'Users' })).toBeVisible();
  });
});
