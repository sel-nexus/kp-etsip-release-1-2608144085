"""Keep report DTOs and CSV headers identical to the Release 1 contract."""
from typing import Literal
from pydantic import BaseModel, Field
from api.core.schemas import ObjectIdString
from api.domains.applications.schemas import ApplicationFilters, Criticality, Lifecycle, Risk, Score, Defects, Tier
from api.domains.portfolios.schemas import PortfolioFilters, Status

class ApplicationReportFilters(ApplicationFilters):
    """Reuse all inventory filters, adding CSV as the sole export format."""
    format: Literal['csv'] | None = None

class PortfolioReportFilters(PortfolioFilters):
    """Reuse portfolio inventory filtering without application filter drift."""
    format: Literal['csv'] | None = None

class ApplicationReportRow(BaseModel):
    """Expose only the fixed application reporting facts."""
    id: ObjectIdString = Field(validation_alias='_id')
    name: str
    portfolioId: ObjectIdString
    criticality: Criticality
    tier: Tier
    lifecycleStatus: Lifecycle
    applicationHealthScore: Score
    qualityScore: Score
    automationCoverage: Score
    unitTestCoverage: Score
    openDefects: Defects
    openCriticalDefects: Defects
    riskLevel: Risk

class PortfolioReportRow(BaseModel):
    """Expose portfolio reporting facts with transient derived measures."""
    id: ObjectIdString = Field(validation_alias='_id')
    name: str
    ownerName: str
    productArea: str
    status: Status
    applicationCount: int
    qualityScore: int | None

class ApplicationReportPage(BaseModel):
    """Return the specified application page envelope."""
    items: list[ApplicationReportRow]
    page: int
    pageSize: int
    total: int

class PortfolioReportPage(BaseModel):
    """Return the specified portfolio page envelope."""
    items: list[PortfolioReportRow]
    page: int
    pageSize: int
    total: int

APPLICATION_COLUMNS = tuple(ApplicationReportRow.model_fields)
PORTFOLIO_COLUMNS = tuple(PortfolioReportRow.model_fields)
