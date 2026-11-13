"""Enforce portfolio policy, optimistic writes, derived measures and required audit."""
from datetime import datetime, timezone, timedelta
from math import floor
from typing import Any
from bson import ObjectId
from api.core.audit import AuditService
from api.core.errors import DomainError
from api.core.policy import Principal, Scope, portfolio_scope, require_permission
from api.domains.portfolios.repository import PortfolioRepository
from api.domains.portfolios.schemas import Portfolio, PortfolioCreate, PortfolioUpdate, PortfolioFilters, PortfolioPage, PortfolioDetail, RelatedApplication, ApplicationPage, DeletedPortfolio

class PortfolioService:
    """Compose inventory operations without process-local persistence."""
    def __init__(self, repository: PortfolioRepository, audit: AuditService) -> None:
        """Bind persistence and mandatory durable audit collaborators."""
        self.repository, self.audit = repository, audit

    async def expose(self, document: dict[str, Any], scope: Scope) -> Portfolio:
        """Round nonnegative means half-up and preserve null for no applications."""
        measures = await self.repository.measures(scope, document['_id'])
        return Portfolio.model_validate({**document, 'applicationCount': measures['count'], 'qualityScore': None if measures['quality'] is None else floor(measures['quality'] + 0.5)})

    async def snapshot(self, principal: Principal, identifier: ObjectId) -> dict[str, Any]:
        """Resolve only visible portfolio records, returning a uniform not-found."""
        document = await self.repository.get(portfolio_scope(principal), identifier)
        if document is None:
            raise DomainError('NOT_FOUND', 'Portfolio not found', 404)
        return document

    async def list(self, principal: Principal, filters: PortfolioFilters) -> PortfolioPage:
        """Authorize before filtered list and derived aggregation."""
        require_permission(principal, 'view', 'portfolio')
        scope = portfolio_scope(principal)
        rows, total = await self.repository.list_page(scope, filters)
        return PortfolioPage(items=[await self.expose(row, scope) for row in rows], page=filters.page, pageSize=filters.pageSize, total=total)

    async def related(self, principal: Principal, identifier: ObjectId, filters: PortfolioFilters) -> ApplicationPage:
        """Check parent visibility before querying a scoped related page."""
        require_permission(principal, 'view', 'portfolio')
        await self.snapshot(principal, identifier)
        rows, total = await self.repository.related(portfolio_scope(principal), identifier, filters.page, filters.pageSize)
        return ApplicationPage(items=[RelatedApplication.model_validate(row) for row in rows], page=filters.page, pageSize=filters.pageSize, total=total)

    async def detail(self, principal: Principal, identifier: ObjectId) -> PortfolioDetail:
        """Return the required wrapper with a bounded initial related page."""
        require_permission(principal, 'view', 'portfolio')
        document = await self.snapshot(principal, identifier)
        apps = await self.related(principal, identifier, PortfolioFilters())
        return PortfolioDetail(portfolio=await self.expose(document, portfolio_scope(principal)), applications=apps.items)

    async def create(self, principal: Principal, request: PortfolioCreate) -> Portfolio:
        """Create only as Administrator and audit before reporting persisted success."""
        require_permission(principal, 'create', 'portfolio')
        now = datetime.now(timezone.utc)
        identifier = ObjectId()
        # Assigned administrators may not create an immediately inaccessible portfolio.
        if not portfolio_scope(principal).includes(identifier):
            raise DomainError('FORBIDDEN', 'Permission denied', 403)
        await self.repository.insert({'_id': identifier, **request.model_dump(), 'createdAt': now, 'updatedAt': now})
        await self.audit.record(principal.user_id, principal.user_name, 'create', 'portfolio', identifier, 'Created portfolio')
        return await self.expose(await self.snapshot(principal, identifier), portfolio_scope(principal))

    async def update(self, principal: Principal, identifier: ObjectId, request: PortfolioUpdate) -> Portfolio:
        """Reject stale supplied or concurrent timestamps without overwriting another edit."""
        require_permission(principal, 'edit', 'portfolio')
        snapshot = await self.snapshot(principal, identifier)
        if request.expectedUpdatedAt is not None and request.expectedUpdatedAt != snapshot['updatedAt']:
            raise DomainError('CONFLICT', 'Portfolio changed. Reload and try again.', 409)
        changes = request.model_dump(exclude_unset=True, exclude={'expectedUpdatedAt'})
        changes['updatedAt'] = max(datetime.now(timezone.utc), snapshot['updatedAt'] + timedelta(milliseconds=1))
        updated = await self.repository.update(portfolio_scope(principal), snapshot, changes)
        if updated is None:
            await self.snapshot(principal, identifier)
            raise DomainError('CONFLICT', 'Portfolio changed. Reload and try again.', 409)
        await self.audit.record(principal.user_id, principal.user_name, 'edit', 'portfolio', identifier, 'Updated portfolio')
        return await self.expose(updated, portfolio_scope(principal))

    async def delete(self, principal: Principal, identifier: ObjectId, expected: datetime | None = None) -> DeletedPortfolio:
        """Reject references and stale snapshots; never cascade linked records.

        Notes:
            The future application writer must coordinate reference creation with deletion.
            Standalone Mongo does not provide a cross-collection transaction here.
        """
        require_permission(principal, 'delete', 'portfolio')
        snapshot = await self.snapshot(principal, identifier)
        if expected is not None and expected != snapshot['updatedAt']:
            raise DomainError('CONFLICT', 'Portfolio changed. Reload and try again.', 409)
        if await self.repository.referenced(identifier):
            raise DomainError('CONFLICT', 'Portfolio is referenced and cannot be deleted', 409)
        if not await self.repository.delete(portfolio_scope(principal), identifier, snapshot['updatedAt']):
            await self.snapshot(principal, identifier)
            raise DomainError('CONFLICT', 'Portfolio changed. Reload and try again.', 409)
        await self.audit.record(principal.user_id, principal.user_name, 'delete', 'portfolio', identifier, 'Deleted portfolio')
        return DeletedPortfolio(id=str(identifier))
