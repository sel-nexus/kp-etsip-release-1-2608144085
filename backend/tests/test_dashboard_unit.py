"""Prove formulas with independently specified totals and rounding fixtures."""
import pytest
from bson import ObjectId
from api.core.policy import Principal, Scope
from api.core.errors import DomainError
from api.domains.dashboard.formulas import ApplicationTotals, rounded_mean, calculate
from api.domains.dashboard.schemas import DashboardFilters
from api.domains.dashboard.service import DashboardService
from api.domains.applications.repository import ApplicationRepository
from api.domains.portfolios.repository import PortfolioRepository

@pytest.mark.parametrize('total,count,expected', [(0,0,None),(0,1,0),(100,1,100),(1,2,1),(5,2,3),(159,2,80),(158,2,79),(1,3,0),(2,3,1),(299,3,100),(0,4,0),(400,4,100),(10**18+1,2,500000000000000001)])
def test_half_up_integer_mean(total, count, expected):
    """Distinguish half-up ties from banker rounding, including exact large sums."""
    assert rounded_mean(total,count) == expected

@pytest.mark.parametrize('total,count', [(-1,1),(1,-1),(-1,0)])
def test_mean_rejects_negative_inputs(total,count):
    """Reject impossible repository summary values."""
    with pytest.raises(ValueError):
        rounded_mean(total,count)

def test_unequal_groups_use_application_weighted_means_and_independent_total():
    """Do not average rounded group scores or infer portfolio counts from groups."""
    a,b='65b100000000000000000001','65b100000000000000000002'
    groups=[ApplicationTotals(a,2,159,181,101,7,1),ApplicationTotals(b,1,0,0,100,2,0)]
    result=calculate(groups,{a:'Zulu',b:'Alpha'},9).model_dump()
    assert result == {'metrics':{'enterpriseQualityScore':53,'averageApplicationHealthScore':60,'automationMaturityScore':67,'openCriticalDefects':9,'applicationsAtRisk':1,'totalApplications':3,'totalPortfolios':9},'portfolioComparisons':[{'portfolioId':b,'name':'Alpha','qualityScore':0,'applicationsAtRisk':0},{'portfolioId':a,'name':'Zulu','qualityScore':80,'applicationsAtRisk':1}]}

def test_empty_averages_and_visible_empty_portfolios():
    """Keep empty portfolios counted despite no represented application groups."""
    result=calculate([],{},4)
    assert result.metrics.model_dump() == {'enterpriseQualityScore':None,'averageApplicationHealthScore':None,'automationMaturityScore':None,'openCriticalDefects':0,'applicationsAtRisk':0,'totalApplications':0,'totalPortfolios':4}
    assert result.portfolioComparisons == []

def test_comparisons_omit_unrepresented_or_unlabelled_groups_and_sort_ties():
    """Never fabricate persisted portfolio names or compare zero-row groups."""
    a,b,c=[str(ObjectId()) for _ in range(3)]
    rows=[ApplicationTotals(b,1,100,0,0,0,0),ApplicationTotals(a,1,0,100,100,0,1),ApplicationTotals(c,0,0,0,0,0,0)]
    result=calculate(rows,{a:'Same',b:'Same',c:'Empty'},3)
    assert [row.portfolioId for row in result.portfolioComparisons]==sorted([a,b])
    assert calculate(rows,{},3).portfolioComparisons==[]

async def test_service_empty_scope_and_denied_permission(db):
    """Exercise the real service and repositories on empty authorized data."""
    service=DashboardService(ApplicationRepository(db),PortfolioRepository(db))
    principal=Principal(ObjectId(),'Engineer',frozenset(['view']),(),False,'Test')
    result=await service.executive(principal,DashboardFilters())
    assert result.metrics.totalApplications==0 and result.metrics.totalPortfolios==0
    denied=Principal(principal.user_id,'Engineer',frozenset(),(),False,'Test')
    with pytest.raises(DomainError) as error:
        await service.executive(denied,DashboardFilters())
    assert error.value.status == 403
