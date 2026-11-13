"""Persist application inventory and durable portfolio reference reservations."""
import re
from datetime import datetime
from typing import Any
from collections.abc import AsyncIterator
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.asynchronous.database import AsyncDatabase
from api.core.policy import Scope
from api.domains.applications.schemas import ApplicationFilters

class ApplicationRepository:
    """Use injected pooled Mongo collections, never process-local locks."""
    def __init__(self, database: AsyncDatabase) -> None:
        """Bind related collections from the same pooled database."""
        self.applications = database.applications
        self.portfolios = database.portfolios

    def predicate(self, scope: Scope, filters: ApplicationFilters, identifier: ObjectId | None = None) -> dict[str, Any]:
        """Keep each caller filter conjunctive with immutable authorization scope."""
        terms = [scope.predicate()]
        if identifier is not None:
            terms.append({'_id': identifier})
        for key in ('name', 'search'):
            if getattr(filters, key) is not None:
                terms.append({'name': {'$regex': re.escape(getattr(filters, key)), '$options': 'i'}})
        for key in ('portfolioId', 'productArea', 'criticality', 'lifecycleStatus', 'riskLevel', 'tier'):
            value = getattr(filters, key)
            if value is not None:
                terms.append({key: ObjectId(value) if key == 'portfolioId' else value})
        return {'$and': terms}

    async def list_page(self, scope: Scope, filters: ApplicationFilters) -> tuple[list[dict[str, Any]], int]:
        """Count and read the same stably ordered, bounded result set."""
        query = self.predicate(scope, filters)
        total = await self.applications.count_documents(query)
        rows = await self.applications.find(query).sort([('name', 1), ('_id', 1)]).skip((filters.page - 1) * filters.pageSize).limit(filters.pageSize).to_list(None)
        return rows, total

    async def get(self, scope: Scope, identifier: ObjectId) -> dict[str, Any] | None:
        """Resolve missing and hidden applications identically."""
        return await self.applications.find_one(self.predicate(scope, ApplicationFilters(), identifier))

    async def portfolio(self, scope: Scope, identifier: ObjectId) -> dict[str, Any] | None:
        """Resolve parent context only within the same scope."""
        return await self.portfolios.find_one({'$and': [scope.predicate('_id'), {'_id': identifier}]})

    async def reserve(self, scope: Scope, identifier: ObjectId, token: str) -> bool:
        """Pin a parent before mutation; atomic deletion predicates exclude pins.

        Notes:
            Reservations never expire automatically. A crashed or ambiguous write leaves
            a conservative deletion blocker requiring operator reconciliation.
        """
        result = await self.portfolios.update_one({'$and': [scope.predicate('_id'), {'_id': identifier, '_applicationDeleting': {'$ne': True}}]}, {'$addToSet': {'_applicationReservations': token}})
        return result.matched_count == 1

    async def release(self, identifier: ObjectId, token: str) -> None:
        """Remove only this completed operation's durable reference reservation."""
        await self.portfolios.update_one({'_id': identifier}, {'$pull': {'_applicationReservations': token}})

    async def insert(self, document: dict[str, Any]) -> ObjectId:
        """Let the existing unique name index arbitrate concurrent duplicates."""
        return (await self.applications.insert_one(document)).inserted_id

    async def update(self, scope: Scope, snapshot: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any] | None:
        """Compare both current portfolio and timestamp in the atomic update."""
        query = {'$and': [self.predicate(scope, ApplicationFilters(), snapshot['_id']), {'updatedAt': snapshot['updatedAt'], 'portfolioId': snapshot['portfolioId']}]}
        return await self.applications.find_one_and_update(query, {'$set': changes}, return_document=ReturnDocument.AFTER)

    async def delete(self, scope: Scope, snapshot: dict[str, Any]) -> bool:
        """Delete only the observed scoped application version."""
        query = {'$and': [self.predicate(scope, ApplicationFilters(), snapshot['_id']), {'updatedAt': snapshot['updatedAt'], 'portfolioId': snapshot['portfolioId']}]}
        return (await self.applications.delete_one(query)).deleted_count == 1

    async def dashboard_totals(self, scope: Scope, filters: ApplicationFilters) -> list[dict[str, Any]]:
        """Aggregate exact sums after the shared scope-first filter predicate."""
        cursor = await self.applications.aggregate([
            {'$match': self.predicate(scope, filters)},
            {'$group': {
                '_id': '$portfolioId', 'count': {'$sum': 1},
                'quality': {'$sum': '$qualityScore'}, 'health': {'$sum': '$applicationHealthScore'},
                'automation': {'$sum': '$automationCoverage'},
                'critical_defects': {'$sum': '$openCriticalDefects'},
                'at_risk': {'$sum': {'$cond': [{'$eq': ['$riskLevel', 'High']}, 1, 0]}},
            }},
        ])
        return await cursor.to_list(None)

    async def iterate(self, scope: Scope, filters: ApplicationFilters) -> AsyncIterator[dict[str, Any]]:
        """Stream the entire inventory predicate in bounded driver batches."""
        fields = {key: 1 for key in ('name', 'portfolioId', 'criticality', 'tier', 'lifecycleStatus', 'applicationHealthScore', 'qualityScore', 'automationCoverage', 'unitTestCoverage', 'openDefects', 'openCriticalDefects', 'riskLevel')}
        cursor = self.applications.find(self.predicate(scope, filters), fields).sort([('name', 1), ('_id', 1)]).batch_size(100)
        try:
            async for row in cursor:
                yield row
        finally:
            await cursor.close()

    async def seed_ensure(self, document: dict[str, Any]) -> dict[str, Any]:
        """Insert a missing natural key only; preserve operator edits on repeat runs."""
        query = {'name': document['name']}
        try:
            await self.applications.update_one(query, {'$setOnInsert': document}, upsert=True)
        except DuplicateKeyError:
            # The unique natural-key winner is returned below, never overwritten.
            pass
        row = await self.applications.find_one(query)
        if row is None:
            raise RuntimeError('Seed record disappeared')
        return row
