/** Call approved profile endpoints through the shared bearer client. */
import { apiRequest } from '../../lib/api';
import type { PasswordChange, ProfilePreferences, SafeUser, LandingPage, RoleName } from '../../types';
export const profileApi = {
  /** Return persisted safe identity after a credential replacement. */
  changePassword: (request: PasswordChange) => apiRequest<SafeUser>('/auth/change-password', {
    method: 'POST', body: JSON.stringify(request),
  }),
  /** Persist a supported landing key without inventing an unfinished page. */
  savePreferences: (request: ProfilePreferences) => apiRequest<SafeUser>('/auth/preferences', {
    method: 'PUT', body: JSON.stringify(request),
  }),
};
/** Offer role-ceiling choices; the server additionally checks current stored permissions. */
export function landingChoices(role: RoleName): LandingPage[] {
  const choices: LandingPage[] = ['dashboard', 'portfolios', 'applications', 'reports', 'profile'];
  if (role === 'Administrator') choices.push('users', 'roles');
  if (role === 'Administrator' || role === 'Auditor') choices.push('audit');
  return choices;
}

/** Resolve only completed landing routes; unsupported pages retain the session entry. */
export function landingPath(preference: string | null): string {
  const completed: Record<string, string> = { profile: '/profile', portfolios: '/portfolios' };
  return preference ? completed[preference] ?? '/' : '/';
}
