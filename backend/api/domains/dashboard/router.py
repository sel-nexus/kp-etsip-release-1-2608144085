"""Expose executive measures through the live view permission dependency."""
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from pymongo.asynchronous.database import AsyncDatabase
from api.core.dependencies import get_database, permission_dependency
from api.core.errors import DomainError
from api.core.policy import Principal
from api.domains.applications.repository import ApplicationRepository
from api.domains.portfolios.repository import PortfolioRepository
from api.domains.dashboard.schemas import Dashboard, DashboardFilters
from api.domains.dashboard.service import DashboardService

router = APIRouter(prefix='/api/dashboard', tags=['Dashboard'])

def get_service(database: Annotated[AsyncDatabase, Depends(get_database)]) -> DashboardService:
    """Compose both repositories around the same lifespan-owned client."""
    return DashboardService(ApplicationRepository(database), PortfolioRepository(database))

def filters(request: Request) -> DashboardFilters:
    """Reject malformed, unknown and repeated filter values with the safe envelope."""
    if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise DomainError('INVALID_FILTER', 'Invalid dashboard filters', 400)
    try:
        return DashboardFilters.model_validate(dict(request.query_params))
    except ValidationError as exc:
        raise DomainError('INVALID_FILTER', 'Invalid dashboard filters', 400) from exc

@router.get('/executive', response_model=Dashboard, summary='Review visible executive measures')
async def executive(
    principal: Annotated[Principal, Depends(permission_dependency('view', 'dashboard'))],
    service: Annotated[DashboardService, Depends(get_service)],
    query: Annotated[DashboardFilters, Depends(filters)],
) -> Dashboard:
    """Return only deterministic inventory measures within current authorization."""
    return await service.executive(principal, query)
