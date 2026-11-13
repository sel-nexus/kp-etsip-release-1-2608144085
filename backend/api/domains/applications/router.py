"""Expose application inventory through authorized, typed FastAPI handlers."""
from datetime import datetime
from typing import Annotated
from bson import ObjectId
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from api.domains.reports.router import get_service as get_report_service, parse_filters, csv_response
from api.domains.reports.schemas import ApplicationReportFilters
from api.domains.reports.service import ReportService
from pydantic import ValidationError
from pymongo.asynchronous.database import AsyncDatabase
from api.core.audit import AuditService
from api.core.dependencies import get_database, permission_dependency
from api.core.errors import DomainError
from api.core.policy import Principal
from api.domains.applications.repository import ApplicationRepository
from api.domains.applications.service import ApplicationService
from api.domains.applications.schemas import Application, ApplicationPage, ApplicationDetail, ApplicationCreate, ApplicationUpdate, ApplicationFilters, DeletedApplication
from api.domains.portfolios.router import delete_expected

router = APIRouter(prefix='/api/applications', tags=['Applications'])

def get_service(database: Annotated[AsyncDatabase, Depends(get_database)]) -> ApplicationService:
    """Reuse the pooled database for application and audit persistence."""
    return ApplicationService(ApplicationRepository(database), AuditService(database))

def identifier(id: str) -> ObjectId:
    """Treat malformed direct identifiers as undisclosed missing resources."""
    if not ObjectId.is_valid(id):
        raise DomainError('NOT_FOUND', 'Application not found', 404)
    return ObjectId(id)

def filters(request: Request) -> ApplicationFilters:
    """Reject unsupported, repeated and malformed queries before data access."""
    if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise DomainError('INVALID_FILTER', 'Invalid application filters', 400)
    try:
        return ApplicationFilters.model_validate(dict(request.query_params))
    except ValidationError as exc:
        raise DomainError('INVALID_FILTER', 'Invalid application filters', 400) from exc

Service = Annotated[ApplicationService, Depends(get_service)]
View = Annotated[Principal, Depends(permission_dependency('view', 'application'))]
Create = Annotated[Principal, Depends(permission_dependency('create', 'application'))]
Edit = Annotated[Principal, Depends(permission_dependency('edit', 'application'))]
Delete = Annotated[Principal, Depends(permission_dependency('delete', 'application'))]

@router.get('', response_model=ApplicationPage, responses={200: {'content': {'text/csv': {}}}}, summary='Find or export visible applications')
async def list_applications(request: Request, principal: View, service: Service, reports: Annotated[ReportService, Depends(get_report_service)]) -> ApplicationPage | StreamingResponse:
    """Reuse report export and inventory predicates without duplicate CSV logic."""
    query = parse_filters(request, ApplicationReportFilters)
    if query.format == 'csv':
        return csv_response(await reports.export(principal, query, 'application'), 'application')
    return await service.list(principal, query)

@router.post('', response_model=Application, status_code=201, summary='Create application')
async def create_application(body: ApplicationCreate, principal: Create, service: Service) -> Application:
    """Persist validated facts and mandatory audit before success."""
    return await service.create(principal, body)

@router.get('/{id}', response_model=ApplicationDetail, summary='Review application')
async def get_application(id: str, principal: View, service: Service) -> ApplicationDetail:
    """Expose the full safe application and visible portfolio summary."""
    return await service.detail(principal, identifier(id))

@router.put('/{id}', response_model=Application, summary='Update application')
async def update_application(id: str, body: ApplicationUpdate, principal: Edit, service: Service) -> Application:
    """Apply supplied fields using optimistic concurrency and reference coordination."""
    return await service.update(principal, identifier(id), body)

@router.delete('/{id}', response_model=DeletedApplication, summary='Delete application')
async def delete_application(id: str, principal: Delete, service: Service, expected: Annotated[datetime | None, Depends(delete_expected)]) -> DeletedApplication:
    """Delete an authorized observed version and require audit persistence."""
    return await service.delete(principal, identifier(id), expected)
