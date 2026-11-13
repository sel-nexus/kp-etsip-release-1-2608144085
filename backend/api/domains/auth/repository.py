"""Look up persisted users and roles through the pooled async driver."""
from datetime import datetime
from typing import Any
from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo import ReturnDocument

class AuthRepository:
    """Own identity collection reads and the login timestamp write."""
    def __init__(self, database: AsyncDatabase) -> None:
        """Bind current user and role collections."""
        self.users, self.roles = database['users'], database['roles']
    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        """Read credentials by normalized exact scalar email."""
        return await self.users.find_one({'email': email.lower()})
    async def get_by_id(self, user_id: ObjectId) -> dict[str, Any] | None:
        """Reload a current identity without fetching its password hash."""
        return await self.users.find_one({'_id': user_id}, {'passwordHash': 0})
    async def get_role(self, name: str) -> dict[str, Any] | None:
        """Reload stored role permissions for each protected request."""
        return await self.roles.find_one({'name': name})
    async def mark_login(self, user_id: ObjectId, now: datetime) -> dict[str, Any] | None:
        """Update only a still-active account and return persisted state."""
        return await self.users.find_one_and_update({'_id': user_id, 'status': 'Active'}, {'$set': {'lastLogin': now, 'updatedAt': now}}, return_document=ReturnDocument.AFTER, projection={'passwordHash': 0})

    async def get_credentials_by_id(self, user_id: ObjectId) -> dict[str, Any] | None:
        """Fetch credentials solely for the authenticated password operation."""
        return await self.users.find_one({'_id': user_id})

    async def update_profile(self, snapshot: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any] | None:
        """Conditionally replace profile state without overwriting a concurrent edit.

        Notes:
            Hash and password gate are updated together in one atomic user write.
        """
        predicate = {'_id': snapshot['_id'], 'status': 'Active', 'updatedAt': snapshot['updatedAt'],
                     'role': snapshot['role'], 'portfolioAccess': snapshot['portfolioAccess'],
                     'mustChangePassword': snapshot.get('mustChangePassword', False)}
        if 'passwordHash' in snapshot:
            predicate['passwordHash'] = snapshot['passwordHash']
        return await self.users.find_one_and_update(predicate, {'$set': changes},
            return_document=ReturnDocument.AFTER, projection={'passwordHash': 0})
