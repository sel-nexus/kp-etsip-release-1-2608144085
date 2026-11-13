"""Persist fixed roles through the lifespan-owned async Mongo pool."""
from typing import Any
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.asynchronous.database import AsyncDatabase
from api.core.policy import ROLE_MAXIMUM

class RoleRepository:
    """Keep all collection access separate from bounded role business rules."""
    def __init__(self, database: AsyncDatabase) -> None:
        """Reuse the injected collection without opening a client."""
        self.collection = database.roles

    async def list(self) -> list[dict[str, Any]]:
        """Query only the six supported names, including incomplete setup states."""
        return await self.collection.find({'name': {'$in': list(ROLE_MAXIMUM)}}).sort('name', 1).limit(6).to_list(None)

    async def get(self, identifier: ObjectId) -> dict[str, Any] | None:
        """Hide unsupported stored roles as missing resources."""
        return await self.collection.find_one({'_id': identifier, 'name': {'$in': list(ROLE_MAXIMUM)}})

    async def ensure(self, document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Use insert-only upsert and unique name arbitration without resetting edits."""
        try:
            result = await self.collection.update_one({'name': document['name']}, {'$setOnInsert': document}, upsert=True)
            inserted = result.upserted_id is not None
        except DuplicateKeyError:
            # A concurrent insert won the unique natural key; return its current state.
            inserted = False
        row = await self.collection.find_one({'name': document['name']})
        if row is None:
            raise RuntimeError('Ensured role disappeared')
        return row, inserted

    async def update(self, snapshot: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any] | None:
        """Atomically compare the observed timestamp before replacing permissions."""
        return await self.collection.find_one_and_update(
            {'_id': snapshot['_id'], 'name': snapshot['name'], 'updatedAt': snapshot['updatedAt']},
            {'$set': changes}, return_document=ReturnDocument.AFTER)
