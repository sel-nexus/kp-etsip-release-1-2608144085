/** Call portfolio contracts through the sole bearer-aware HTTP client. */
import { apiRequest } from '../../lib/api';
import type { Page, Portfolio, PortfolioDetail, PortfolioWrite, RelatedApplication } from '../../types';
export const portfolioApi = {
  /** Fetch a URL-backed filtered inventory page. */
  list: (query: URLSearchParams) => apiRequest<Page<Portfolio>>(`/portfolios?${query}`),
  /** Return the specified portfolio/detail wrapper. */
  detail: (id: string) => apiRequest<PortfolioDetail>(`/portfolios/${id}`),
  /** Fetch independently paged related summaries. */
  related: (id: string, page: number, pageSize = 25) =>
    apiRequest<Page<RelatedApplication>>(`/portfolios/${id}/applications?page=${page}&pageSize=${pageSize}`),
  /** Create a complete portfolio without derived fields. */
  create: (body: PortfolioWrite) => apiRequest<Portfolio>('/portfolios', { method: 'POST', body: JSON.stringify(body) }),
  /** Compare the visible timestamp before replacing supplied fields. */
  update: (id: string, body: PortfolioWrite, expectedUpdatedAt: string) =>
    apiRequest<Portfolio>(`/portfolios/${id}`, { method: 'PUT', body: JSON.stringify({ ...body, expectedUpdatedAt }) }),
  /** Reject stale deletion and any linked records on the server. */
  delete: (id: string, expectedUpdatedAt: string) => apiRequest<{ deleted: true; id: string }>(
    `/portfolios/${id}?${new URLSearchParams({ expectedUpdatedAt })}`, { method: 'DELETE' },
  ),
};
