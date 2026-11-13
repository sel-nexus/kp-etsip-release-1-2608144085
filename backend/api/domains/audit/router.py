"""Expose strictly filtered review and independently authorized CSV."""
from collections.abc import AsyncIterator
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from pymongo.asynchronous.database import AsyncDatabase
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from api.core.audit import AuditService
from api.core.dependencies import get_database, get_principal
from api.core.errors import DomainError
from api.core.policy import Principal, require_permission
from api.domains.audit.repository import AuditRepository
from api.domains.audit.schemas import AuditFilters, AuditPage
from api.domains.audit.service import AuditHistoryService

router = APIRouter(prefix='/api/audit-logs', tags=['Audit'])

def get_service(database: Annotated[AsyncDatabase, Depends(get_database)]) -> AuditHistoryService:
    """Inject the existing pool into query and evidence repositories."""
    return AuditHistoryService(AuditRepository(database), AuditService(database))

def parse_filters(request: Request) -> AuditFilters:
    """Reject unknown and repeated HTTP keys before model validation."""
    allowed = {'userId', 'action', 'from', 'to', 'page', 'pageSize', 'format'}
    pairs = list(request.query_params.multi_items())
    if any(key not in allowed for key, _ in pairs) or len({key for key, _ in pairs}) != len(pairs):
        raise DomainError('INVALID_FILTER', 'Invalid audit filters', 400)
    try:
        return AuditFilters.model_validate(dict(pairs))
    except ValidationError as exc:
        raise DomainError('INVALID_FILTER', 'Invalid audit filters', 400) from exc

@router.get('', response_model=AuditPage, summary='Review or export audit history', responses={200: {'content': {'text/csv': {}}}})
async def history(request: Request, principal: Annotated[Principal, Depends(get_principal)], service: Annotated[AuditHistoryService, Depends(get_service)]) -> AuditPage | StreamingResponse:
    """Authorize before parsing and release only completed, audited exports."""
    require_permission(principal, 'export' if request.query_params.get('format') == 'csv' else 'view', 'audit')
    filters = parse_filters(request)
    if filters.format == 'csv':
        spool = await service.export(principal, filters)
        async def chunks() -> AsyncIterator[bytes]:
            """Read bounded chunks and release the spool on disconnect."""
            try:
                while chunk := await run_in_threadpool(spool.read, 64 * 1024):
                    yield chunk
            finally:
                await run_in_threadpool(spool.close)
        return StreamingResponse(chunks(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="audit-history.csv"'}, background=BackgroundTask(spool.close))
    return await service.search(principal, filters)
