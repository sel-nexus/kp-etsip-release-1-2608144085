"""Persist users with durable portfolio pins shared with inventory deletion."""
import re
from typing import Any
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.collation import Collation
from pymongo.asynchronous.database import AsyncDatabase
from api.domains.users.schemas import UserFilters

EMAIL_COLLATION = Collation(locale='en', strength=2)

class UserRepository:
    """Use only collections from the injected pooled async database."""
    def __init__(self, database: AsyncDatabase) -> None:
        """Bind account and reference collections without opening another client."""
        self.users, self.roles, self.portfolios = database.users, database.roles, database.portfolios

    async def get(self, identifier: ObjectId) -> dict[str, Any] | None:
        """Read safe mapping inputs without fetching credential hashes."""
        return await self.users.find_one({'_id': identifier}, {'passwordHash': 0})

    async def list_page(self, filters: UserFilters) -> tuple[list[dict[str, Any]], int]:
        """Apply escaped name/email search and exact filters in Mongo."""
        query: dict[str, Any] = {}
        if filters.search:
            expression = {'$regex': re.escape(filters.search), '$options': 'i'}
            query['$or'] = [{'name': expression}, {'email': expression}]
        for key in ('role', 'status'):
            if getattr(filters, key) is not None:
                query[key] = getattr(filters, key)
        total = await self.users.count_documents(query)
        rows = await self.users.find(query, {'passwordHash': 0}).sort([('name', 1), ('_id', 1)]).skip((filters.page - 1) * filters.pageSize).limit(filters.pageSize).to_list(None)
        return rows, total

    async def role_exists(self, role: str) -> bool:
        """Require a current supported role definition rather than inventing one."""
        return await self.roles.find_one({'name': role}, {'_id': 1}) is not None

    async def email_exists(self, email: str, exclude: ObjectId | None = None) -> bool:
        """Check legacy mixed-case accounts using the unique-index collation."""
        query: dict[str, Any] = {'email': email}
        if exclude is not None:
            query['_id'] = {'$ne': exclude}
        return await self.users.find_one(query, {'_id': 1}, collation=EMAIL_COLLATION) is not None

    async def portfolios_exist(self, identifiers: list[ObjectId]) -> bool:
        """Validate all destinations before any durable coordination mutation."""
        return await self.portfolios.count_documents({'_id': {'$in': identifiers}, '_applicationDeleting': {'$ne': True}}) == len(set(identifiers))

    async def reserve(self, identifier: ObjectId, token: str) -> bool:
        """Atomically pin a parent unless durable deletion intent already won."""
        result = await self.portfolios.update_one({'_id': identifier, '_applicationDeleting': {'$ne': True}}, {'$addToSet': {'_applicationReservations': token}})
        return result.matched_count == 1

    async def release(self, identifier: ObjectId, token: str) -> None:
        """Release only a known completed operation; crashed pins never expire."""
        await self.portfolios.update_one({'_id': identifier}, {'$pull': {'_applicationReservations': token}})

    async def insert(self, document: dict[str, Any]) -> ObjectId:
        """Let the collated unique email index arbitrate concurrent creation."""
        return (await self.users.insert_one(document)).inserted_id

    async def update(self, snapshot: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any] | None:
        """Compare timestamp and old assignments before the atomic account write."""
        return await self.users.find_one_and_update({'_id': snapshot['_id'], 'updatedAt': snapshot['updatedAt'], 'portfolioAccess': snapshot['portfolioAccess']}, {'$set': changes}, projection={'passwordHash': 0}, return_document=ReturnDocument.AFTER)

    async def seed_ensure(self, document: dict[str, Any]) -> dict[str, Any]:
        """Insert a missing natural key only; preserve operator edits on repeat runs."""
        query = {'email': document['email']}
        try:
            await self.users.update_one(query, {'$setOnInsert': document}, upsert=True, collation=EMAIL_COLLATION)
        except DuplicateKeyError:
            # The unique natural-key winner is returned below, never overwritten.
            pass
        row = await self.users.find_one(query, {'passwordHash': 0}, collation=EMAIL_COLLATION)
        if row is None:
            raise RuntimeError('Seed record disappeared')
        return row
