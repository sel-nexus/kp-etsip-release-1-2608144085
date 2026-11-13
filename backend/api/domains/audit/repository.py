"""Own audit collection inserts and typed global history queries."""
from collections.abc import AsyncIterator
from typing import Any
from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from api.domains.audit.schemas import AuditFilters

PUBLIC_FIELDS = {field: 1 for field in ('_id', 'timestamp', 'userId', 'userName', 'action', 'entityType', 'entityId', 'details')}
SORT = [('timestamp', -1), ('_id', -1)]

class AuditRepository:
    """Use the injected pool without portfolio joins or raw caller predicates."""
    def __init__(self, database: AsyncDatabase) -> None:
        """Retain the same collection for all evidence operations."""
        self.collection = database['audit_logs']

    async def insert(self, document: dict[str, Any]) -> ObjectId:
        """Persist a service-owned snapshot without retrying ambiguous writes."""
        return (await self.collection.insert_one(document)).inserted_id

    def predicate(self, filters: AuditFilters) -> dict[str, object]:
        """AND every validated user, action and inclusive date constraint."""
        query: dict[str, object] = {}
        if filters.userId is not None:
            query['userId'] = ObjectId(filters.userId)
        if filters.action is not None:
            query['action'] = filters.action
        dates = {}
        if filters.from_date is not None:
            dates['$gte'] = filters.from_date
        if filters.to_date is not None:
            dates['$lte'] = filters.to_date
        if dates:
            query['timestamp'] = dates
        return query

    async def page(self, filters: AuditFilters) -> tuple[list[dict[str, Any]], int]:
        """Count and fetch a bounded page under the identical predicate."""
        query = self.predicate(filters)
        total = await self.collection.count_documents(query)
        rows = await self.collection.find(query, PUBLIC_FIELDS).sort(SORT).skip((filters.page - 1) * filters.pageSize).limit(filters.pageSize).to_list(filters.pageSize)
        return rows, total

    async def iterate(self, filters: AuditFilters) -> AsyncIterator[dict[str, Any]]:
        """Yield the full filtered set in bounded driver batches, not just its page."""
        cursor = self.collection.find(self.predicate(filters), PUBLIC_FIELDS).sort(SORT).batch_size(100)
        try:
            async for row in cursor:
                yield row
        finally:
            await cursor.close()
