"""Verify portfolio service outcomes and durable state with real Mongo."""
from dataclasses import replace
from datetime import timedelta
import pytest
from bson import ObjectId
from api.core.audit import AuditService
from api.core.errors import DomainError
from api.core.policy import Principal, ROLE_MAXIMUM, Scope
from api.domains.portfolios.repository import PortfolioRepository
from api.domains.portfolios.service import PortfolioService
from api.domains.portfolios.schemas import PortfolioCreate, PortfolioUpdate, PortfolioFilters

@pytest.fixture
async def service(db):
    """Compose production collaborators around the disposable pooled DB."""
    return PortfolioService(PortfolioRepository(db), AuditService(db))

@pytest.fixture
async def admin(identity):
    """Use an unrestricted authorized Administrator actor."""
    return Principal(identity[0]['_id'], 'Administrator', ROLE_MAXIMUM['Administrator'], (), False, 'Test Admin')

async def test_service_crud_derives_half_up_and_never_stores_metrics(service, admin, db):
    created = await service.create(admin, PortfolioCreate(name='Payments', ownerName='Owner', description='Services', productArea='Finance', status='Active'))
    identifier = ObjectId(created.id)
    stored = await db.portfolios.find_one({'_id': identifier})
    assert created.applicationCount == 0 and created.qualityScore is None
    assert 'qualityScore' not in stored and 'applicationCount' not in stored
    for score in [80, 81]:
        await db.applications.insert_one({'name': f'App {score}', 'portfolioId': identifier, 'qualityScore': score, 'criticality': 'High', 'tier': 2, 'lifecycleStatus': 'Active', 'riskLevel': 'Low'})
    detail = await service.detail(admin, identifier)
    assert detail.portfolio.applicationCount == 2 and detail.portfolio.qualityScore == 81
    assert len(detail.applications) == 2
    page = await service.list(admin, PortfolioFilters(search='pay', productArea='Finance', status='Active'))
    assert page.total == 1 and page.items[0].id == created.id
    updated = await service.update(admin, identifier, PortfolioUpdate(ownerName='Next', expectedUpdatedAt=stored['updatedAt']))
    assert updated.ownerName == 'Next'
    assert (await db.portfolios.find_one({'_id': identifier}))['ownerName'] == 'Next'
    with pytest.raises(DomainError) as rejected:
        await service.delete(admin, identifier)
    assert rejected.value.status == 409
    assert await db.applications.count_documents({'portfolioId': identifier}) == 2
    await db.applications.delete_many({'portfolioId': identifier})
    assert (await service.delete(admin, identifier)).deleted is True
    assert await db.portfolios.find_one({'_id': identifier}) is None
    assert sorted(await db.audit_logs.distinct('action', {'entityId': identifier})) == ['create', 'delete', 'edit']

@pytest.mark.parametrize('role', ['Executive', 'Portfolio Leader', 'Engineer', 'Auditor', 'Read Only'])
async def test_service_non_admin_mutations_denied_without_writes(service, admin, db, role):
    principal = replace(admin, role=role, permissions=ROLE_MAXIMUM[role])
    with pytest.raises(DomainError) as error:
        await service.create(principal, PortfolioCreate(name='No', ownerName='Owner', description='Text', productArea='Area', status='Active'))
    assert error.value.status == 403
    assert await db.portfolios.count_documents({}) == 0 and await db.audit_logs.count_documents({}) == 0

async def test_service_hidden_missing_stale_and_user_reference_branches(service, admin, db):
    created = await service.create(admin, PortfolioCreate(name='One', ownerName='Owner', description='Text', productArea='Area', status='Active'))
    identifier = ObjectId(created.id)
    row = await db.portfolios.find_one({'_id': identifier})
    for principal, target in [(replace(admin, portfolio_access=(ObjectId(),)), identifier), (admin, ObjectId())]:
        with pytest.raises(DomainError) as error:
            await service.detail(principal, target)
        assert error.value.status == 404
    for operation in ['update', 'delete']:
        with pytest.raises(DomainError) as error:
            if operation == 'update':
                await service.update(admin, identifier, PortfolioUpdate(status='Archived', expectedUpdatedAt=row['updatedAt'] - timedelta(seconds=1)))
            else:
                await service.delete(admin, identifier, row['updatedAt'] - timedelta(seconds=1))
        assert error.value.status == 409
        assert await db.portfolios.find_one({'_id': identifier}) == row
    await db.users.update_one({'_id': admin.user_id}, {'$set': {'portfolioAccess': [identifier]}})
    with pytest.raises(DomainError) as error:
        await service.delete(admin, identifier)
    assert error.value.status == 409 and await db.portfolios.find_one({'_id': identifier}) == row
    assert (await service.list(replace(admin, role='Engineer', portfolio_access=()), PortfolioFilters())).total == 0

async def test_repository_conditional_write_loses_to_new_snapshot(service, admin, db):
    created = await service.create(admin, PortfolioCreate(name='One', ownerName='Owner', description='Text', productArea='Area', status='Active'))
    identifier = ObjectId(created.id)
    snapshot = await db.portfolios.find_one({'_id': identifier})
    await db.portfolios.update_one({'_id': identifier}, {'$set': {'updatedAt': snapshot['updatedAt'] + timedelta(seconds=1), 'ownerName': 'Winner'}})
    assert await service.repository.update(Scope(None), snapshot, {'ownerName': 'Loser'}) is None
    assert not await service.repository.delete(Scope(None), identifier, snapshot['updatedAt'])
    assert (await db.portfolios.find_one({'_id': identifier}))['ownerName'] == 'Winner'

@pytest.mark.parametrize('operation,removed', [('update',False), ('update',True), ('delete',False), ('delete',True)])
async def test_service_concurrent_snapshot_branches_requery_real_state(service, admin, db, operation, removed):
    """Interleave a real competing Mongo write at the repository boundary."""
    created = await service.create(admin, PortfolioCreate(name='Race', ownerName='Owner', description='Text', productArea='Area', status='Active'))
    identifier = ObjectId(created.id)
    class RacingRepository(PortfolioRepository):
        """Perform a real competing write rather than fake database results."""
        async def compete(self) -> None:
            """Remove or advance the observed record before the conditional mutation."""
            if removed:
                await db.portfolios.delete_one({'_id': identifier})
            else:
                snapshot = await db.portfolios.find_one({'_id': identifier})
                await db.portfolios.update_one({'_id': identifier}, {'$set': {'ownerName':'Winner', 'updatedAt':snapshot['updatedAt']+timedelta(seconds=1)}})
        async def update(self, scope, snapshot, changes):
            """Interleave before the production compare-and-set."""
            await self.compete()
            return await super().update(scope, snapshot, changes)
        async def delete(self, scope, identifier, updated_at):
            """Interleave before the production conditional delete."""
            await self.compete()
            return await super().delete(scope, identifier, updated_at)
    racing = PortfolioService(RacingRepository(db), AuditService(db))
    with pytest.raises(DomainError) as error:
        if operation == 'update':
            await racing.update(admin, identifier, PortfolioUpdate(ownerName='Loser'))
        else:
            await racing.delete(admin, identifier)
    assert error.value.status == (404 if removed else 409)
    stored = await db.portfolios.find_one({'_id': identifier})
    assert stored is None if removed else stored['ownerName'] == 'Winner'
    assert await db.audit_logs.count_documents({'entityId':identifier}) == 1

async def test_service_assigned_admin_create_and_permissionless_read_denied(service, admin, db):
    """Fail closed where a new ID cannot belong to an explicit assignment."""
    with pytest.raises(DomainError) as error:
        await service.create(replace(admin, portfolio_access=(ObjectId(),)), PortfolioCreate(name='Hidden', ownerName='Owner', description='Text', productArea='Area', status='Active'))
    assert error.value.status == 403
    with pytest.raises(DomainError) as error:
        await service.list(replace(admin, permissions=frozenset()), PortfolioFilters())
    assert error.value.status == 403 and await db.portfolios.count_documents({}) == 0
