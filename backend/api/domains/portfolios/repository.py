"""Query and mutate portfolios through the single injected async Mongo database."""
import re
from datetime import datetime
from typing import Any
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from api.core.policy import Scope
from api.domains.portfolios.schemas import PortfolioFilters

class PortfolioRepository:
    """Keep scope predicates inseparable from inventory and relation queries."""
    def __init__(self, database: AsyncDatabase) -> None:
        """Reuse pooled collections, including related apps until their slice exists."""
        self.portfolios = database.portfolios
        self.applications = database.applications
        self.users = database.users

    def predicate(self, scope: Scope, filters: PortfolioFilters, identifier: ObjectId | None = None) -> dict[str, Any]:
        """AND trusted scope with escaped search and validated exact filters."""
        terms: list[dict[str, Any]] = [scope.predicate('_id')]
        if identifier is not None:
            terms.append({'_id': identifier})
        if filters.search is not None:
            terms.append({'name': {'$regex': re.escape(filters.search), '$options': 'i'}})
        for key in ('status', 'productArea'):
            if getattr(filters, key) is not None:
                terms.append({key: getattr(filters, key)})
        return {'$and': terms}

    async def list_page(self, scope: Scope, filters: PortfolioFilters) -> tuple[list[dict[str, Any]], int]:
        """Count the same filtered set and sort pages deterministically."""
        query = self.predicate(scope, filters)
        total = await self.portfolios.count_documents(query)
        rows = await self.portfolios.find(query).sort([('name', 1), ('_id', 1)]).skip((filters.page - 1) * filters.pageSize).limit(filters.pageSize).to_list(None)
        return rows, total

    async def get(self, scope: Scope, identifier: ObjectId) -> dict[str, Any] | None:
        """Hide inaccessible IDs with the same query as missing IDs."""
        return await self.portfolios.find_one(self.predicate(scope, PortfolioFilters(), identifier))

    async def measures(self, scope: Scope, identifier: ObjectId) -> dict[str, Any]:
        """Aggregate authorized applications without storing derived portfolio values."""
        cursor = await self.applications.aggregate([
            {'$match': {'$and': [scope.predicate(), {'portfolioId': identifier}]}},
            {'$group': {'_id': None, 'count': {'$sum': 1}, 'quality': {'$avg': '$qualityScore'}}},
        ])
        rows = await cursor.to_list(None)
        return rows[0] if rows else {'count': 0, 'quality': None}

    async def related(self, scope: Scope, identifier: ObjectId, page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        """Return bounded allowlisted application summaries with an explicit scope."""
        query = {'$and': [scope.predicate(), {'portfolioId': identifier}]}
        total = await self.applications.count_documents(query)
        fields = {key: 1 for key in ('name', 'criticality', 'tier', 'lifecycleStatus', 'riskLevel')}
        rows = await self.applications.find(query, fields).sort([('name', 1), ('_id', 1)]).skip((page - 1) * size).limit(size).to_list(None)
        return rows, total

    async def insert(self, document: dict[str, Any]) -> ObjectId:
        """Let the unique index arbitrate duplicate creation."""
        return (await self.portfolios.insert_one(document)).inserted_id

    async def update(self, scope: Scope, snapshot: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any] | None:
        """Atomically compare the stored edit timestamp before replacing supplied fields."""
        query = {'$and': [self.predicate(scope, PortfolioFilters(), snapshot['_id']), {'updatedAt': snapshot['updatedAt']}]}
        return await self.portfolios.find_one_and_update(query, {'$set': changes}, return_document=ReturnDocument.AFTER)

    async def referenced(self, identifier: ObjectId) -> bool:
        """Reject both application links and user assignments instead of cascading."""
        return await self.applications.find_one({'portfolioId': identifier}, {'_id': 1}) is not None or await self.users.find_one({'portfolioAccess': identifier}, {'_id': 1}) is not None

    async def begin_delete(self, scope: Scope, identifier: ObjectId, updated_at: datetime) -> bool:
        """Exclude new reference reservations before checking existing references."""
        query = {'$and': [self.predicate(scope, PortfolioFilters(), identifier), {'updatedAt': updated_at, '_applicationDeleting': {'$ne': True}, '_applicationReservations.0': {'$exists': False}}]}
        return (await self.portfolios.update_one(query, {'$set': {'_applicationDeleting': True}})).matched_count == 1

    async def cancel_delete(self, identifier: ObjectId) -> None:
        """Reopen a portfolio after a confirmed rejected deletion."""
        await self.portfolios.update_one({'_id': identifier}, {'$unset': {'_applicationDeleting': ''}})

    async def delete(self, scope: Scope, identifier: ObjectId, updated_at: datetime) -> bool:
        """Delete only the previously observed scoped portfolio snapshot."""
        query = {'$and': [self.predicate(scope, PortfolioFilters(), identifier), {'updatedAt': updated_at, '_applicationDeleting': True, '_applicationReservations.0': {'$exists': False}}]}
        return (await self.portfolios.delete_one(query)).deleted_count == 1
