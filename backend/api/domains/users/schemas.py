"""Define strict administration writes and complete credential-free account DTOs."""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, AwareDatetime, field_validator, model_validator
from api.core.schemas import WriteModel, ObjectIdString, RoleName
from api.domains.auth.schemas import LocalEmail, LoginRequest
from api.domains.portfolios.schemas import PortfolioFilters, PortfolioUpdate

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
InputId = Annotated[str, Field(pattern=r'^[0-9a-fA-F]{24}$')]
Status = Literal['Active', 'Inactive']

class UserCreate(WriteModel):
    """Accept an initial credential only at account creation."""
    name: Text
    email: LocalEmail
    password: SecretStr = Field(min_length=1)
    role: RoleName
    portfolioAccess: list[InputId] = Field(max_length=1000)
    status: Status
    managerName: Text | None = None
    vendorIndicator: bool = False
    normalize_email = field_validator('email', mode='before')(LoginRequest.normalize_email.__func__)

    @field_validator('password')
    @classmethod
    def bcrypt_length(cls, value: SecretStr) -> SecretStr:
        """Reject truncation aliases without inventing a password complexity policy."""
        if len(value.get_secret_value().encode('utf-8')) > 72:
            raise ValueError('Password exceeds bcrypt byte limit')
        return value

    @field_validator('portfolioAccess')
    @classmethod
    def unique_assignments(cls, value: list[str]) -> list[str]:
        """Reject duplicate references before any parent reservation writes."""
        if value is None:
            raise ValueError('Null assignments are not allowed')
        if len({item.lower() for item in value}) != len(value):
            raise ValueError('Duplicate portfolio assignments')
        return value

class UserUpdate(WriteModel):
    """Apply supplied account fields, never reset credentials."""
    name: Text | None = None
    email: LocalEmail | None = None
    role: RoleName | None = None
    portfolioAccess: list[InputId] | None = Field(default=None, max_length=1000)
    status: Status | None = None
    managerName: Text | None = None
    vendorIndicator: bool | None = None
    expectedUpdatedAt: AwareDatetime | None = Field(default=None, strict=False)
    normalize_email = field_validator('email', mode='before')(LoginRequest.normalize_email.__func__)
    timestamp_input = field_validator('expectedUpdatedAt', mode='before')(PortfolioUpdate.timestamp_input.__func__)
    unique_assignments = field_validator('portfolioAccess')(UserCreate.unique_assignments.__func__)

    @model_validator(mode='after')
    def valid_changes(self) -> 'UserUpdate':
        """Allow nullable manager only and reject empty or explicit-null edits."""
        if not self.model_fields_set - {'expectedUpdatedAt'}:
            raise ValueError('Supply at least one edit')
        if any(getattr(self, key) is None for key in self.model_fields_set - {'managerName'}):
            raise ValueError('Null values are not allowed')
        return self

class UserFilters(BaseModel):
    """Bound account search and closed role/status filters."""
    model_config = ConfigDict(extra='forbid')
    page: int = Field(default=1, ge=1, le=100000)
    pageSize: int = Field(default=25, ge=1, le=100)
    search: Text | None = None
    integer_query = field_validator('page', 'pageSize', mode='before')(PortfolioFilters.integer_query.__func__)
    role: RoleName | None = None
    status: Status | None = None

class User(BaseModel):
    """Allowlist account metadata; ignore stored credentials and internal pins."""
    id: ObjectIdString = Field(validation_alias='_id')
    name: str
    email: str
    role: RoleName
    portfolioAccess: list[ObjectIdString]
    status: Status
    lastLogin: datetime | None = None
    authSource: Literal['local'] = 'local'
    managerName: str | None = None
    vendorIndicator: bool = False
    mustChangePassword: bool = False
    createdAt: datetime
    updatedAt: datetime

class UserPage(BaseModel):
    """Return complete safe accounts and stable paging metadata."""
    items: list[User]
    page: int
    pageSize: int
    total: int

class DeactivatedUser(BaseModel):
    """Confirm soft deactivation without removing durable account history."""
    deactivated: Literal[True] = True
    id: ObjectIdString
