"""Expose portfolio contracts through thin authorized FastAPI handlers."""
from datetime import datetime
from typing import Annotated
from bson import ObjectId
from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError, TypeAdapter, AwareDatetime
from pymongo.asynchronous.database import AsyncDatabase
from api.core.audit import AuditService
from api.core.dependencies import get_database, permission_dependency
from api.core.errors import DomainError
from api.core.policy import Principal
from api.domains.portfolios.repository import PortfolioRepository
from api.domains.portfolios.service import PortfolioService
from api.domains.portfolios.schemas import Portfolio, PortfolioPage, PortfolioDetail, PortfolioCreate, PortfolioUpdate, PortfolioFilters, ApplicationPage, DeletedPortfolio

router = APIRouter(prefix='/api/portfolios', tags=['Portfolios'])

def get_service(database: Annotated[AsyncDatabase, Depends(get_database)]) -> PortfolioService:
    """Reuse the injected database for both inventory and audit writes."""
    return PortfolioService(PortfolioRepository(database), AuditService(database))

def identifier(id: str) -> ObjectId:
    """Reject malformed direct IDs without querying Mongo."""
    if not ObjectId.is_valid(id):
        raise DomainError('NOT_FOUND', 'Portfolio not found', 404)
    return ObjectId(id)

def filters(request: Request) -> PortfolioFilters:
    """Reject unsupported, repeated, malformed or unbounded query parameters."""
    values = dict(request.query_params)
    if any(len(request.query_params.getlist(key)) != 1 for key in values):
        raise DomainError('INVALID_FILTER', 'Invalid portfolio filters', 400)
    try:
        return PortfolioFilters.model_validate(values)
    except ValidationError as exc:
        raise DomainError('INVALID_FILTER', 'Invalid portfolio filters', 400) from exc

def paging(request: Request) -> PortfolioFilters:
    """Allow only page and pageSize for related-application queries."""
    if set(request.query_params) - {'page', 'pageSize'}:
        raise DomainError('INVALID_FILTER', 'Invalid paging filters', 400)
    return filters(request)

def delete_expected(request: Request) -> datetime | None:
    """Validate the optional stale-delete token and reject unknown query names."""
    if set(request.query_params) - {'expectedUpdatedAt'} or len(request.query_params.getlist('expectedUpdatedAt')) > 1:
        raise DomainError('INVALID_FILTER', 'Invalid delete filters', 400)
    value = request.query_params.get('expectedUpdatedAt')
    if value is not None and ('T' not in value or len(value) > 64):
        raise DomainError('INVALID_FILTER', 'Invalid edit timestamp', 400)
    try:
        return TypeAdapter(AwareDatetime).validate_python(value) if value is not None else None
    except ValidationError as exc:
        raise DomainError('INVALID_FILTER', 'Invalid edit timestamp', 400) from exc

Service = Annotated[PortfolioService, Depends(get_service)]
View = Annotated[Principal, Depends(permission_dependency('view', 'portfolio'))]
Create = Annotated[Principal, Depends(permission_dependency('create', 'portfolio'))]
Edit = Annotated[Principal, Depends(permission_dependency('edit', 'portfolio'))]
Delete = Annotated[Principal, Depends(permission_dependency('delete', 'portfolio'))]

@router.get('', response_model=PortfolioPage, summary='Find visible portfolios')
async def list_portfolios(principal: View, service: Service, query: Annotated[PortfolioFilters, Depends(filters)]) -> PortfolioPage:
    """Return AND-filtered visible inventory with derived measures."""
    return await service.list(principal, query)

@router.post('', response_model=Portfolio, status_code=201, summary='Create portfolio')
async def create_portfolio(body: PortfolioCreate, principal: Create, service: Service) -> Portfolio:
    """Create and require audit persistence before success."""
    return await service.create(principal, body)

@router.get('/{id}/applications', response_model=ApplicationPage, summary='List related applications')
async def related_applications(id: str, principal: View, service: Service, query: Annotated[PortfolioFilters, Depends(paging)]) -> ApplicationPage:
    """Return a scoped related page only after checking parent visibility."""
    return await service.related(principal, identifier(id), query)

@router.get('/{id}', response_model=PortfolioDetail, summary='Review portfolio')
async def get_portfolio(id: str, principal: View, service: Service) -> PortfolioDetail:
    """Return the portfolio and initial related application summaries."""
    return await service.detail(principal, identifier(id))

@router.put('/{id}', response_model=Portfolio, summary='Update portfolio')
async def update_portfolio(id: str, body: PortfolioUpdate, principal: Edit, service: Service) -> Portfolio:
    """Apply only supplied fields with optimistic concurrency."""
    return await service.update(principal, identifier(id), body)

@router.delete('/{id}', response_model=DeletedPortfolio, summary='Delete unreferenced portfolio')
async def delete_portfolio(id: str, principal: Delete, service: Service, expected: Annotated[datetime | None, Depends(delete_expected)]) -> DeletedPortfolio:
    """Delete without cascade and require durable audit."""
    return await service.delete(principal, identifier(id), expected)
