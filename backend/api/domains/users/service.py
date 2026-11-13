"""Compose administrator policy, reference safety and required audit writes."""
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from api.core.audit import AuditService
from api.core.errors import DomainError
from api.core.policy import Principal, require_permission
from api.core.security import hash_password
from api.domains.users.repository import UserRepository
from api.domains.users.schemas import User, UserCreate, UserUpdate, UserFilters, UserPage, DeactivatedUser

class UserService:
    """Keep standalone Mongo partial and ambiguous writes honest."""
    def __init__(self, repository: UserRepository, audit: AuditService) -> None:
        """Inject real persistence and mandatory audit collaborators."""
        self.repository, self.audit = repository, audit

    async def snapshot(self, identifier: ObjectId) -> dict[str, Any]:
        """Resolve missing users uniformly without exposing credential metadata."""
        row = await self.repository.get(identifier)
        if row is None:
            raise DomainError('NOT_FOUND', 'User not found', 404)
        return row

    async def detail(self, principal: Principal, identifier: ObjectId) -> User:
        """Return the complete safe account only to an authorized administrator."""
        require_permission(principal, 'administer', 'user')
        return User.model_validate(await self.snapshot(identifier))

    async def validate(self, changes: dict[str, Any], exclude: ObjectId | None = None) -> None:
        """Reject invalid references and duplicate email before writing any pins."""
        if 'role' in changes and not await self.repository.role_exists(changes['role']):
            raise DomainError('VALIDATION_ERROR', 'Role does not exist', 422, {'role': 'Select an existing supported role'})
        if 'portfolioAccess' in changes and not await self.repository.portfolios_exist(changes['portfolioAccess']):
            raise DomainError('VALIDATION_ERROR', 'Portfolio assignment does not exist', 422, {'portfolioAccess': 'Select existing portfolios'})
        if 'email' in changes and await self.repository.email_exists(changes['email'], exclude):
            raise DomainError('CONFLICT', 'Email already exists', 409)

    async def pin(self, parents: list[ObjectId], token: str) -> list[ObjectId]:
        """Pin old and destination parents in stable order before account persistence.

        Notes:
            Ambiguous reservation or account writes retain pins for operations
            reconciliation. No in-memory lock or cross-document transaction is claimed.
        """
        reserved: list[ObjectId] = []
        for parent in sorted(set(parents), key=str):
            if not await self.repository.reserve(parent, token):
                await self.release(reserved, token)
                raise DomainError('CONFLICT', 'Portfolio references changed. Reload and try again.', 409)
            reserved.append(parent)
        return reserved

    async def release(self, parents: list[ObjectId], token: str) -> None:
        """Release only this known finished operation's conservative deletion blockers."""
        for parent in parents:
            await self.repository.release(parent, token)

    async def create(self, principal: Principal, request: UserCreate) -> User:
        """Validate, hash off-thread, pin references and require durable create audit."""
        require_permission(principal, 'administer', 'user')
        document = request.model_dump(exclude={'password'})
        document['portfolioAccess'] = [ObjectId(item) for item in request.portfolioAccess]
        await self.validate(document)
        document['passwordHash'] = await hash_password(request.password.get_secret_value())
        now, identifier, token = datetime.now(timezone.utc), ObjectId(), 'user:' + uuid4().hex
        document.update({'_id': identifier, 'createdAt': now, 'updatedAt': now, 'authSource': 'local', 'lastLogin': None, 'mustChangePassword': False, 'defaultLandingPage': None})
        parents = await self.pin(document['portfolioAccess'], token)
        try:
            await self.repository.insert(document)
        except DuplicateKeyError:
            await self.release(parents, token)
            raise
        # Driver failures may have persisted: deliberately retain pins on ambiguity.
        await self.release(parents, token)
        await self.audit.record(principal.user_id, principal.user_name, 'create', 'user', identifier, 'Created user')
        return User.model_validate(await self.snapshot(identifier))

    async def persist(self, principal: Principal, snapshot: dict[str, Any], changes: dict[str, Any], action: str) -> User:
        """Compare the observed account version and audit all successful changes."""
        token = 'user:' + uuid4().hex
        parents = await self.pin(snapshot['portfolioAccess'] + changes.get('portfolioAccess', []), token) if 'portfolioAccess' in changes else []
        changes['updatedAt'] = max(datetime.now(timezone.utc), snapshot['updatedAt'] + timedelta(milliseconds=1))
        try:
            updated = await self.repository.update(snapshot, changes)
        except DuplicateKeyError:
            await self.release(parents, token)
            raise
        await self.release(parents, token)
        if updated is None:
            await self.snapshot(snapshot['_id'])
            raise DomainError('CONFLICT', 'User changed. Reload and try again.', 409)
        if updated['role'] != snapshot['role']:
            await self.audit.record(principal.user_id, principal.user_name, 'roleChange', 'user', snapshot['_id'], 'Changed user role')
        await self.audit.record(principal.user_id, principal.user_name, action, 'user', snapshot['_id'], 'Deactivated user' if action == 'delete' else 'Updated user')
        return User.model_validate(updated)

    async def update(self, principal: Principal, identifier: ObjectId, request: UserUpdate) -> User:
        """Validate partial edits and optional stale version before coordination writes."""
        require_permission(principal, 'administer', 'user')
        snapshot = await self.snapshot(identifier)
        self.check_expected(snapshot, request.expectedUpdatedAt)
        changes = request.model_dump(exclude_unset=True, exclude={'expectedUpdatedAt'})
        if 'portfolioAccess' in changes:
            changes['portfolioAccess'] = [ObjectId(item) for item in changes['portfolioAccess']]
        await self.validate(changes, identifier)
        return await self.persist(principal, snapshot, changes, 'edit')

    def check_expected(self, snapshot: dict[str, Any], expected: datetime | None) -> None:
        """Reject a stale supplied version without any mutation."""
        if expected is not None and expected != snapshot['updatedAt']:
            raise DomainError('CONFLICT', 'User changed. Reload and try again.', 409)

    async def delete(self, principal: Principal, identifier: ObjectId, expected: datetime | None = None) -> DeactivatedUser:
        """Soft deactivate; existing tokens fail live identity resolution next request."""
        require_permission(principal, 'administer', 'user')
        snapshot = await self.snapshot(identifier)
        self.check_expected(snapshot, expected)
        await self.persist(principal, snapshot, {'status': 'Inactive'}, 'delete')
        return DeactivatedUser(id=str(identifier))

    async def list(self, principal: Principal, filters: UserFilters) -> UserPage:
        """Require administer before any bounded account query."""
        require_permission(principal, 'administer', 'user')
        rows, total = await self.repository.list_page(filters)
        return UserPage(items=[User.model_validate(row) for row in rows], page=filters.page, pageSize=filters.pageSize, total=total)

