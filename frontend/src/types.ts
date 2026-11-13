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
  updateProfile: (operation: () => Promise<SafeUser>) => Promise<void>;
}

export type LandingPage = 'dashboard' | 'portfolios' | 'applications' | 'reports' | 'users' | 'roles' | 'audit' | 'profile';
export interface PasswordChange { currentPassword: string; newPassword: string }
export interface ProfilePreferences { defaultLandingPage: LandingPage }

export interface PortfolioWrite {
  name: string;
  ownerName: string;
  description: string;
  productArea: string;
  status: 'Active' | 'Archived';
}
export interface Portfolio extends PortfolioWrite {
  id: string;
  applicationCount: number;
  qualityScore: number | null;
  createdAt: string;
  updatedAt: string;
}
export interface RelatedApplication {
  id: string;
  name: string;
  criticality: 'Low' | 'Medium' | 'High' | 'Critical';
  tier: number;
  lifecycleStatus: 'Active' | 'Deprecated' | 'Retired';
  riskLevel: 'Low' | 'Medium' | 'High';
}
export interface Page<T> { items: T[]; page: number; pageSize: number; total: number }
export interface PortfolioDetail { portfolio: Portfolio; applications: RelatedApplication[] }

export interface ApplicationWrite {
  name: string;
  description: string;
  portfolioId: string;
  productArea: string;
  businessOwner: string;
  technologyOwner: string;
  etsOwner: string;
  criticality: RelatedApplication['criticality'];
  tier: number;
  lifecycleStatus: RelatedApplication['lifecycleStatus'];
  technologyStack: string;
  repositoryUrl: string | null;
  pipelineUrl: string | null;
  applicationHealthScore: number;
  qualityScore: number;
  automationCoverage: number;
  unitTestCoverage: number;
  openDefects: number;
  openCriticalDefects: number;
  riskLevel: RelatedApplication['riskLevel'];
}
export interface Application extends ApplicationWrite {
  id: string;
  createdAt: string;
  updatedAt: string;
}
export interface ApplicationDetail extends Application {
  portfolio: Pick<Portfolio, 'id' | 'name' | 'productArea' | 'status'>;
}

/** Share the full administration DTO without any credential fields. */
export interface AdminUser extends UserWrite {
  id: string;
  lastLogin: string | null;
  authSource: 'local';
  mustChangePassword: boolean;
  createdAt: string;
  updatedAt: string;
}
export interface UserWrite {
  name: string;
  email: string;
  role: RoleName;
  portfolioAccess: string[];
  status: 'Active' | 'Inactive';
  managerName: string | null;
  vendorIndicator: boolean;
}
export interface UserCreate extends UserWrite { password: string }
