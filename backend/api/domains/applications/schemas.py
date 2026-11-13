"""Validate complete application records and narrowly bounded query inputs."""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, HttpUrl, AwareDatetime, field_validator, model_validator
from api.core.schemas import ObjectIdString, WriteModel
from api.domains.portfolios.schemas import Text, Description, PortfolioFilters

Score = Annotated[int, Field(strict=True, ge=0, le=100)]
Defects = Annotated[int, Field(strict=True, ge=0)]
Tier = Annotated[int, Field(strict=True, ge=1, le=4)]
Criticality = Literal['Low', 'Medium', 'High', 'Critical']
Lifecycle = Literal['Active', 'Deprecated', 'Retired']
Risk = Literal['Low', 'Medium', 'High']
BodyId = Annotated[str, StringConstraints(pattern=r'^[0-9a-fA-F]{24}$', strict=True)]

class ApplicationCreate(WriteModel):
    """Require every logical field, permitting null only for resource URLs."""
    name: Text
    description: Description
    portfolioId: BodyId
    productArea: Text
    businessOwner: Text
    technologyOwner: Text
    etsOwner: Text
    criticality: Criticality
    tier: Tier
    lifecycleStatus: Lifecycle
    technologyStack: Description
    repositoryUrl: HttpUrl | None
    pipelineUrl: HttpUrl | None
    applicationHealthScore: Score
    qualityScore: Score
    automationCoverage: Score
    unitTestCoverage: Score
    openDefects: Defects
    openCriticalDefects: Defects
    riskLevel: Risk

class ApplicationUpdate(WriteModel):
    """Distinguish omitted fields from invalid nulls and reject empty edits."""
    name: Text | None = None
    description: Description | None = None
    portfolioId: BodyId | None = None
    productArea: Text | None = None
    businessOwner: Text | None = None
    technologyOwner: Text | None = None
    etsOwner: Text | None = None
    criticality: Criticality | None = None
    tier: Tier | None = None
    lifecycleStatus: Lifecycle | None = None
    technologyStack: Description | None = None
    repositoryUrl: HttpUrl | None = None
    pipelineUrl: HttpUrl | None = None
    applicationHealthScore: Score | None = None
    qualityScore: Score | None = None
    automationCoverage: Score | None = None
    unitTestCoverage: Score | None = None
    openDefects: Defects | None = None
    openCriticalDefects: Defects | None = None
    riskLevel: Risk | None = None
    expectedUpdatedAt: AwareDatetime | None = Field(default=None, strict=False)

    @field_validator('expectedUpdatedAt', mode='before')
    @classmethod
    def timestamp(cls, value: object) -> object:
        """Accept aware ISO dates but reject numeric epoch coercion."""
        if not isinstance(value, (str, datetime)) or isinstance(value, str) and ('T' not in value or len(value) > 64):
            raise ValueError('Use an aware ISO timestamp')
        return value

    @model_validator(mode='after')
    def changes(self) -> 'ApplicationUpdate':
        """Allow explicit URL clearing without allowing null business facts."""
        if not self.model_fields_set - {'expectedUpdatedAt'}:
            raise ValueError('Supply at least one edit')
        if any(getattr(self, key) is None for key in self.model_fields_set - {'repositoryUrl', 'pipelineUrl'}):
            raise ValueError('Null values are not allowed')
        return self

class ApplicationFilters(BaseModel):
    """AND supported search and exact filters with server-owned scope."""
    model_config = ConfigDict(extra='forbid')
    page: int = Field(default=1, ge=1, le=100000)
    pageSize: int = Field(default=25, ge=1, le=100)
    name: Text | None = None
    search: Text | None = None
    portfolioId: BodyId | None = None
    productArea: Text | None = None
    criticality: Criticality | None = None
    lifecycleStatus: Lifecycle | None = None
    riskLevel: Risk | None = None
    tier: int | None = Field(default=None, ge=1, le=4)
    integer_query = field_validator('page', 'pageSize', 'tier', mode='before')(PortfolioFilters.integer_query.__func__)

class Application(ApplicationCreate):
    """Expose allowlisted BSON-backed application facts and timestamps."""
    model_config = ConfigDict(extra='ignore', strict=False)
    id: ObjectIdString = Field(validation_alias='_id')
    portfolioId: ObjectIdString
    createdAt: datetime
    updatedAt: datetime

class PortfolioSummary(BaseModel):
    """Expose only non-sensitive parent inventory context."""
    id: ObjectIdString = Field(validation_alias='_id')
    name: str
    productArea: str
    status: Literal['Active', 'Archived']

class ApplicationDetail(Application):
    """Pair all application fields with its visible portfolio summary."""
    portfolio: PortfolioSummary

class ApplicationPage(BaseModel):
    """Return a bounded application page and its matching total."""
    items: list[Application]
    page: int
    pageSize: int
    total: int

class DeletedApplication(BaseModel):
    """Confirm explicit application deletion without cascading its parent."""
    deleted: Literal[True] = True
    id: ObjectIdString
