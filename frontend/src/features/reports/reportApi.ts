/** Share report queries and explicit blob downloads with application inventory. */
import { apiRequest, ApiError, TOKEN_KEY, SESSION_EXPIRED } from '../../lib/api';
import type { ApplicationReportRow, PortfolioReportRow, Page, ErrorEnvelope } from '../../types';
export const applicationColumns = ['id','name','portfolioId','criticality','tier','lifecycleStatus','applicationHealthScore','qualityScore','automationCoverage','unitTestCoverage','openDefects','openCriticalDefects','riskLevel'] as const;
export const portfolioColumns = ['id','name','ownerName','productArea','status','applicationCount','qualityScore'] as const;
/** Request CSV only after a user action; retain filters and independent paging. */
async function download(resource: 'applications' | 'portfolios' | 'application-list', query: URLSearchParams): Promise<void> {
  const filters = new URLSearchParams(query);
  filters.set('format', 'csv');
  const headers = new Headers({ Accept: 'text/csv' });
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  let response: Response;
  try {
    response = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? '/api'}${resource === 'application-list' ? '/applications' : `/reports/${resource}`}?${filters}`, { headers, cache: 'no-store' });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Unable to reach the service. Try again.');
  }
  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      window.dispatchEvent(new Event(SESSION_EXPIRED));
    }
    let body: ErrorEnvelope | null = null;
    try { body = await response.json() as ErrorEnvelope; } catch { body = null; }
    throw new ApiError(response.status, body?.error?.code ?? 'REQUEST_FAILED', body?.error?.message ?? 'Export failed. Try again.');
  }
  if (!response.headers.get('Content-Type')?.startsWith('text/csv')) {
    throw new ApiError(0, 'INVALID_RESPONSE', 'The service did not return CSV. Try again.');
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  try {
    anchor.href = url;
    anchor.download = resource === 'portfolios' ? 'portfolio-report.csv' : 'application-report.csv';
    document.body.append(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    // Allow the browser to start the real download before releasing its URL.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

export const reportApi = {
  applications: (query: URLSearchParams) => apiRequest<Page<ApplicationReportRow>>(`/reports/applications?${query}`),
  portfolios: (query: URLSearchParams) => apiRequest<Page<PortfolioReportRow>>(`/reports/portfolios?${query}`),
  download,
};
