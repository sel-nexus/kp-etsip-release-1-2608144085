"""Calculate inventory measures using exact integer half-up arithmetic."""
from dataclasses import dataclass
from collections.abc import Sequence, Mapping
from api.domains.dashboard.schemas import Dashboard, DashboardMetrics, PortfolioComparison

@dataclass(frozen=True)
class ApplicationTotals:
    """Carry scoped repository sums without retaining application documents."""
    portfolio_id: str
    count: int
    quality: int
    health: int
    automation: int
    critical_defects: int
    at_risk: int

def rounded_mean(total: int, count: int) -> int | None:
    """Round nonnegative sums half up without floating-point or banker drift.

    Returns:
        No score when there are no observations.
    Raises:
        ValueError: When a caller supplies a negative sum or count.
    """
    if total < 0 or count < 0:
        raise ValueError('Means require nonnegative totals and counts')
    if count == 0:
        return None
    return (2 * total + count) // (2 * count)

def calculate(groups: Sequence[ApplicationTotals], names: Mapping[str, str], total_portfolios: int) -> Dashboard:
    """Combine exact sums, never averaging rounded portfolio scores.

    Args:
        groups: Totals from the filtered, authorized application query.
        names: Labels loaded from scoped portfolio documents.
        total_portfolios: Independently counted visible portfolio documents.
    """
    count = sum(group.count for group in groups)
    metrics = DashboardMetrics(
        enterpriseQualityScore=rounded_mean(sum(group.quality for group in groups), count),
        averageApplicationHealthScore=rounded_mean(sum(group.health for group in groups), count),
        automationMaturityScore=rounded_mean(sum(group.automation for group in groups), count),
        openCriticalDefects=sum(group.critical_defects for group in groups),
        applicationsAtRisk=sum(group.at_risk for group in groups),
        totalApplications=count, totalPortfolios=total_portfolios,
    )
    comparisons = [PortfolioComparison(
        portfolioId=group.portfolio_id, name=names[group.portfolio_id],
        qualityScore=rounded_mean(group.quality, group.count), applicationsAtRisk=group.at_risk,
    ) for group in groups if group.count and group.portfolio_id in names]
    comparisons.sort(key=lambda row: (row.name, row.portfolioId))
    return Dashboard(metrics=metrics, portfolioComparisons=comparisons)
