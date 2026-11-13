"""Authorize global history and complete exports before recording success."""
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from starlette.concurrency import run_in_threadpool
from api.core.audit import AuditService
from api.core.csv import csv_line
from api.core.errors import DomainError
from api.core.policy import Principal, require_permission
from api.domains.audit.repository import AuditRepository
from api.domains.audit.schemas import AuditFilters, AuditPage, AuditRow

CSV_COLUMNS = ('timestamp', 'userId', 'userName', 'action', 'entityType', 'entityId', 'details')

class AuditHistoryService:
    """Keep review and export independently permissioned and read-only."""
    def __init__(self, repository: AuditRepository, audit: AuditService) -> None:
        """Compose query and required writer over the application pool."""
        self.repository, self.audit = repository, audit

    async def search(self, principal: Principal, filters: AuditFilters) -> AuditPage:
        """Authorize before fetching an allowlisted, bounded history page."""
        require_permission(principal, 'view', 'audit')
        rows, total = await self.repository.page(filters)
        return AuditPage(items=[AuditRow.model_validate(row) for row in rows], page=filters.page, pageSize=filters.pageSize, total=total)

    async def export(self, principal: Principal, filters: AuditFilters) -> BinaryIO:
        """Finish bounded CSV generation and evidence before releasing bytes.

        Returns:
            A rewound transient spool owned by the response, never durable state.
        Raises:
            DomainError: If permission, generation or required audit fails.
        """
        require_permission(principal, 'export', 'audit')
        spool = SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b')
        completed = False
        try:
            await run_in_threadpool(spool.write, csv_line(CSV_COLUMNS))
            count = 0
            async for document in self.repository.iterate(filters):
                row = AuditRow.model_validate(document).model_dump(mode='json')
                await run_in_threadpool(spool.write, csv_line(CSV_COLUMNS, row))
                count += 1
            await run_in_threadpool(spool.seek, 0)
            summary = filters.model_dump(mode='json', by_alias=True, exclude_none=True, exclude={'page', 'pageSize', 'format'})
            await self.audit.record(principal.user_id, principal.user_name, 'export', 'audit', None, f'Exported audit history: {count} rows; filters: {summary}')
            completed = True
            return spool
        except OSError as exc:
            raise DomainError('DEPENDENCY_UNAVAILABLE', 'Unable to generate export', 503) from exc
        finally:
            if not completed:
                await run_in_threadpool(spool.close)
