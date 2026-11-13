/** Exercise UI actions and the real auth client at its HTTP boundary. */
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { SessionProvider } from './SessionProvider';
import { AppRoutes } from '../../routes';
import { authApi } from './authApi';
import { apiRequest, TOKEN_KEY, SESSION_EXPIRED } from '../../lib/api';
import type { SafeUser } from '../../types';
const identity: SafeUser = { id: '65b000000000000000000001', name: 'Test Engineer', email: 'engineer@example.com', role: 'Engineer', portfolioAccess: [], status: 'Active', defaultLandingPage: null, mustChangePassword: false };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const mount = () => render(
  <MemoryRouter initialEntries={['/']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <SessionProvider>
      <AppRoutes />
    </SessionProvider>
  </MemoryRouter>,
);
describe('Local session', () => {
  it('does not call login on render and validates required fields', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch');
    mount();
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(screen.getByText('Email is required')).toBeVisible();
    expect(screen.getByText('Password is required')).toBeVisible();
    expect(fetch).not.toHaveBeenCalled();
  });
  it('shows invalid email without a request', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch');
    mount();
    await userEvent.type(screen.getByLabelText('Email'), 'invalid');
    await userEvent.type(screen.getByLabelText('Password'), 'test-password');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(screen.getByText('Enter a valid email')).toBeVisible();
    expect(fetch).not.toHaveBeenCalled();
  });
  it('renders pending then backend identity, stores token, and signs out', async () => {
    let resolve!: (response: Response) => void;
    const fetch = vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    mount();
    await userEvent.type(screen.getByLabelText('Email'), identity.email);
    await userEvent.type(screen.getByLabelText('Password'), 'test-password');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(screen.getByRole('button', { name: 'Signing in…' })).toBeDisabled();
    expect(screen.getByText('Verifying credentials…')).toBeVisible();
    await act(async () => resolve(json({ token: 'backend-token', user: identity })));
    expect(await screen.findByText(identity.name)).toBeVisible();
    expect(screen.getByText(identity.role)).toBeVisible();
    expect(localStorage.getItem(TOKEN_KEY)).toBe('backend-token');
    fetch.mockResolvedValueOnce(json({ message: 'Signed out' }));
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeVisible();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(screen.queryByText(identity.name)).not.toBeInTheDocument();
  });
  it('restores identity on reload then clears it on protected 401', async () => {
    localStorage.setItem(TOKEN_KEY, 'stored-token');
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json(identity));
    mount();
    expect(await screen.findByText(identity.name)).toBeVisible();
    const headers = new Headers(fetch.mock.calls[0][1]?.headers);
    expect(headers.get('Authorization')).toBe('Bearer stored-token');
    fetch.mockResolvedValueOnce(json({ error: { code: 'UNAUTHENTICATED', message: 'Unable to authenticate', fields: {} } }, 401));
    await userEvent.click(screen.getByRole('button', { name: 'Refresh identity' }));
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeVisible();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });
  it('keeps a recoverable restore error and clears locally after failed logout', async () => {
    localStorage.setItem(TOKEN_KEY, 'stored-token');
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('offline'));
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to reach the service');
    expect(screen.getByRole('button', { name: 'Retry session' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeVisible();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });
  it('shows generic invalid login, clears password, and does not persist token', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ error: { code: 'UNAUTHENTICATED', message: 'Unable to authenticate', fields: {} } }, 401));
    mount();
    await userEvent.type(screen.getByLabelText('Email'), identity.email);
    await userEvent.type(screen.getByLabelText('Password'), 'bad-password');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to authenticate');
    expect(screen.getByLabelText('Password')).toHaveValue('');
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });
  it('never sends a stale token on login and excludes login 401 from expiration', async () => {
    localStorage.setItem(TOKEN_KEY, 'old-token');
    const expire = vi.fn();
    window.addEventListener(SESSION_EXPIRED, expire);
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ error: { code: 'UNAUTHENTICATED', message: 'Unable to authenticate', fields: {} } }, 401));
    await expect(authApi.login({ email: identity.email, password: 'wrong' })).rejects.toThrow('Unable to authenticate');
    expect(new Headers(fetch.mock.calls[0][1]?.headers).has('Authorization')).toBe(false);
    expect(localStorage.getItem(TOKEN_KEY)).toBe('old-token');
    expect(expire).not.toHaveBeenCalled();
    window.removeEventListener(SESSION_EXPIRED, expire);
  });
  it('returns a safe fallback for non-JSON server errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('invalid gateway output', { status: 503 }));
    await expect(apiRequest('/auth/me')).rejects.toThrow('Request failed. Try again.');
  });
  it('renders password gate without linking unimplemented routes', async () => {
    localStorage.setItem(TOKEN_KEY, 'stored-token');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ ...identity, mustChangePassword: true }));
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('Password change required');
    expect(screen.getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual(['/', '/']);
  });
});
