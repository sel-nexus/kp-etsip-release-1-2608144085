"""Define strict portfolio mutations and bounded public inventory contracts."""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, AwareDatetime, model_validator, field_validator
from api.core.schemas import ObjectIdString, WriteModel

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Status = Literal['Active', 'Archived']

class PortfolioCreate(WriteModel):
    """Require the complete stored business record without derived values."""
    name: Text
    ownerName: Text
    description: Description
    productArea: Text
    status: Status

class PortfolioUpdate(WriteModel):
    """Allow partial edits while rejecting nulls and empty mutations."""
    name: Text | None = None
    ownerName: Text | None = None
    description: Description | None = None
    productArea: Text | None = None
    status: Status | None = None
    expectedUpdatedAt: AwareDatetime | None = Field(default=None, strict=False)

    @field_validator('expectedUpdatedAt', mode='before')
    @classmethod
    def timestamp_input(cls, value: object) -> object:
        """Accept explicit aware timestamps, never numeric epoch coercion."""
        if not isinstance(value, (str, datetime)) or isinstance(value, str) and ('T' not in value or len(value) > 64):
            raise ValueError('Use an aware ISO timestamp')
        return value

    @model_validator(mode='after')
    def valid_changes(self) -> 'PortfolioUpdate':
        """Keep omitted fields distinct from explicit null values."""
        if not self.model_fields_set - {'expectedUpdatedAt'}:
            raise ValueError('Supply at least one edit')
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError('Null values are not allowed')
        return self

class PortfolioFilters(BaseModel):
    """Bound pagination and allow only the defined narrowing filters."""
    model_config = ConfigDict(extra='forbid')
    page: int = Field(default=1, ge=1, le=100000)
    pageSize: int = Field(default=25, ge=1, le=100)
    search: Text | None = None
    status: Status | None = None
    productArea: Text | None = None

    @field_validator('page', 'pageSize', mode='before')
    @classmethod
    def integer_query(cls, value: object) -> object:
        """Reject fractional, signed or boolean paging instead of coercing it."""
        if type(value) is int or isinstance(value, str) and value.isascii() and value.isdigit():
            return value
        raise ValueError('Use a positive integer')

class Portfolio(BaseModel):
    """Expose safe stored fields and current derived measures."""
    id: ObjectIdString = Field(validation_alias='_id')
    name: str
    ownerName: str
    description: str
    productArea: str
    status: Status
    createdAt: datetime
    updatedAt: datetime
    applicationCount: int
    qualityScore: int | None

class RelatedApplication(BaseModel):
    """Expose only the related-application summary specified for portfolio detail."""
    id: ObjectIdString = Field(validation_alias='_id')
    name: str
    criticality: Literal['Low', 'Medium', 'High', 'Critical']
    tier: int
    lifecycleStatus: Literal['Active', 'Deprecated', 'Retired']
    riskLevel: Literal['Low', 'Medium', 'High']

class PortfolioPage(BaseModel):
    """Return stable inventory paging metadata."""
    items: list[Portfolio]
    page: int
    pageSize: int
    total: int

class ApplicationPage(BaseModel):
    """Bound related summaries independently from portfolio metrics."""
    items: list[RelatedApplication]
    page: int
    pageSize: int
    total: int

class PortfolioDetail(BaseModel):
    """Pair the portfolio with its first bounded related application page."""
    portfolio: Portfolio
    applications: list[RelatedApplication]

class DeletedPortfolio(BaseModel):
    """Confirm explicit non-cascading deletion."""
    deleted: Literal[True] = True
    id: ObjectIdString
