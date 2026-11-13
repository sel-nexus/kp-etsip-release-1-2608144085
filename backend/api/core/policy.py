"""Enforce six-role ceilings, resource boundaries, and Mongo portfolio scope."""
from dataclasses import dataclass
from bson import ObjectId
from api.core.schemas import RoleName, Permission
from api.core.errors import Forbidden, DomainError

ROLE_MAXIMUM: dict[str, frozenset[str]] = {
    'Administrator': frozenset(('view', 'create', 'edit', 'delete', 'export', 'administer')),
    'Executive': frozenset(('view', 'export')),
    'Portfolio Leader': frozenset(('view', 'create', 'edit', 'export')),
    'Engineer': frozenset(('view', 'create', 'edit', 'export')),
    'Auditor': frozenset(('view', 'export')),
    'Read Only': frozenset(('view',)),
}
@dataclass(frozen=True)
class Principal:
    """Hold current database-derived authorization, never stale token roles."""
    user_id: ObjectId
    role: RoleName
    permissions: frozenset[str]
    portfolio_access: tuple[ObjectId, ...]
    must_change_password: bool
    user_name: str

@dataclass(frozen=True)
class Scope:
    """Represent unrestricted access distinctly from an empty assignment."""
    portfolio_ids: tuple[ObjectId, ...] | None
    def predicate(self, field: str = 'portfolioId') -> dict[str, object]:
        """Produce a server-owned predicate for the same database query."""
        if field not in ('portfolioId', '_id'):
            raise ValueError('Unsupported scope field')
        return {} if self.portfolio_ids is None else {field: {'$in': list(self.portfolio_ids)}}
    def includes(self, portfolio_id: ObjectId) -> bool:
        """Check a create/edit destination before persistence."""
        return self.portfolio_ids is None or portfolio_id in self.portfolio_ids

def validate_permissions(role: str, permissions: list[str]) -> frozenset[str]:
    """Reject unknown roles, unknown actions, and any ceiling expansion."""
    result = frozenset(permissions)
    if role not in ROLE_MAXIMUM or not result <= ROLE_MAXIMUM[role]:
        raise DomainError('VALIDATION_ERROR', 'Unsupported role permissions', 422)
    return result

def password_gate(principal: Principal, path: str, method: str) -> None:
    """Allow only me, logout, and password replacement through the gate."""
    allowed = {('GET', '/api/auth/me'), ('POST', '/api/auth/logout'), ('POST', '/api/auth/change-password')}
    if principal.must_change_password and (method, path) not in allowed:
        raise DomainError('PASSWORD_CHANGE_REQUIRED', 'Password change required', 403)

def require_permission(principal: Principal, action: Permission, resource: str) -> None:
    """Combine stored permissions with immutable role/resource ceilings."""
    if principal.must_change_password:
        raise DomainError('PASSWORD_CHANGE_REQUIRED', 'Password change required', 403)
    if action not in principal.permissions or action not in ROLE_MAXIMUM.get(principal.role, ()):
        raise Forbidden()
    if resource in ('user', 'role') and principal.role != 'Administrator':
        raise Forbidden()
    if resource == 'audit' and principal.role not in ('Administrator', 'Auditor'):
        raise Forbidden()
    if action in ('create', 'edit', 'delete', 'administer') and resource != 'application' and principal.role != 'Administrator':
        raise Forbidden()

def portfolio_scope(principal: Principal) -> Scope:
    """Keep empty assignments restricted for assignment-bound roles."""
    if not principal.portfolio_access and principal.role in ('Administrator', 'Executive', 'Auditor'):
        return Scope(None)
    return Scope(principal.portfolio_access)
