"""Define closed ensure requests and bounded permission edits."""
from datetime import datetime
from pydantic import BaseModel, Field, AwareDatetime, field_validator
from api.core.schemas import WriteModel, RoleName, Permission, ObjectIdString

class RoleEnsure(WriteModel):
    """Ensure only a supported baseline; never accept editable fields here."""
    name: RoleName

class RoleUpdate(WriteModel):
    """Replace a unique permission subset with optional optimistic concurrency."""
    permissions: list[Permission] = Field(max_length=6)
    expectedUpdatedAt: AwareDatetime | None = Field(default=None, strict=False)

    @field_validator('permissions')
    @classmethod
    def unique_permissions(cls, value: list[str]) -> list[str]:
        """Reject duplicates rather than silently normalizing invalid input."""
        if len(set(value)) != len(value):
            raise ValueError('Duplicate permissions')
        return value

    @field_validator('expectedUpdatedAt', mode='before')
    @classmethod
    def timestamp_input(cls, value: object) -> object:
        """Accept aware dates or ISO strings, not numeric epoch coercion or null."""
        if not isinstance(value, (str, datetime)):
            raise ValueError('Supply an aware timestamp')
        return value

class Role(BaseModel):
    """Expose only supported role metadata and its persisted version."""
    id: ObjectIdString = Field(validation_alias='_id')
    name: RoleName
    description: str
    permissions: list[Permission]
    createdAt: datetime
    updatedAt: datetime

class RoleList(BaseModel):
    """Return the fixed vocabulary without invented paging parameters."""
    items: list[Role]
