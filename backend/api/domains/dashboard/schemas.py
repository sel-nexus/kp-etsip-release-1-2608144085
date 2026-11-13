"""Define the closed executive filter and deterministic measure contracts."""
from pydantic import BaseModel, ConfigDict
from api.core.schemas import ObjectIdString
from api.domains.applications.schemas import BodyId, Risk, Score, Defects
from api.domains.portfolios.schemas import Text

class DashboardFilters(BaseModel):
    """Allow only the three application-narrowing filters."""
    model_config = ConfigDict(extra='forbid', strict=True)
    portfolioId: BodyId | None = None
    productArea: Text | None = None
    riskLevel: Risk | None = None

class DashboardMetrics(BaseModel):
    """Keep empty averages unavailable and counts nonnegative."""
    enterpriseQualityScore: Score | None
    averageApplicationHealthScore: Score | None
    automationMaturityScore: Score | None
    openCriticalDefects: Defects
    applicationsAtRisk: Defects
    totalApplications: Defects
    totalPortfolios: Defects

class PortfolioComparison(BaseModel):
    """Expose represented visible groups with persisted portfolio labels."""
    portfolioId: ObjectIdString
    name: str
    qualityScore: Score
    applicationsAtRisk: Defects

class Dashboard(BaseModel):
    """Return exactly the specified metrics and comparison groups."""
    metrics: DashboardMetrics
    portfolioComparisons: list[PortfolioComparison]
