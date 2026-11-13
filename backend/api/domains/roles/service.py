"""Enforce role ceilings, concurrency and required durable audit evidence."""
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from api.core.audit import AuditService
from api.core.errors import DomainError
from api.core.policy import Principal, ROLE_MAXIMUM, require_permission, validate_permissions
from api.domains.roles.repository import RoleRepository
from api.domains.roles.schemas import Role, RoleList, RoleEnsure, RoleUpdate

DESCRIPTIONS = {
    'Administrator': 'Platform administration',
    'Executive': 'Enterprise read and export',
    'Portfolio Leader': 'Assigned portfolio leadership',
    'Engineer': 'Application engineering',
    'Auditor': 'Read and audit',
    'Read Only': 'Assigned inventory read',
}

class RoleService:
    """Allow reductions and restoration up to immutable role-specific maxima."""
    def __init__(self, repository: RoleRepository, audit: AuditService) -> None:
        """Inject pooled persistence and mandatory audit collaborators."""
        self.repository, self.audit = repository, audit

    async def list(self, principal: Principal) -> RoleList:
        """Require administration before querying supported definitions."""
        require_permission(principal, 'administer', 'role')
        return RoleList(items=[Role.model_validate(row) for row in await self.repository.list()])

    async def ensure(self, principal: Principal, request: RoleEnsure) -> Role:
        """Insert a missing baseline only; audit exclusively the winning insertion."""
        require_permission(principal, 'administer', 'role')
        now = datetime.now(timezone.utc)
        row, inserted = await self.repository.ensure({
            'name': request.name, 'description': DESCRIPTIONS[request.name],
            'permissions': sorted(ROLE_MAXIMUM[request.name]), 'createdAt': now, 'updatedAt': now})
        if inserted:
            await self.audit.record(principal.user_id, principal.user_name, 'create', 'role', row['_id'], 'Ensured supported role')
        return Role.model_validate(row)

    async def update(self, principal: Principal, identifier: ObjectId, request: RoleUpdate) -> Role:
        """Compare versions and bound permissions before any persistence or audit."""
        require_permission(principal, 'administer', 'role')
        snapshot = await self.repository.get(identifier)
        if snapshot is None:
            raise DomainError('NOT_FOUND', 'Role not found', 404)
        validate_permissions(snapshot['name'], request.permissions)
        if request.expectedUpdatedAt is not None and request.expectedUpdatedAt != snapshot['updatedAt']:
            raise DomainError('CONFLICT', 'Role changed. Reload and try again.', 409)
        updated = await self.repository.update(snapshot, {
            'permissions': request.permissions,
            'updatedAt': max(datetime.now(timezone.utc), snapshot['updatedAt'] + timedelta(milliseconds=1))})
        if updated is None:
            if await self.repository.get(identifier) is None:
                raise DomainError('NOT_FOUND', 'Role not found', 404)
            raise DomainError('CONFLICT', 'Role changed. Reload and try again.', 409)
        await self.audit.record(principal.user_id, principal.user_name, 'permissionChange', 'role', identifier, 'Updated role permissions')
        return Role.model_validate(updated)
