/** Configure only the six supported roles through the shared bearer client. */
import { apiRequest } from '../../lib/api';
import type { Permission, RoleDefinition, RoleName } from '../../types';
export const roleMaximum: Record<RoleName, readonly Permission[]> = {
  Administrator: ['view', 'create', 'edit', 'delete', 'export', 'administer'],
  Executive: ['view', 'export'],
  'Portfolio Leader': ['view', 'create', 'edit', 'export'],
  Engineer: ['view', 'create', 'edit', 'export'],
  Auditor: ['view', 'export'],
  'Read Only': ['view'],
};
export const roleApi = {
  /** Fetch current persisted definitions without inventing custom role filters. */
  list: () => apiRequest<{ items: RoleDefinition[] }>('/roles'),
  /** Restore a missing baseline without resetting an existing edited role. */
  ensure: (name: RoleName) => apiRequest<RoleDefinition>('/roles', { method: 'POST', body: JSON.stringify({ name }) }),
  /** Supply the displayed version so concurrent changes cannot silently overwrite. */
  update: (role: RoleDefinition, permissions: Permission[]) => apiRequest<RoleDefinition>(`/roles/${role.id}`, {
    method: 'PUT', body: JSON.stringify({ permissions, expectedUpdatedAt: role.updatedAt }),
  }),
};
