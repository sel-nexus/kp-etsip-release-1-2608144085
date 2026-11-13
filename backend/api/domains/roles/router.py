"""Expose only administer-protected list, ensure and permission updates."""
from typing import Annotated
from bson import ObjectId
from fastapi import APIRouter, Depends, Request
from pymongo.asynchronous.database import AsyncDatabase
from api.core.audit import AuditService
from api.core.dependencies import get_database, permission_dependency
from api.core.errors import DomainError
from api.core.policy import Principal
from api.domains.roles.repository import RoleRepository
from api.domains.roles.service import RoleService
from api.domains.roles.schemas import Role, RoleList, RoleEnsure, RoleUpdate

router = APIRouter(prefix='/api/roles', tags=['Roles'])

def get_service(database: Annotated[AsyncDatabase, Depends(get_database)]) -> RoleService:
    """Compose both repositories from the same request-injected pool."""
    return RoleService(RoleRepository(database), AuditService(database))

def no_query(request: Request) -> None:
    """Reject unsupported filters rather than silently ignoring them."""
    if request.query_params:
        raise DomainError('INVALID_FILTER', 'Invalid role filters', 400)

Admin = Annotated[Principal, Depends(permission_dependency('administer', 'role'))]
Service = Annotated[RoleService, Depends(get_service)]

@router.get('', response_model=RoleList, summary='List supported roles')
async def list_roles(principal: Admin, service: Service, request: Request) -> RoleList:
    """Return persisted supported roles only."""
    no_query(request)
    return await service.list(principal)

@router.post('', response_model=Role, summary='Ensure supported baseline role')
async def ensure_role(body: RoleEnsure, principal: Admin, service: Service, request: Request) -> Role:
    """Return the existing or newly inserted supported baseline with status 200."""
    no_query(request)
    return await service.ensure(principal, body)

@router.put('/{id}', response_model=Role, summary='Update bounded role permissions')
async def update_role(id: str, body: RoleUpdate, principal: Admin, service: Service, request: Request) -> Role:
    """Never rename, delete or expand the role boundary."""
    no_query(request)
    if not ObjectId.is_valid(id):
        raise DomainError('NOT_FOUND', 'Role not found', 404)
    return await service.update(principal, ObjectId(id), body)
