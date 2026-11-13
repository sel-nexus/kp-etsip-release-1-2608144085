/** Exercise fixed-role navigation, bounds and optimistic write feedback. */
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { SessionProvider } from '../auth/SessionProvider';
import { AppRoutes } from '../../routes';
import { TOKEN_KEY } from '../../lib/api';
import { roleMaximum } from './roleApi';
import type { SafeUser, RoleDefinition, RoleName } from '../../types';
const admin: SafeUser = { id: '65b000000000000000000001', name: 'Admin', email: 'admin@example.com', role: 'Administrator',
  portfolioAccess: [], status: 'Active', defaultLandingPage: null, mustChangePassword: false };
const roles: RoleDefinition[] = (Object.keys(roleMaximum) as RoleName[]).map((name, index) => ({
  id: `65b40000000000000000000${index}`, name, description: `${name} definition`, permissions: [...roleMaximum[name]],
  createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z',
}));
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
/** Mount the real router and bearer client while isolating network calls. */
function mount(user = admin, items = roles, entry = '/roles') {
  localStorage.setItem(TOKEN_KEY, 'test-token');
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json(user)).mockResolvedValueOnce(json({ items }));
  render(
    <MemoryRouter initialEntries={[entry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </MemoryRouter>,
  );
  return fetch;
}
describe('Fixed role editor', () => {
  it('renders exactly six bounded forms and saves the observed version', async () => {
    const fetch = mount();
    await screen.findByRole('form', { name: 'Engineer permissions' });
    expect(screen.getByRole('link', { name: 'Roles' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getAllByRole('form')).toHaveLength(6);
    for (const role of roles) {
      const form = within(screen.getByRole('form', { name: `${role.name} permissions` }));
      expect(form.getAllByRole('checkbox')).toHaveLength(roleMaximum[role.name].length);
      expect(form.getByText(`Maximum allowed: ${roleMaximum[role.name].join(', ')}.`)).toBeVisible();
    }
    const engineer = roles.find((item) => item.name === 'Engineer')!;
    const form = within(screen.getByRole('form', { name: 'Engineer permissions' }));
    await userEvent.click(form.getByRole('checkbox', { name: /^edit$/ }));
    let done!: (value: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; }));
    await userEvent.click(form.getByRole('button', { name: 'Save Engineer permissions' }));
    expect(form.getByText('Saving permissions…')).toBeVisible();
    expect(form.getByRole('checkbox', { name: 'view' })).toBeDisabled();
    const options = fetch.mock.calls[2][1]!;
    expect(options.method).toBe('PUT');
    expect(JSON.parse(options.body as string)).toEqual({ permissions: ['view','create','export'], expectedUpdatedAt: engineer.updatedAt });
    expect(new Headers(options.headers).get('Authorization')).toBe('Bearer test-token');
    const updated = { ...engineer, permissions: ['view','create','export'], updatedAt: '2026-01-02T00:00:00Z' };
    await act(async () => done(json(updated)));
    expect(await form.findByText('Permissions saved')).toBeVisible();
    fetch.mockResolvedValueOnce(json({ ...updated, permissions: [] }));
    await userEvent.click(form.getByRole('button', { name: 'Save Engineer permissions' }));
    expect(JSON.parse(fetch.mock.calls[3][1]?.body as string).expectedUpdatedAt).toBe(updated.updatedAt);
  });
  it.each(['Engineer','Executive','Portfolio Leader','Auditor','Read Only'] as const)('hides roles navigation and rejects %s direct entry', async (role) => {
    mount({ ...admin, role });
    await screen.findByRole('heading', { name: 'Authenticated session' });
    expect(screen.queryByRole('link', { name: 'Roles' })).not.toBeInTheDocument();
    expect(screen.queryByRole('form')).not.toBeInTheDocument();
  });
  it.each([409, 503])('retains edits and requires reload after %s without claiming success', async (status) => {
    const fetch = mount();
    const form = within(await screen.findByRole('form', { name: 'Engineer permissions' }));
    await userEvent.click(form.getByRole('checkbox', { name: /^edit$/ }));
    fetch.mockResolvedValueOnce(json({ error: { code: status === 409 ? 'CONFLICT' : 'AUDIT_WRITE_FAILED', message: 'Reload required' } }, status));
    await userEvent.click(form.getByRole('button', { name: 'Save Engineer permissions' }));
    expect(await form.findByRole('alert')).toHaveTextContent('Reload required');
    expect(form.getByRole('checkbox', { name: /^edit$/ })).not.toBeChecked();
    expect(form.queryByText('Permissions saved')).not.toBeInTheDocument();
    expect(form.getByRole('button')).toBeDisabled();
    fetch.mockResolvedValueOnce(json({ items: roles }));
    await userEvent.click(screen.getByRole('button', { name: 'Reload roles' }));
    const fresh = within(await screen.findByRole('form', { name: 'Engineer permissions' }));
    expect(fresh.getByRole('checkbox', { name: /^edit$/ })).toBeChecked();
  });
  it('handles loading failure reload and missing baseline setup', async () => {
    const fetch = mount(admin, []);
    await screen.findByRole('button', { name: 'Ensure Engineer baseline' });
    expect(screen.getAllByRole('button', { name: /^Ensure/ })).toHaveLength(6);
    fetch.mockResolvedValueOnce(json(roles[3]));
    await userEvent.click(screen.getByRole('button', { name: 'Ensure Engineer baseline' }));
    await screen.findByRole('form', { name: 'Engineer permissions' });
    expect(fetch.mock.calls[2][1]?.method).toBe('POST');
    expect(JSON.parse(fetch.mock.calls[2][1]?.body as string)).toEqual({ name: 'Engineer' });
    let done!: (value: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; }));
    await userEvent.click(screen.getByRole('button', { name: 'Reload roles' }));
    expect(screen.getByText('Loading roles…')).toBeVisible();
    await act(async () => done(json({ error: { message: 'Unavailable' } }, 503)));
    expect(await screen.findByRole('alert')).toHaveTextContent('Unavailable');
    fetch.mockResolvedValueOnce(json({ items: roles }));
    await userEvent.click(screen.getByRole('button', { name: 'Reload roles' }));
    await screen.findByRole('form', { name: 'Engineer permissions' });
  });
  it('reports ensure failure without success and supports roles landing', async () => {
    const fetch = mount({ ...admin, defaultLandingPage: 'roles' }, [], '/login');
    await screen.findByRole('heading', { name: 'Roles' });
    fetch.mockResolvedValueOnce(json({ error: { message: 'Audit unavailable' } }, 503));
    await userEvent.click(screen.getByRole('button', { name: 'Ensure Engineer baseline' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Audit unavailable');
    expect(screen.queryByText('Engineer baseline ensured')).not.toBeInTheDocument();
  });
});
