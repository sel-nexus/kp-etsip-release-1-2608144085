"""Inject pooled persistence and enforce live identity before domain actions."""
from typing import Annotated
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pymongo.asynchronous.database import AsyncDatabase
from api.core.audit import AuditService
from api.core.errors import Unauthenticated
from api.core.policy import Principal, password_gate, require_permission
from api.core.schemas import Permission
from api.domains.auth.repository import AuthRepository
from api.domains.auth.service import AuthService

bearer = HTTPBearer(auto_error=False)
def get_database(request: Request) -> AsyncDatabase:
    """Return the lifespan-owned database; never open a request client."""
    return request.app.state.database
def get_auth_service(request: Request, database: Annotated[AsyncDatabase, Depends(get_database)]) -> AuthService:
    """Compose request services around the same pooled database."""
    return AuthService(AuthRepository(database), AuditService(database), request.app.state.settings)
async def get_principal(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], service: Annotated[AuthService, Depends(get_auth_service)]) -> Principal:
    """Authenticate and apply the password gate before protected route logic."""
    if credentials is None or credentials.scheme.lower() != 'bearer':
        raise Unauthenticated()
    principal = await service.resolve(credentials.credentials)
    password_gate(principal, request.url.path, request.method)
    return principal

def permission_dependency(action: Permission, resource: str):
    """Build a thin route-level policy dependency for subsequent slices."""
    async def authorized(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        """Authorize current permissions before any resource lookup."""
        require_permission(principal, action, resource)
        return principal
    return authorized
