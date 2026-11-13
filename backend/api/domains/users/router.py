"""Expose administer-only account endpoints through thin typed handlers."""
from datetime import datetime
from typing import Annotated
from bson import ObjectId
from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from pymongo.asynchronous.database import AsyncDatabase
from api.core.audit import AuditService
from api.core.dependencies import get_database, permission_dependency
from api.core.errors import DomainError
from api.core.policy import Principal
from api.domains.users.repository import UserRepository
from api.domains.users.service import UserService
from api.domains.users.schemas import User, UserPage, UserCreate, UserUpdate, UserFilters, DeactivatedUser
from api.domains.portfolios.router import delete_expected

router = APIRouter(prefix='/api/users', tags=['Users'])

def get_service(database: Annotated[AsyncDatabase, Depends(get_database)]) -> UserService:
    """Compose account and audit persistence from the pooled database."""
    return UserService(UserRepository(database), AuditService(database))

def identifier(id: str) -> ObjectId:
    """Treat malformed direct IDs as undisclosed missing accounts."""
    if not ObjectId.is_valid(id):
        raise DomainError('NOT_FOUND', 'User not found', 404)
    return ObjectId(id)

def filters(request: Request) -> UserFilters:
    """Reject unknown and repeated queries before any account data access."""
    if any(key not in {'page', 'pageSize', 'search', 'role', 'status'} or len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise DomainError('INVALID_FILTER', 'Invalid user filters', 400)
    try:
        return UserFilters.model_validate(dict(request.query_params))
    except ValidationError as exc:
        raise DomainError('INVALID_FILTER', 'Invalid user filters', 400) from exc

def no_query(request: Request) -> None:
    """Reject unsupported query fields on account detail and body-only mutations."""
    if request.query_params:
        raise DomainError('INVALID_FILTER', 'Invalid user filters', 400)

Service = Annotated[UserService, Depends(get_service)]
Admin = Annotated[Principal, Depends(permission_dependency('administer', 'user'))]

@router.get('', response_model=UserPage, summary='Find accounts')
async def list_users(principal: Admin, service: Service, query: Annotated[UserFilters, Depends(filters)]) -> UserPage:
    """Return a bounded complete safe account page."""
    return await service.list(principal, query)

@router.post('', response_model=User, status_code=201, summary='Create local account')
async def create_user(body: UserCreate, principal: Admin, service: Service, request: Request) -> User:
    """Persist account and audit without returning the submitted credential."""
    no_query(request)
    return await service.create(principal, body)

@router.get('/{id}', response_model=User, summary='Review account')
async def get_user(id: str, principal: Admin, service: Service, request: Request) -> User:
    """Expose only allowlisted account metadata."""
    no_query(request)
    return await service.detail(principal, identifier(id))

@router.put('/{id}', response_model=User, summary='Update account')
async def update_user(id: str, body: UserUpdate, principal: Admin, service: Service, request: Request) -> User:
    """Apply role and access changes with durable reference safety."""
    no_query(request)
    return await service.update(principal, identifier(id), body)

@router.delete('/{id}', response_model=DeactivatedUser, summary='Deactivate account')
async def deactivate_user(id: str, principal: Admin, service: Service, expected: Annotated[datetime | None, Depends(delete_expected)]) -> DeactivatedUser:
    """Never hard delete an account or its audit history."""
    return await service.delete(principal, identifier(id), expected)
