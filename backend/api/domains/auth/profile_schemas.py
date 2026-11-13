"""Validate only approved profile mutations without exposing secrets."""
from typing import Literal
from pydantic import Field, SecretStr, field_validator
from api.core.schemas import WriteModel

LandingPage = Literal['dashboard', 'portfolios', 'applications', 'reports', 'users', 'roles', 'audit', 'profile']

class PasswordChangeRequest(WriteModel):
    """Accept nonempty credentials within bcrypt's full UTF-8 byte limit."""
    currentPassword: SecretStr = Field(min_length=1)
    newPassword: SecretStr = Field(min_length=1)

    @field_validator('currentPassword', 'newPassword')
    @classmethod
    def supported_password(cls, value: SecretStr) -> SecretStr:
        """Reject truncation aliases before credential verification or persistence."""
        secret = value.get_secret_value()
        if len(secret.encode('utf-8')) > 72 or '\x00' in secret:
            raise ValueError('Password is not supported by bcrypt')
        return value

class PreferencesRequest(WriteModel):
    """Restrict landing preferences to the closed Release 1 route vocabulary."""
    defaultLandingPage: LandingPage
