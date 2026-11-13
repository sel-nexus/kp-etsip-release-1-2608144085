/** Share only public session contracts across client features. */
export type RoleName = 'Administrator' | 'Executive' | 'Portfolio Leader' | 'Engineer' | 'Auditor' | 'Read Only';
export interface SafeUser {
  id: string;
  name: string;
  email: string;
  role: RoleName;
  portfolioAccess: string[];
  status: 'Active' | 'Inactive';
  defaultLandingPage: string | null;
  mustChangePassword: boolean;
}
export interface LoginCredentials { email: string; password: string }
export interface LoginResult { token: string; user: SafeUser }
export interface ErrorEnvelope { error: { code: string; message: string; fields: Record<string, string> } }
export interface SessionContextValue {
  user: SafeUser | null;
  loading: boolean;
  error: string | null;
  login: (credentials: LoginCredentials) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}
