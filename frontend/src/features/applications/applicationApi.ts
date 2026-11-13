/** Execute application contracts through the shared bearer client. */
import { apiRequest } from '../../lib/api';
import type { Application, ApplicationDetail, ApplicationWrite, Page } from '../../types';
export const applicationApi = {
  /** Preserve validated URL filters without replacing server authorization. */
  list: (query = new URLSearchParams()) => apiRequest<Page<Application>>(`/applications?${query}`),
  /** Load complete safe application and parent context. */
  detail: (id: string) => apiRequest<ApplicationDetail>(`/applications/${id}`),
  /** Create every required business field. */
  create: (body: ApplicationWrite) => apiRequest<Application>('/applications', { method: 'POST', body: JSON.stringify(body) }),
  /** Compare the loaded edit token before replacing supplied fields. */
  update: (id: string, body: Partial<ApplicationWrite>, expectedUpdatedAt: string) => apiRequest<Application>(`/applications/${id}`, {
    method: 'PUT', body: JSON.stringify({ ...body, expectedUpdatedAt }),
  }),
  /** Require explicit admin confirmation with the observed version. */
  delete: (id: string, expectedUpdatedAt: string) => apiRequest<{ deleted: true; id: string }>(
    `/applications/${id}?${new URLSearchParams({ expectedUpdatedAt })}`, { method: 'DELETE' },
  ),
};
export const applicationGroups = [
  { title: 'Identity and ownership', keys: ['name', 'description', 'portfolioId', 'productArea', 'businessOwner', 'technologyOwner', 'etsOwner'] },
  { title: 'Classification and technology', keys: ['criticality', 'tier', 'lifecycleStatus', 'riskLevel', 'technologyStack', 'repositoryUrl', 'pipelineUrl'] },
  { title: 'Quality and health', keys: ['applicationHealthScore', 'qualityScore', 'automationCoverage', 'unitTestCoverage', 'openDefects', 'openCriticalDefects'] },
] as const;
export const applicationLabels: Record<keyof ApplicationWrite, string> = {
  name: 'Name', description: 'Description', portfolioId: 'Portfolio', productArea: 'Product area', businessOwner: 'Business owner',
  technologyOwner: 'Technology owner', etsOwner: 'ETS owner', criticality: 'Criticality', tier: 'Tier', lifecycleStatus: 'Lifecycle status',
  technologyStack: 'Technology stack', repositoryUrl: 'Repository URL', pipelineUrl: 'Pipeline URL', applicationHealthScore: 'Application health score',
  qualityScore: 'Quality score', automationCoverage: 'Automation coverage', unitTestCoverage: 'Unit test coverage', openDefects: 'Open defects',
  openCriticalDefects: 'Open critical defects', riskLevel: 'Risk level',
};
