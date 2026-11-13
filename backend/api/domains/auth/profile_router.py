"""Expose the approved password and landing preference HTTP contracts."""
from typing import Annotated
from fastapi import APIRouter, Depends
from api.core.dependencies import get_auth_service, get_principal
from api.core.policy import Principal
from api.domains.auth.service import AuthService
from api.domains.auth.schemas import SafeUser
from api.domains.auth.profile_service import ProfileService
from api.domains.auth.profile_schemas import PasswordChangeRequest, PreferencesRequest

router = APIRouter(prefix='/api/auth', tags=['Profile'])

@router.post('/change-password', response_model=SafeUser, summary='Change my password')
async def change_password(request: PasswordChangeRequest, principal: Annotated[Principal, Depends(get_principal)], auth: Annotated[AuthService, Depends(get_auth_service)]) -> SafeUser:
    """Allow credential replacement through the first-password gate."""
    return await ProfileService(auth).change_password(principal, request)

@router.put('/preferences', response_model=SafeUser, summary='Save my landing preference')
async def preferences(request: PreferencesRequest, principal: Annotated[Principal, Depends(get_principal)], auth: Annotated[AuthService, Depends(get_auth_service)]) -> SafeUser:
    """Reject gated or inaccessible landing destinations before persistence."""
    return await ProfileService(auth).save_preferences(principal, request)
