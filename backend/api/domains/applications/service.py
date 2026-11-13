"""Compose scope, durable reference safety, optimistic writes and required audit."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from typing import Any
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from api.core.audit import AuditService
from api.core.errors import DomainError
from api.core.policy import Principal, portfolio_scope, require_permission
from api.domains.applications.repository import ApplicationRepository
from api.domains.applications.schemas import Application, ApplicationCreate, ApplicationUpdate, ApplicationFilters, ApplicationPage, ApplicationDetail, PortfolioSummary, DeletedApplication

class ApplicationService:
    """Keep standalone Mongo partial-write behavior explicit and fail closed."""
    def __init__(self, repository: ApplicationRepository, audit: AuditService) -> None:
        """Bind inventory and required audit collaborators."""
        self.repository, self.audit = repository, audit

    async def snapshot(self, principal: Principal, identifier: ObjectId) -> dict[str, Any]:
        """Hide inaccessible inventory before considering current or destination parents."""
        result = await self.repository.get(portfolio_scope(principal), identifier)
        if result is None:
            raise DomainError('NOT_FOUND', 'Application not found', 404)
        return result

    async def list(self, principal: Principal, filters: ApplicationFilters) -> ApplicationPage:
        """Authorize before executing bounded conjunctive inventory queries."""
        require_permission(principal, 'view', 'application')
        rows, total = await self.repository.list_page(portfolio_scope(principal), filters)
        return ApplicationPage(items=[Application.model_validate(row) for row in rows], page=filters.page, pageSize=filters.pageSize, total=total)

    async def detail(self, principal: Principal, identifier: ObjectId) -> ApplicationDetail:
        """Return complete application facts and only safe visible parent context."""
        require_permission(principal, 'view', 'application')
        row = await self.snapshot(principal, identifier)
        parent = await self.repository.portfolio(portfolio_scope(principal), row['portfolioId'])
        if parent is None:
            raise DomainError('NOT_FOUND', 'Application not found', 404)
        return ApplicationDetail.model_validate({**row, 'portfolio': PortfolioSummary.model_validate(parent)})

    async def create(self, principal: Principal, request: ApplicationCreate) -> Application:
        """Reserve the destination before writing, then require audit before success."""
        require_permission(principal, 'create', 'application')
        scope = portfolio_scope(principal)
        parent, token = ObjectId(request.portfolioId), uuid4().hex
        if not await self.repository.reserve(scope, parent, token):
            raise DomainError('NOT_FOUND', 'Portfolio not found', 404)
        now, identifier = datetime.now(timezone.utc), ObjectId()
        document = {**request.model_dump(mode='json'), '_id': identifier, 'portfolioId': parent, 'createdAt': now, 'updatedAt': now}
        try:
            await self.repository.insert(document)
        except DuplicateKeyError:
            await self.repository.release(parent, token)
            raise
        # Do not release on ambiguous driver failures: the write may have persisted.
        await self.repository.release(parent, token)
        await self.audit.record(principal.user_id, principal.user_name, 'create', 'application', identifier, 'Created application')
        return Application.model_validate(await self.snapshot(principal, identifier))

    async def update(self, principal: Principal, identifier: ObjectId, request: ApplicationUpdate) -> Application:
        """Pin current and destination parents while atomically comparing the edit version."""
        require_permission(principal, 'edit', 'application')
        snapshot = await self.snapshot(principal, identifier)
        if request.expectedUpdatedAt is not None and request.expectedUpdatedAt != snapshot['updatedAt']:
            raise DomainError('CONFLICT', 'Application changed. Reload and try again.', 409)
        scope, token = portfolio_scope(principal), uuid4().hex
        destination = ObjectId(request.portfolioId) if request.portfolioId is not None else snapshot['portfolioId']
        parents = sorted({snapshot['portfolioId'], destination}, key=str)
        reserved: list[ObjectId] = []
        for parent in parents:
            if not await self.repository.reserve(scope, parent, token):
                for pinned in reserved:
                    await self.repository.release(pinned, token)
                raise DomainError('NOT_FOUND', 'Portfolio not found', 404)
            reserved.append(parent)
        changes = request.model_dump(mode='json', exclude_unset=True, exclude={'expectedUpdatedAt'})
        if 'portfolioId' in changes:
            changes['portfolioId'] = destination
        changes['updatedAt'] = max(datetime.now(timezone.utc), snapshot['updatedAt'] + timedelta(milliseconds=1))
        try:
            updated = await self.repository.update(scope, snapshot, changes)
        except DuplicateKeyError:
            for parent in reserved:
                await self.repository.release(parent, token)
            raise
        for parent in reserved:
            await self.repository.release(parent, token)
        if updated is None:
            await self.snapshot(principal, identifier)
            raise DomainError('CONFLICT', 'Application changed. Reload and try again.', 409)
        await self.audit.record(principal.user_id, principal.user_name, 'edit', 'application', identifier, 'Updated application')
        return Application.model_validate(updated)

    async def delete(self, principal: Principal, identifier: ObjectId, expected: datetime | None = None) -> DeletedApplication:
        """Allow only authorized Administrator deletion of the observed version."""
        require_permission(principal, 'delete', 'application')
        snapshot = await self.snapshot(principal, identifier)
        if expected is not None and expected != snapshot['updatedAt']:
            raise DomainError('CONFLICT', 'Application changed. Reload and try again.', 409)
        if not await self.repository.delete(portfolio_scope(principal), snapshot):
            await self.snapshot(principal, identifier)
            raise DomainError('CONFLICT', 'Application changed. Reload and try again.', 409)
        await self.audit.record(principal.user_id, principal.user_name, 'delete', 'application', identifier, 'Deleted application')
        return DeletedApplication(id=str(identifier))
