"""Separate submitted credentials from allowlisted session identities."""
from typing import Annotated, Literal
from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator, WrapValidator, ValidatorFunctionWrapHandler

def validate_local_email(value: object, handler: ValidatorFunctionWrapHandler) -> str:
    """Validate the prescribed local account domain without global validator changes."""
    if isinstance(value, str) and value.endswith('@ketsip.local'):
        handler(value.removesuffix('@ketsip.local') + '@example.com')
        return value
    return handler(value)

LocalEmail = Annotated[EmailStr, WrapValidator(validate_local_email)]
from api.core.schemas import WriteModel, ObjectIdString, RoleName

class LoginRequest(WriteModel):
    """Accept only explicit local sign-in credentials."""
    email: LocalEmail
    password: SecretStr = Field(min_length=1)
    @field_validator('email', mode='before')
    @classmethod
    def normalize_email(cls, value: object) -> object:
        """Normalize scalar email strings without accepting Mongo operators."""
        return value.strip().lower() if isinstance(value, str) else value
class SafeUser(BaseModel):
    """Expose only current identity and access, never credential metadata."""
    id: ObjectIdString
    name: str
    email: str
    role: RoleName
    portfolioAccess: list[ObjectIdString]
    status: Literal['Active', 'Inactive']
    defaultLandingPage: str | None = None
    mustChangePassword: bool = False
class LoginResult(BaseModel):
    """Return the backend-issued token and a safe identity."""
    token: str
    user: SafeUser
class LogoutResult(BaseModel):
    """Describe client-side sign-out without claiming token revocation."""
    message: Literal['Signed out'] = 'Signed out'
