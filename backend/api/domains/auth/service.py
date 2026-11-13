"""Compose local credentials, current policy, safe DTOs, and durable audits."""
from datetime import datetime, timezone
from typing import Any
from bson import ObjectId
from api.core.config import Settings
from api.core.security import verify_password, create_access_token, verify_access_token
from api.core.errors import Unauthenticated, DomainError
from api.core.policy import Principal, ROLE_MAXIMUM
from api.core.audit import AuditService
from api.domains.auth.repository import AuthRepository
from api.domains.auth.schemas import LoginRequest, LoginResult, SafeUser, LogoutResult

class AuthService:
    """Resolve authorization exclusively from persisted current records."""
    def __init__(self, repository: AuthRepository, audit: AuditService, settings: Settings) -> None:
        """Inject persistence and signing configuration."""
        self.repository, self.audit, self.settings = repository, audit, settings
    async def principal_for_user(self, user: dict[str, Any] | None) -> Principal:
        """Fail closed for inactive, missing, or malformed stored identity."""
        if not user or user.get('status') != 'Active' or user.get('role') not in ROLE_MAXIMUM:
            raise Unauthenticated()
        role = await self.repository.get_role(user['role'])
        if not role:
            raise Unauthenticated()
        try:
            permissions = role['permissions']
            access = user['portfolioAccess']
            if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
                raise Unauthenticated()
            if not isinstance(access, list) or not all(isinstance(p, ObjectId) for p in access):
                raise Unauthenticated()
            return Principal(user['_id'], user['role'], frozenset(permissions) & ROLE_MAXIMUM[user['role']], tuple(access), bool(user.get('mustChangePassword', False)), user['name'])
        except (KeyError, TypeError) as exc:
            raise Unauthenticated() from exc
    async def login(self, credentials: LoginRequest) -> LoginResult:
        """Audit both outcomes; do not issue a token when audit fails."""
        user = await self.repository.get_by_email(str(credentials.email))
        valid = bool(user and await verify_password(credentials.password.get_secret_value(), user.get('passwordHash', '')))
        try:
            if not valid:
                raise Unauthenticated()
            await self.principal_for_user(user)
        except Unauthenticated:
            # Unknown attempts have an opaque event actor, never an invented persisted account.
            actor_id = user.get('_id') if user else None
            actor_name = user.get('name') or 'Incomplete account' if user else 'Unknown account'
            try:
                await self.audit.record(actor_id, actor_name, 'login', 'user', actor_id, 'Sign-in failed')
            except DomainError as exc:
                if exc.code != 'AUDIT_WRITE_FAILED':
                    raise
            raise Unauthenticated()
        updated = await self.repository.mark_login(user['_id'], datetime.now(timezone.utc))
        if not updated:
            await self.audit.record(user['_id'], user['name'], 'login', 'user', user['_id'], 'Sign-in failed')
            raise Unauthenticated()
        await self.audit.record(updated['_id'], updated['name'], 'login', 'user', updated['_id'], 'Sign-in succeeded')
        return LoginResult(token=create_access_token(updated['_id'], self.settings), user=self.safe_user(updated))
    async def resolve(self, token: str) -> Principal:
        """Verify JWT then reread user and role for every protected call."""
        user_id = verify_access_token(token, self.settings)
        return await self.principal_for_user(await self.repository.get_by_id(user_id))
    def safe_user(self, user: dict[str, Any]) -> SafeUser:
        """Map an explicit response allowlist, excluding unknown stored fields."""
        return SafeUser(id=user['_id'], name=user['name'], email=user['email'], role=user['role'], portfolioAccess=user['portfolioAccess'], status=user['status'], defaultLandingPage=user.get('defaultLandingPage'), mustChangePassword=user.get('mustChangePassword', False))
    async def current_user(self, principal: Principal) -> SafeUser:
        """Return only the authenticated subject, rejecting deactivation races."""
        user = await self.repository.get_by_id(principal.user_id)
        await self.principal_for_user(user)
        return self.safe_user(user)
    async def logout(self, principal: Principal) -> LogoutResult:
        """Confirm a current identity without persisting fictitious revocation."""
        await self.current_user(principal)
        return LogoutResult()
