"""Verify real report service branches and fixed CSV encoding independently."""
import csv
from io import StringIO
from dataclasses import replace
import pytest
from api.core.audit import AuditService
from api.core.csv import csv_line, safe_cell
from api.core.errors import DomainError
from api.core.policy import Principal, ROLE_MAXIMUM
from api.domains.applications.repository import ApplicationRepository
from api.domains.portfolios.repository import PortfolioRepository
from api.domains.reports.service import ReportService
from api.domains.reports.schemas import ApplicationReportFilters, PortfolioReportFilters
from test_reports_api import inventory

@pytest.mark.parametrize('value,expected',[(None,''),('=1',"'=1"),('+1',"'+1"),('-1',"'-1"),('@a',"'@a"),('é, "hello"\nline','é, "hello"\nline'),(0,'0')])
def test_csv_cells(value,expected):
    assert safe_cell(value) == expected
    assert next(csv.reader(StringIO(csv_line(('a','b'),{'a':value,'secret':'excluded'}).decode()))) == [expected,'']

async def test_service_pages_export_permissions_and_cleanup(db,identity,monkeypatch):
    ids = await inventory(db)
    user,_ = identity
    principal = Principal(user['_id'],'Engineer',ROLE_MAXIMUM['Engineer'],tuple(ids[:2]),False,'Test')
    service = ReportService(ApplicationRepository(db),PortfolioRepository(db),AuditService(db))
    assert (await service.applications_page(principal,ApplicationReportFilters())).total == 2
    portfolios = await service.portfolios_page(principal,PortfolioReportFilters())
    assert [p.qualityScore for p in portfolios.items] == [None,80]
    for resource,filters in [('application',ApplicationReportFilters()),('portfolio',PortfolioReportFilters())]:
        spool = await service.export(principal,filters,resource)
        assert len(list(csv.reader(StringIO(spool.read().decode())))) == 3
        spool.close()
        denied = replace(principal,permissions=frozenset(['view']))
        with pytest.raises(DomainError) as error:
            await service.export(denied,filters,resource)
        assert error.value.status == 403
    with pytest.raises(ValueError):
        await service.export(principal,ApplicationReportFilters(),'unsupported')
    import api.domains.reports.service as module
    from tempfile import SpooledTemporaryFile
    spools=[]
    def failing_spool(*args,**kwargs):
        spool = SpooledTemporaryFile(*args,**kwargs)
        spools.append(spool)
        def fail(*args):
            raise OSError('injected disk failure')
        spool.write = fail
        return spool
    monkeypatch.setattr(module,'SpooledTemporaryFile',failing_spool)
    with pytest.raises(DomainError) as error:
        await service.export(principal,ApplicationReportFilters(),'application')
    assert error.value.status == 503 and spools[0].closed

async def test_generation_validation_and_audit_failure_close_spools(db,identity,monkeypatch):
    """A failed row or required audit cannot release bytes or leak a handle."""
    ids = await inventory(db)
    user,_ = identity
    principal = Principal(user['_id'],'Engineer',ROLE_MAXIMUM['Engineer'],tuple(ids[:2]),False,'Test')
    service = ReportService(ApplicationRepository(db),PortfolioRepository(db),AuditService(db))
    import api.domains.reports.service as module
    from tempfile import SpooledTemporaryFile
    from pydantic import ValidationError

    spools=[]
    def capture(*args,**kwargs):
        spool = SpooledTemporaryFile(*args,**kwargs)
        spools.append(spool)
        return spool
    monkeypatch.setattr(module,'SpooledTemporaryFile',capture)
    audits_before = await db.audit_logs.find().sort('_id',1).to_list(None)
    await db.applications.update_one({'portfolioId':ids[0]},{'$unset':{'riskLevel':''}})
    with pytest.raises(ValidationError):
        await service.export(principal,ApplicationReportFilters(),'application')
    assert spools[-1].closed
    assert await db.audit_logs.find().sort('_id',1).to_list(None) == audits_before
    assert await db.applications.count_documents({'portfolioId':ids[0],'riskLevel':{'$exists':False}}) == 1
    await db.applications.update_many({'portfolioId':ids[0]},{'$set':{'riskLevel':'Medium'}})
    applications_before = await db.applications.find().sort('_id',1).to_list(None)
    portfolios_before = await db.portfolios.find().sort('_id',1).to_list(None)
    await db.command({'collMod':'audit_logs','validator':{'impossible':{'$exists':True}},'validationLevel':'strict','validationAction':'error'})
    try:
        with pytest.raises(DomainError) as error:
            await service.export(principal,ApplicationReportFilters(),'application')
        assert error.value.status == 503 and error.value.code == 'AUDIT_WRITE_FAILED'
        assert spools[-1].closed
        assert await db.audit_logs.find().sort('_id',1).to_list(None) == audits_before
        assert await db.applications.find().sort('_id',1).to_list(None) == applications_before
        assert await db.portfolios.find().sort('_id',1).to_list(None) == portfolios_before
    finally:
        await db.command({'collMod':'audit_logs','validator':{}})
    for operation,filters in [(service.applications_page,ApplicationReportFilters()),(service.portfolios_page,PortfolioReportFilters())]:
        with pytest.raises(DomainError):
            await operation(replace(principal,permissions=frozenset()),filters)
