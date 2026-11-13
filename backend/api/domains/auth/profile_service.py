"""Compose live profile policy, conditional user writes, and required safe audits."""
from datetime import datetime, timezone, timedelta
from typing import Any
from api.core.errors import DomainError
from api.core.policy import Principal, password_gate, require_permission
from api.core.security import hash_password, verify_password
from api.domains.auth.service import AuthService
from api.domains.auth.schemas import SafeUser
from api.domains.auth.profile_schemas import PasswordChangeRequest, PreferencesRequest, LandingPage

class ProfileService:
    """Reuse session identity mapping without widening public credential access."""
    def __init__(self, auth: AuthService) -> None:
        """Bind the request's current identity and durable audit collaborators."""
        self.auth = auth
        self.repository = auth.repository

    async def persist(self, snapshot: dict[str, Any], changes: dict[str, Any], details: str) -> SafeUser:
        """Require conditional persistence and audit before returning success.

        Raises:
            DomainError: A concurrent edit or audit failure prevents success.
        """
        now = datetime.now(timezone.utc)
        changes['updatedAt'] = max(now, snapshot['updatedAt'] + timedelta(milliseconds=1))
        updated = await self.repository.update_profile(snapshot, changes)
        if updated is None:
            await self.auth.principal_for_user(await self.repository.get_by_id(snapshot['_id']))
            raise DomainError('CONFLICT', 'Profile changed. Reload and try again.', 409)
        await self.auth.audit.record(updated['_id'], updated['name'], 'edit', 'user', updated['_id'], details)
        return self.auth.safe_user(updated)

    async def change_password(self, principal: Principal, request: PasswordChangeRequest) -> SafeUser:
        """Verify current credential and atomically replace hash and clear the gate."""
        user = await self.repository.get_credentials_by_id(principal.user_id)
        await self.auth.principal_for_user(user)
        if not await verify_password(request.currentPassword.get_secret_value(), user.get('passwordHash', '')):
            raise DomainError('FORBIDDEN', 'Current password is incorrect', 403)
        replacement = await hash_password(request.newPassword.get_secret_value())
        return await self.persist(user, {'passwordHash': replacement, 'mustChangePassword': False}, 'Changed password')

    def validate_landing(self, principal: Principal, destination: LandingPage) -> None:
        """Require live resource permission for supported destinations, including future pages."""
        password_gate(principal, '/api/auth/preferences', 'PUT')
        if destination == 'profile':
            return
        if destination in ('users', 'roles'):
            require_permission(principal, 'administer', 'user' if destination == 'users' else 'role')
        else:
            require_permission(principal, 'view', 'audit' if destination == 'audit' else 'application')

    async def save_preferences(self, principal: Principal, request: PreferencesRequest) -> SafeUser:
        """Reload policy before saving only the authenticated subject's preference."""
        user = await self.repository.get_by_id(principal.user_id)
        current = await self.auth.principal_for_user(user)
        self.validate_landing(current, request.defaultLandingPage)
        return await self.persist(user, {'defaultLandingPage': request.defaultLandingPage}, 'Updated landing preference')
