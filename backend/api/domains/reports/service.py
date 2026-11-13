"""Reuse scoped inventory repositories for report pages and audited CSV."""
from math import floor
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from starlette.concurrency import run_in_threadpool
from api.core.audit import AuditService
from api.core.csv import csv_line
from api.core.errors import DomainError
from api.core.policy import Principal, Scope, portfolio_scope, require_permission
from api.domains.applications.repository import ApplicationRepository
from api.domains.portfolios.repository import PortfolioRepository
from api.domains.reports.schemas import ApplicationReportFilters, PortfolioReportFilters, ApplicationReportRow, PortfolioReportRow, ApplicationReportPage, PortfolioReportPage, APPLICATION_COLUMNS, PORTFOLIO_COLUMNS

class ReportService:
    """Keep reads and exports read-only and independently authorized."""
    def __init__(self, applications: ApplicationRepository, portfolios: PortfolioRepository, audit: AuditService) -> None:
        """Bind real repositories to the existing request database pool."""
        self.applications, self.portfolios, self.audit = applications, portfolios, audit

    async def portfolio_row(self, document: dict, scope: Scope) -> PortfolioReportRow:
        """Calculate authorized counts and half-up means without persisting them."""
        measures = await self.portfolios.measures(scope, document['_id'])
        return PortfolioReportRow.model_validate({**document, 'applicationCount': measures['count'], 'qualityScore': None if measures['quality'] is None else floor(measures['quality'] + 0.5)})

    async def applications_page(self, principal: Principal, filters: ApplicationReportFilters) -> ApplicationReportPage:
        """Authorize before using exactly the application inventory predicate."""
        require_permission(principal, 'view', 'application')
        rows, total = await self.applications.list_page(portfolio_scope(principal), filters)
        return ApplicationReportPage(items=[ApplicationReportRow.model_validate(row) for row in rows], page=filters.page, pageSize=filters.pageSize, total=total)

    async def portfolios_page(self, principal: Principal, filters: PortfolioReportFilters) -> PortfolioReportPage:
        """Authorize before portfolio listing and associated scoped measures."""
        require_permission(principal, 'view', 'portfolio')
        scope = portfolio_scope(principal)
        rows, total = await self.portfolios.list_page(scope, filters)
        return PortfolioReportPage(items=[await self.portfolio_row(row, scope) for row in rows], page=filters.page, pageSize=filters.pageSize, total=total)

    async def export(self, principal: Principal, filters: ApplicationReportFilters | PortfolioReportFilters, resource: str) -> BinaryIO:
        """Complete the whole filtered export before audit and response bytes.

        Returns:
            A rewound transient spool; response cleanup owns its lifetime.
        """
        if resource not in ('application', 'portfolio'):
            raise ValueError('Unsupported report')
        require_permission(principal, 'view', resource)
        require_permission(principal, 'export', resource)
        scope = portfolio_scope(principal)
        repository = self.applications if resource == 'application' else self.portfolios
        columns = APPLICATION_COLUMNS if resource == 'application' else PORTFOLIO_COLUMNS
        spool = SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b')
        completed = False
        try:
            await run_in_threadpool(spool.write, csv_line(columns))
            count = 0
            async for document in repository.iterate(scope, filters):
                row = ApplicationReportRow.model_validate(document) if resource == 'application' else await self.portfolio_row(document, scope)
                await run_in_threadpool(spool.write, csv_line(columns, row.model_dump(mode='json')))
                count += 1
            await run_in_threadpool(spool.seek, 0)
            # Record only validated filter names: free-text filters can contain secrets.
            summary = sorted(filters.model_dump(exclude_none=True, exclude={'page', 'pageSize', 'format'}))
            await self.audit.record(principal.user_id, principal.user_name, 'export', resource, None, f'Exported {resource} report: {count} rows; filter fields: {summary}')
            completed = True
            return spool
        except OSError as exc:
            raise DomainError('DEPENDENCY_UNAVAILABLE', 'Unable to generate export', 503) from exc
        finally:
            if not completed:
                await run_in_threadpool(spool.close)
