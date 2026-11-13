"""Compose executive measures from shared authorized inventory repositories."""
from api.core.policy import Principal, portfolio_scope, require_permission
from api.domains.applications.repository import ApplicationRepository
from api.domains.applications.schemas import ApplicationFilters
from api.domains.portfolios.repository import PortfolioRepository
from api.domains.dashboard.schemas import Dashboard, DashboardFilters
from api.domains.dashboard.formulas import ApplicationTotals, calculate

class DashboardService:
    """Reuse inventory scope and keep Mongo operations out of business logic."""
    def __init__(self, applications: ApplicationRepository, portfolios: PortfolioRepository) -> None:
        """Bind repositories backed by the existing pooled database."""
        self.applications = applications
        self.portfolios = portfolios

    async def executive(self, principal: Principal, filters: DashboardFilters) -> Dashboard:
        """Authorize before reads and count portfolios independently of all filters."""
        require_permission(principal, 'view', 'dashboard')
        scope = portfolio_scope(principal)
        rows = await self.applications.dashboard_totals(scope, ApplicationFilters(**filters.model_dump()))
        total = await self.portfolios.count_visible(scope)
        names = await self.portfolios.names(scope, [row['_id'] for row in rows])
        groups = [ApplicationTotals(str(row['_id']), row['count'], row['quality'], row['health'],
                                    row['automation'], row['critical_defects'], row['at_risk']) for row in rows]
        return calculate(groups, names, total)
