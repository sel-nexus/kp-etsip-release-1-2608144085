/** Verify real profile client contracts and user-visible form transitions. */
import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { SessionProvider } from '../auth/SessionProvider';
import { AppRoutes } from '../../routes';
import { TOKEN_KEY } from '../../lib/api';
import type { SafeUser } from '../../types';
const identity: SafeUser = { id: '65b000000000000000000001', name: 'Profile Engineer', email: 'profile@example.com', role: 'Engineer', portfolioAccess: [], status: 'Active', defaultLandingPage: null, mustChangePassword: false };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const mount = (user = identity, entry = '/profile') => {
  localStorage.setItem(TOKEN_KEY, 'profile-token');
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json(user));
  render(
    <MemoryRouter initialEntries={[entry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </MemoryRouter>,
  );
  return fetch;
};
const fillPasswords = async (current = 'old', replacement = 'new', confirm = replacement) => {
  await userEvent.type(screen.getByLabelText('Current password'), current);
  await userEvent.type(screen.getByLabelText('New password'), replacement);
  await userEvent.type(screen.getByLabelText('Confirm new password'), confirm);
};
describe('Profile and first-password gate', () => {
  it('displays safe access and only completed navigation with role-bounded preferences', async () => {
    mount();
    expect(await screen.findByText(identity.name)).toBeVisible();
    expect(screen.getByText(identity.email)).toBeVisible();
    expect(screen.getByText('No portfolio access')).toBeVisible();
    expect(screen.getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual(['/', '/', '/profile', '/portfolios']);
    expect(screen.queryByRole('option', { name: 'Users' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Audit' })).not.toBeInTheDocument();
  });
  it('shows administrator all-portfolio access and additional supported preference keys', async () => {
    mount({ ...identity, role: 'Administrator' });
    expect(await screen.findByText('All portfolios')).toBeVisible();
    expect(screen.getByRole('option', { name: 'Users' })).toBeVisible();
    expect(screen.getByRole('option', { name: 'Roles' })).toBeVisible();
    expect(screen.getByRole('option', { name: 'Audit' })).toBeVisible();
  });
  it('validates required credentials and matching confirmation without a write', async () => {
    const fetch = mount();
    await screen.findByRole('heading', { name: 'My profile' });
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(screen.getAllByText('Password is required')).toHaveLength(2);
    expect(screen.getByText('Confirm your new password')).toBeVisible();
    expect(screen.getByLabelText('Current password')).toHaveAttribute('aria-invalid', 'true');
    await fillPasswords('old', 'new', 'different');
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(screen.getByText('Passwords do not match')).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('rejects passwords beyond the UTF-8 bcrypt limit', async () => {
    const fetch = mount();
    await screen.findByRole('heading', { name: 'My profile' });
    await fillPasswords('old', 'é'.repeat(37));
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(screen.getByText(/Use a password supported by bcrypt/)).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([403, 503])('keeps forced gate on password failure %s and clears submitted secrets', async (status) => {
    const fetch = mount({ ...identity, mustChangePassword: true }, '/profile');
    await screen.findByRole('heading', { name: 'Secure your account' });
    expect(screen.queryByRole('link', { name: 'My profile' })).not.toBeInTheDocument();
    fetch.mockResolvedValueOnce(json({ error: { code: status === 403 ? 'FORBIDDEN' : 'AUDIT_WRITE_FAILED', message: 'Password update failed', fields: {} } }, status));
    await fillPasswords();
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByText('Password update failed')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Secure your account' })).toBeVisible();
    for (const label of ['Current password', 'New password', 'Confirm new password']) expect(screen.getByLabelText(label)).toHaveValue('');
    expect(localStorage.getItem(TOKEN_KEY)).toBe('profile-token');
  });
  it('shows pending state and unlocks navigation only after persisted safe password result', async () => {
    const fetch = mount({ ...identity, mustChangePassword: true }, '/');
    await screen.findByRole('heading', { name: 'Secure your account' });
    let done!: (response: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; }));
    await fillPasswords();
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(screen.getByRole('button', { name: 'Changing password…' })).toBeDisabled();
    expect(screen.getByText('Updating credentials…')).toBeVisible();
    expect(screen.queryByRole('link', { name: 'My profile' })).not.toBeInTheDocument();
    const options = fetch.mock.calls[1][1];
    expect(options?.method).toBe('POST');
    expect(JSON.parse(options?.body as string)).toEqual({ currentPassword: 'old', newPassword: 'new' });
    expect(new Headers(options?.headers).get('Authorization')).toBe('Bearer profile-token');
    await act(async () => done(json(identity)));
    expect(await screen.findByRole('heading', { name: 'Authenticated session' })).toBeVisible();
    await userEvent.click(screen.getByRole('link', { name: 'My profile' }));
    expect(await screen.findByRole('heading', { name: 'My profile' })).toBeVisible();
  });
  it('confirms voluntary password success and resets all credentials', async () => {
    const fetch = mount();
    await screen.findByRole('heading', { name: 'My profile' });
    fetch.mockResolvedValueOnce(json(identity));
    await fillPasswords();
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByText('Password changed')).toBeVisible();
    expect(screen.getByLabelText('New password')).toHaveValue('');
  });
  it('saves future landing keys with pending, success and retained session state', async () => {
    const fetch = mount();
    await screen.findByRole('heading', { name: 'My profile' });
    await userEvent.selectOptions(screen.getByLabelText('Default landing page'), 'reports');
    let done!: (response: Response) => void;
    fetch.mockImplementationOnce(() => new Promise((resolve) => { done = resolve; }));
    await userEvent.click(screen.getByRole('button', { name: 'Save preference' }));
    expect(screen.getByRole('button', { name: 'Saving preference…' })).toBeDisabled();
    expect(fetch.mock.calls[1][0]).toBe('/api/auth/preferences');
    expect(fetch.mock.calls[1][1]?.method).toBe('PUT');
    expect(JSON.parse(fetch.mock.calls[1][1]?.body as string)).toEqual({ defaultLandingPage: 'reports' });
    await act(async () => done(json({ ...identity, defaultLandingPage: 'reports' })));
    expect(await screen.findByText('Preference saved')).toBeVisible();
    await userEvent.click(screen.getByRole('link', { name: /^Session$/ }));
    await userEvent.click(screen.getByRole('link', { name: 'My profile' }));
    expect(screen.getByLabelText('Default landing page')).toHaveValue('reports');
    expect(screen.queryByRole('link', { name: 'Reports' })).not.toBeInTheDocument();
  });
  it('shows preference denial and permits retry without claiming success', async () => {
    const fetch = mount();
    await screen.findByRole('heading', { name: 'My profile' });
    fetch.mockResolvedValueOnce(json({ error: { code: 'FORBIDDEN', message: 'Permission denied', fields: {} } }, 403));
    await userEvent.selectOptions(screen.getByLabelText('Default landing page'), 'reports');
    await userEvent.click(screen.getByRole('button', { name: 'Save preference' }));
    expect(await screen.findByText('Permission denied')).toBeVisible();
    expect(screen.queryByText('Preference saved')).not.toBeInTheDocument();
    fetch.mockResolvedValueOnce(json({ ...identity, defaultLandingPage: 'profile' }));
    await userEvent.selectOptions(screen.getByLabelText('Default landing page'), 'profile');
    await userEvent.click(screen.getByRole('button', { name: 'Save preference' }));
    expect(await screen.findByText('Preference saved')).toBeVisible();
  });
  it('clears session on a password request 401', async () => {
    const fetch = mount();
    await screen.findByRole('heading', { name: 'My profile' });
    fetch.mockResolvedValueOnce(json({ error: { code: 'UNAUTHENTICATED', message: 'Unable to authenticate', fields: {} } }, 401));
    await fillPasswords();
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeVisible();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });
});
