/** Read executive measures through the sole bearer-aware client. */
import { apiRequest } from '../../lib/api';
import type { Dashboard } from '../../types';
export const dashboardApi = {
  /** Preserve URL filters, including invalid values for server validation. */
  executive: (query: URLSearchParams) => apiRequest<Dashboard>(`/dashboard/executive?${query}`),
};
