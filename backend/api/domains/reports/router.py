"""Expose fixed reports and completed CSV with current identity policy."""
from typing import Annotated, BinaryIO, TypeVar
from collections.abc import AsyncIterator
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from pymongo.asynchronous.database import AsyncDatabase
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from api.core.audit import AuditService
from api.core.dependencies import get_database, get_principal
from api.core.errors import DomainError
from api.core.policy import Principal, require_permission
from api.domains.applications.repository import ApplicationRepository
from api.domains.portfolios.repository import PortfolioRepository
from api.domains.reports.schemas import ApplicationReportFilters, PortfolioReportFilters, ApplicationReportPage, PortfolioReportPage
from api.domains.reports.service import ReportService

router = APIRouter(prefix='/api/reports', tags=['Reports'])

def get_service(database: Annotated[AsyncDatabase, Depends(get_database)]) -> ReportService:
    """Compose inventory and evidence collaborators over one pooled database."""
    return ReportService(ApplicationRepository(database), PortfolioRepository(database), AuditService(database))

FilterModel = TypeVar('FilterModel', bound=BaseModel)

def parse_filters(request: Request, model: type[FilterModel]) -> FilterModel:
    """Reject unknown, repeated and malformed query inputs before reads."""
    pairs = list(request.query_params.multi_items())
    if len({key for key, _ in pairs}) != len(pairs):
        raise DomainError('INVALID_FILTER', 'Invalid report filters', 400)
    try:
        return model.model_validate(dict(pairs))
    except ValidationError as exc:
        raise DomainError('INVALID_FILTER', 'Invalid report filters', 400) from exc

def csv_response(spool: BinaryIO, resource: str) -> StreamingResponse:
    """Release bounded chunks and close transient storage even on disconnect."""
    if resource not in ('application', 'portfolio'):
        spool.close()
        raise ValueError('Unsupported report')
    async def chunks() -> AsyncIterator[bytes]:
        """Read from an already completed and audited spool."""
        try:
            while chunk := await run_in_threadpool(spool.read, 64 * 1024):
                yield chunk
        finally:
            await run_in_threadpool(spool.close)
    return StreamingResponse(chunks(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="{resource}-report.csv"'}, background=BackgroundTask(spool.close))

Identity = Annotated[Principal, Depends(get_principal)]
Service = Annotated[ReportService, Depends(get_service)]

@router.get('/applications', response_model=ApplicationReportPage, responses={200: {'content': {'text/csv': {}}}}, summary='Review or export applications')
async def applications(request: Request, principal: Identity, service: Service) -> ApplicationReportPage | StreamingResponse:
    """Keep report and application-list exports on the same service path."""
    require_permission(principal, 'view', 'application')
    query = parse_filters(request, ApplicationReportFilters)
    if query.format == 'csv':
        return csv_response(await service.export(principal, query, 'application'), 'application')
    return await service.applications_page(principal, query)

@router.get('/portfolios', response_model=PortfolioReportPage, responses={200: {'content': {'text/csv': {}}}}, summary='Review or export portfolios')
async def portfolios(request: Request, principal: Identity, service: Service) -> PortfolioReportPage | StreamingResponse:
    """Derive measures from authorized related facts, never stored summaries."""
    require_permission(principal, 'view', 'portfolio')
    query = parse_filters(request, PortfolioReportFilters)
    if query.format == 'csv':
        return csv_response(await service.export(principal, query, 'portfolio'), 'portfolio')
    return await service.portfolios_page(principal, query)
