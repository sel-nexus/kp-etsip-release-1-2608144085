"""Exercise application validation and durable service transitions against real Mongo."""
from datetime import datetime, timezone
import asyncio
import pytest
from bson import ObjectId
from pydantic import ValidationError
from api.core.audit import AuditService
from api.core.errors import DomainError
from api.core.policy import Principal, ROLE_MAXIMUM, Scope
from api.domains.applications.schemas import ApplicationCreate, ApplicationUpdate, ApplicationFilters
from api.domains.applications.repository import ApplicationRepository
from api.domains.applications.service import ApplicationService
from api.domains.portfolios.repository import PortfolioRepository
from api.domains.portfolios.service import PortfolioService


def payload(parent, name='Test application'):
    """Supply independent complete business facts for validation and persistence tests."""
    return dict(name=name, description='Core service', portfolioId=str(parent), productArea='Payments', businessOwner='Business', technologyOwner='Technology', etsOwner='ETS', criticality='High', tier=2, lifecycleStatus='Active', technologyStack='Python', repositoryUrl='https://example.com/repo', pipelineUrl=None, applicationHealthScore=82, qualityScore=79, automationCoverage=65, unitTestCoverage=72, openDefects=4, openCriticalDefects=1, riskLevel='Medium')


async def parent(db, name='Payments'):
    """Persist a real portfolio with no synthetic reference enforcement."""
    now = datetime.now(timezone.utc)
    identifier = ObjectId()
    await db.portfolios.insert_one(dict(_id=identifier, name=name, description='Portfolio', ownerName='Owner', productArea='Payments', status='Active', createdAt=now, updatedAt=now))
    return identifier


def actor(role='Administrator', parents=()):
    """Construct a current policy principal for service branch tests."""
    return Principal(ObjectId(), role, ROLE_MAXIMUM[role], tuple(parents), False, 'Test actor')


@pytest.mark.parametrize('key', list(payload(ObjectId())))
def test_each_create_field_is_required(key):
    """Reject each individually missing logical application field."""
    data = payload(ObjectId()); del data[key]
    with pytest.raises(ValidationError): ApplicationCreate.model_validate(data)


@pytest.mark.parametrize('key,value', [
    *[(key, value) for key in ['name','description','productArea','businessOwner','technologyOwner','etsOwner','technologyStack'] for value in ['', ' ', None, 1]],
    *[(key, value) for key in ['applicationHealthScore','qualityScore','automationCoverage','unitTestCoverage'] for value in [-1,101,True,1.2,'2',None]],
    *[(key, value) for key in ['openDefects','openCriticalDefects'] for value in [-1,True,1.2,'2',None]],
    *[('tier', value) for value in [0,5,True,1.1,'2']], ('criticality','Extreme'), ('lifecycleStatus','Archived'), ('riskLevel','Critical'),
    ('portfolioId','bad'), ('portfolioId',{'$ne':None}), ('repositoryUrl','javascript:alert(1)'), ('pipelineUrl','bad'), ('unknown','x'),
])
def test_invalid_create_and_update_fields_reject(key, value):
    """Reject invalid write types, bounds, enums, URLs, strings and unknown keys."""
    with pytest.raises(ValidationError): ApplicationCreate.model_validate({**payload(ObjectId()), key:value})
    with pytest.raises(ValidationError): ApplicationUpdate.model_validate({key:value})


@pytest.mark.parametrize('data', [{}, {'expectedUpdatedAt':'2026-01-01T00:00:00Z'}, {'qualityScore':None}, {'qualityScore':2,'expectedUpdatedAt':123}, {'qualityScore':2,'expectedUpdatedAt':'2026-01-01T00:00:00'}])
def test_partial_edit_negative_states(data):
    """Reject empty edits, null business facts and unsafe edit timestamps."""
    with pytest.raises(ValidationError): ApplicationUpdate.model_validate(data)


async def test_service_persists_complete_record_reassigns_and_deletes(db):
    """Requery BSON links, audit events and completed reservations after each write."""
    first, second = await parent(db), await parent(db, 'Other')
    service = ApplicationService(ApplicationRepository(db), AuditService(db)); principal = actor()
    created = await service.create(principal, ApplicationCreate.model_validate(payload(first)))
    stored = await db.applications.find_one({'_id':ObjectId(created.id)})
    assert stored['portfolioId'] == first and stored['pipelineUrl'] is None
    detail = await service.detail(principal, ObjectId(created.id))
    assert detail.portfolio.name == 'Payments' and detail.technologyStack == 'Python'
    updated = await service.update(principal, ObjectId(created.id), ApplicationUpdate(portfolioId=str(second), qualityScore=100, repositoryUrl=None))
    assert updated.qualityScore == 100
    assert (await db.applications.find_one({'_id':ObjectId(created.id)}))['portfolioId'] == second
    assert not (await db.portfolios.find_one({'_id':first}))['_applicationReservations']
    assert await db.audit_logs.count_documents({'entityId':ObjectId(created.id)}) == 2
    assert (await service.delete(principal,ObjectId(created.id))).deleted
    assert await db.applications.find_one({'_id':ObjectId(created.id)}) is None


@pytest.mark.parametrize('reassign', [False, True])
async def test_concurrent_reference_write_and_portfolio_delete_never_orphan(db, reassign):
    """Race independent real service workflows and assert every surviving link resolves."""
    service = ApplicationService(ApplicationRepository(db), AuditService(db)); portfolios = PortfolioService(PortfolioRepository(db), AuditService(db)); principal = actor()
    source = await parent(db, 'Source')
    for index in range(15):
        destination = await parent(db, f'Destination {index}')
        if reassign:
            app = await service.create(principal, ApplicationCreate.model_validate(payload(source, f'App {index}')))
            write = service.update(principal,ObjectId(app.id),ApplicationUpdate(portfolioId=str(destination)))
        else:
            write = service.create(principal,ApplicationCreate.model_validate(payload(destination,f'App {index}')))
        results = await asyncio.gather(write, portfolios.delete(principal,destination),return_exceptions=True)
        for result in results:
            if isinstance(result, Exception): assert isinstance(result, DomainError) and result.status in (404,409)
        for row in await db.applications.find({}).to_list(None):
            assert await db.portfolios.find_one({'_id':row['portfolioId']}) is not None


async def test_delete_intent_and_durable_pin_exclude_each_other(db):
    """Prove both deterministic interleavings on actual Mongo atomic predicates."""
    identifier = await parent(db); repo = ApplicationRepository(db); portfolios = PortfolioRepository(db)
    row = await db.portfolios.find_one({'_id':identifier})
    assert await repo.reserve(Scope(None),identifier,'operation')
    assert not await portfolios.begin_delete(Scope(None),identifier,row['updatedAt'])
    await repo.release(identifier,'operation')
    assert await portfolios.begin_delete(Scope(None),identifier,row['updatedAt'])
    assert not await repo.reserve(Scope(None),identifier,'late')
    await portfolios.cancel_delete(identifier)
    assert await repo.reserve(Scope(None),identifier,'reconciled')


async def test_conditional_repository_write_rejects_changed_and_deleted_snapshots(db):
    """Arbitrate concurrent versions with Mongo conditional writes, not Python locks."""
    identifier = await parent(db)
    repo = ApplicationRepository(db)
    service = ApplicationService(repo, AuditService(db))
    created = await service.create(actor(), ApplicationCreate.model_validate(payload(identifier)))
    snapshot = await repo.get(Scope(None), ObjectId(created.id))
    await service.update(actor(), ObjectId(created.id), ApplicationUpdate(qualityScore=90))
    assert await repo.update(Scope(None), snapshot, {'qualityScore': 0}) is None
    assert not await repo.delete(Scope(None), snapshot)
    assert (await repo.get(Scope(None), ObjectId(created.id)))['qualityScore'] == 90
    current = await repo.get(Scope(None), ObjectId(created.id))
    assert await repo.delete(Scope(None), current)
    assert await repo.update(Scope(None), current, {'qualityScore': 0}) is None
