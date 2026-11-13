/** Call account endpoints through the sole bearer-aware client. */
import { apiRequest } from '../../lib/api';
import { portfolioApi } from '../portfolios/portfolioApi';
import type { AdminUser, UserWrite, UserCreate, Page, Portfolio } from '../../types';
export const supportedRoles = ['Administrator', 'Executive', 'Portfolio Leader', 'Engineer', 'Auditor', 'Read Only'] as const;
export const userApi = {
  /** Fetch bounded URL-backed account results. */
  list: (query: URLSearchParams) => apiRequest<Page<AdminUser>>(`/users?${query}`),
  /** Read complete safe account metadata. */
  detail: (id: string) => apiRequest<AdminUser>(`/users/${id}`),
  /** Submit an initial password only when creating a local account. */
  create: (body: UserCreate) => apiRequest<AdminUser>('/users', { method: 'POST', body: JSON.stringify(body) }),
  /** Compare the observed version before updating access. */
  update: (id: string, body: UserWrite, expectedUpdatedAt: string) => apiRequest<AdminUser>(`/users/${id}`, {
    method: 'PUT', body: JSON.stringify({ ...body, expectedUpdatedAt }),
  }),
  /** Deactivate without removing account history. */
  deactivate: (id: string, expectedUpdatedAt: string) => apiRequest<{ deactivated: true; id: string }>(
    `/users/${id}?${new URLSearchParams({ expectedUpdatedAt })}`, { method: 'DELETE' },
  ),
};
/** Fetch every bounded page of available portfolios for explicit assignment choices. */
export async function availablePortfolios(): Promise<Portfolio[]> {
  const rows: Portfolio[] = [];
  let page = 1;
  let total = 0;
  do {
    const result = await portfolioApi.list(new URLSearchParams({ page: String(page), pageSize: '100' }));
    if (result.items.length === 0 && rows.length < result.total) throw new Error('Portfolio inventory changed. Retry loading assignments.');
    rows.push(...result.items); total = result.total; page += 1;
  } while (rows.length < total);
  return rows;
}
