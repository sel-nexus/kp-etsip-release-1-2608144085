/** Call only the implemented exact auth contracts. */
import { apiRequest } from '../../lib/api';
import type { LoginCredentials, LoginResult, SafeUser } from '../../types';
export const authApi = {
  /** Sign in publicly; never attach a stale bearer. */
  login: (credentials: LoginCredentials) => apiRequest<LoginResult>('/auth/login', { method: 'POST', body: JSON.stringify(credentials) }, false),
  /** Read the authoritative current identity using the stored token. */
  me: () => apiRequest<SafeUser>('/auth/me'),
  /** Confirm sign-out without claiming server-side token revocation. */
  logout: () => apiRequest<{ message: 'Signed out' }>('/auth/logout', { method: 'POST' }),
};
