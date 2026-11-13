"""Expose the exact local session HTTP contracts."""
from typing import Annotated
from fastapi import APIRouter, Depends
from api.core.dependencies import get_auth_service, get_principal
from api.core.policy import Principal
from api.domains.auth.service import AuthService
from api.domains.auth.schemas import LoginRequest, LoginResult, SafeUser, LogoutResult

router = APIRouter(prefix='/api/auth', tags=['Authentication'])
@router.post('/login', response_model=LoginResult, summary='Sign in with local credentials')
async def login(credentials: LoginRequest, service: Annotated[AuthService, Depends(get_auth_service)]) -> LoginResult:
    """Verify explicit credentials without requiring a bearer token."""
    return await service.login(credentials)
@router.get('/me', response_model=SafeUser, summary='Read my current identity')
async def me(principal: Annotated[Principal, Depends(get_principal)], service: Annotated[AuthService, Depends(get_auth_service)]) -> SafeUser:
    """Return the live subject allowlist even during password gating."""
    return await service.current_user(principal)
@router.post('/logout', response_model=LogoutResult, summary='Sign out of the client session')
async def logout(principal: Annotated[Principal, Depends(get_principal)], service: Annotated[AuthService, Depends(get_auth_service)]) -> LogoutResult:
    """Confirm sign-out; the client discards the non-revoked bearer."""
    return await service.logout(principal)
