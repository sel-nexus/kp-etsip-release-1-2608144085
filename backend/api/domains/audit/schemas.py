"""Define closed audit filters and allowlisted historical evidence."""
from datetime import datetime, timezone
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from api.core.schemas import ObjectIdString

AuditAction = Literal['login', 'create', 'edit', 'delete', 'roleChange', 'permissionChange', 'export']

class AuditFilters(BaseModel):
    """Accept bounded paging and exact narrowing criteria."""
    model_config = ConfigDict(extra='forbid')
    userId: ObjectIdString | None = None
    action: AuditAction | None = None
    from_date: AwareDatetime | None = Field(default=None, alias='from')
    to_date: AwareDatetime | None = Field(default=None, alias='to')
    page: int = Field(default=1, ge=1, le=100000)
    pageSize: int = Field(default=25, ge=1, le=100)
    format: Literal['csv'] | None = None

    @field_validator('page', 'pageSize', mode='before')
    @classmethod
    def integer_query(cls, value: object) -> object:
        """Reject signed, fractional and boolean page values."""
        if type(value) is int or isinstance(value, str) and value.isascii() and value.isdigit():
            return value
        raise ValueError('Use a positive integer')

    @field_validator('from_date', 'to_date', mode='before')
    @classmethod
    def iso_date(cls, value: object) -> object:
        """Accept aware ISO dates rather than epochs or date-only input."""
        if not isinstance(value, (str, datetime)) or isinstance(value, str) and ('T' not in value or len(value) > 64):
            raise ValueError('Use an aware ISO timestamp')
        return value

    @field_validator('from_date', 'to_date')
    @classmethod
    def utc_date(cls, value: datetime) -> datetime:
        """Normalize accepted offsets before querying BSON UTC dates."""
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def ordered_dates(self) -> 'AuditFilters':
        """Reject reversed ranges, allowing equal inclusive bounds."""
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError('Date range is reversed')
        return self

class AuditRow(BaseModel):
    """Expose only historical fields, retaining the approved unknown actor."""
    id: ObjectIdString = Field(validation_alias='_id')
    timestamp: AwareDatetime
    userId: ObjectIdString | None
    userName: str
    action: AuditAction
    entityType: str
    entityId: ObjectIdString | None
    details: str

class AuditPage(BaseModel):
    """Return the standard bounded table envelope."""
    items: list[AuditRow]
    page: int
    pageSize: int
    total: int
