"""Prove user service validation and durable reference safety against real Mongo."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from bson import ObjectId
from pymongo.errors import AutoReconnect, DuplicateKeyError
from api.core.audit import AuditService
from api.core.errors import DomainError
from api.core.policy import Principal, ROLE_MAXIMUM, Scope
from api.domains.users.schemas import UserCreate, UserUpdate, UserFilters
from api.domains.users.repository import UserRepository
from api.domains.users.service import UserService
from api.domains.portfolios.repository import PortfolioRepository
from api.domains.portfolios.service import PortfolioService


def actor(role: str = 'Administrator') -> Principal:
    """Use a current policy principal for direct service tests."""
    return Principal(ObjectId(), role, ROLE_MAXIMUM[role], (), False, 'Test admin')


def payload(email: str = 'account@example.com', access: list[str] | None = None) -> dict:
    """Supply independent account facts and a test-only credential."""
    return dict(name='Test Account', email=email, password='test-secret', role='Engineer', portfolioAccess=access or [], status='Active', managerName=None, vendorIndicator=False)


async def parent(db, name: str = 'Source') -> ObjectId:
    """Persist a real parent for reference interleavings."""
    now = datetime.now(timezone.utc)
    identifier = ObjectId()
    await db.portfolios.insert_one(dict(_id=identifier, name=name, ownerName='Owner', description='Test portfolio', productArea='Test', status='Active', createdAt=now, updatedAt=now))
    return identifier


async def service(db) -> UserService:
    """Install only the current role records used by this disposable test."""
    for role in ROLE_MAXIMUM:
        await db.roles.insert_one({'name': role, 'permissions': sorted(ROLE_MAXIMUM[role])})
    return UserService(UserRepository(db), AuditService(db))


async def test_safe_service_crud_and_role_audit_persist(db):
    """Requery each write and prove soft deletion retains the credential hash."""
    users = await service(db)
    first, second = await parent(db), await parent(db, 'Destination')
    account = await users.create(actor(), UserCreate.model_validate(payload(access=[str(first)])))
    identifier = ObjectId(account.id)
    before = await db.users.find_one({'_id': identifier})
    assert before['portfolioAccess'] == [first] and before['passwordHash'].startswith('$2')
    assert account.mustChangePassword is False and 'passwordHash' not in account.model_dump()
    updated = await users.update(actor(), identifier, UserUpdate(role='Read Only', portfolioAccess=[str(second)], managerName='Manager'))
    assert updated.role == 'Read Only' and updated.managerName == 'Manager'
    assert (await users.detail(actor(), identifier)).portfolioAccess == [str(second)]
    listing = await users.list(actor(), UserFilters(search='ACCOUNT@', role='Read Only', status='Active'))
    assert listing.total == 1 and listing.items[0].id == account.id
    actions = [row['action'] for row in await db.audit_logs.find({'entityId': identifier}).to_list(None)]
    assert actions == ['create', 'roleChange', 'edit']
    assert (await users.delete(actor(), identifier)).deactivated is True
    after = await db.users.find_one({'_id': identifier})
    assert after['status'] == 'Inactive' and after['passwordHash'] == before['passwordHash']
    for parent_id in (first, second):
        assert (await db.portfolios.find_one({'_id': parent_id}))['_applicationReservations'] == []


@pytest.mark.parametrize('reassign', [False, True])
async def test_concurrent_user_assignment_and_portfolio_delete_never_orphan(db, reassign):
    """Race independent Mongo workflows; every successful assignment retains a parent."""
    users = await service(db)
    portfolios = PortfolioService(PortfolioRepository(db), AuditService(db))
    source = await parent(db)
    for index in range(8):
        destination = await parent(db, f'Destination {index}')
        if reassign:
            account = await users.create(actor(), UserCreate.model_validate(payload(f'user{index}@example.com', [str(source)])))
            write = users.update(actor(), ObjectId(account.id), UserUpdate(portfolioAccess=[str(destination)]))
        else:
            write = users.create(actor(), UserCreate.model_validate(payload(f'user{index}@example.com', [str(destination)])))
        results = await asyncio.gather(write, portfolios.delete(actor(), destination), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                assert isinstance(result, DomainError) and result.status in (404, 409, 422)
        for row in await db.users.find({}).to_list(None):
            for assigned in row['portfolioAccess']:
                assert await db.portfolios.find_one({'_id': assigned}) is not None


async def test_both_deterministic_pin_delete_interleavings_and_old_parent_pin(db):
    """Prove deletion intent and reservations exclude one another atomically."""
    users = await service(db)
    first, second = await parent(db), await parent(db, 'Other')
    repo = users.repository
    portfolios = PortfolioRepository(db)
    snapshot = await db.portfolios.find_one({'_id': second})
    assert await repo.reserve(second, 'user:pending')
    assert not await portfolios.begin_delete(Scope(None), second, snapshot['updatedAt'])
    await repo.release(second, 'user:pending')
    assert await portfolios.begin_delete(Scope(None), second, snapshot['updatedAt'])
    assert not await repo.reserve(second, 'user:late')
    await portfolios.cancel_delete(second)
    pinned = await users.pin([first, second], 'user:move')
    for identifier in (first, second):
        row = await db.portfolios.find_one({'_id': identifier})
        assert not await portfolios.begin_delete(Scope(None), identifier, row['updatedAt'])
    await users.release(pinned, 'user:move')


async def test_invalid_reference_and_role_do_not_mutate_parents_or_accounts(db):
    """Validate all references before reserving any otherwise valid parent."""
    users = await service(db)
    identifier = await parent(db)
    before = await db.portfolios.find_one({'_id': identifier})
    with pytest.raises(DomainError) as error:
        await users.create(actor(), UserCreate.model_validate(payload(access=[str(identifier), str(ObjectId())])))
    assert error.value.status == 422
    assert await db.users.count_documents({}) == 0
    assert await db.portfolios.find_one({'_id': identifier}) == before
    await db.roles.delete_one({'name': 'Engineer'})
    with pytest.raises(DomainError) as error:
        await users.create(actor(), UserCreate.model_validate(payload(access=[str(identifier)])))
    assert error.value.status == 422
    assert await db.portfolios.find_one({'_id': identifier}) == before


async def test_stale_and_competing_updates_preserve_winner(db):
    """Reject both optional stale versions and atomic snapshot losers."""
    users = await service(db)
    created = await users.create(actor(), UserCreate.model_validate(payload()))
    identifier = ObjectId(created.id)
    old = await users.snapshot(identifier)
    await users.update(actor(), identifier, UserUpdate(name='Winner'))
    with pytest.raises(DomainError) as error:
        await users.update(actor(), identifier, UserUpdate(name='Loser', expectedUpdatedAt=old['updatedAt']))
    assert error.value.status == 409
    with pytest.raises(DomainError) as error:
        await users.persist(actor(), old, {'name': 'Loser'}, 'edit')
    assert error.value.status == 409
    assert (await users.snapshot(identifier))['name'] == 'Winner'


async def test_ambiguous_write_keeps_durable_pin_for_reconciliation(db):
    """Inject lost acknowledgement after a real write and retain conservative pins."""
    users = await service(db)
    identifier = await parent(db)
    insert = users.repository.insert
    async def ambiguous(document: dict) -> ObjectId:
        """Persist first, then emulate an unknown acknowledgement outcome."""
        await insert(document)
        raise AutoReconnect('test lost acknowledgement')
    with patch.object(users.repository, 'insert', ambiguous):
        with pytest.raises(AutoReconnect):
            await users.create(actor(), UserCreate.model_validate(payload(access=[str(identifier)])))
    assert await db.users.count_documents({}) == 1
    assert (await db.portfolios.find_one({'_id': identifier}))['_applicationReservations']


async def test_confirmed_duplicate_releases_pins_and_partial_pin_failure_cleans_known_pins(db):
    """Release definite nonwrites, never a possibly completed write."""
    users = await service(db)
    first, second = await parent(db), await parent(db, 'Other')
    with patch.object(users.repository, 'insert', side_effect=DuplicateKeyError('test duplicate')):
        with pytest.raises(DuplicateKeyError):
            await users.create(actor(), UserCreate.model_validate(payload(access=[str(first)])))
    assert (await db.portfolios.find_one({'_id': first}))['_applicationReservations'] == []
    ordered = sorted([first, second], key=str)
    await db.portfolios.update_one({'_id': ordered[1]}, {'$set': {'_applicationDeleting': True}})
    with pytest.raises(DomainError) as error:
        await users.pin(ordered, 'user:failed')
    assert error.value.status == 409
    assert (await db.portfolios.find_one({'_id': ordered[0]}))['_applicationReservations'] == []


async def test_ambiguous_update_retains_both_parent_pins(db):
    """Keep old and destination pins when an assignment write loses acknowledgement."""
    users = await service(db)
    first, second = await parent(db), await parent(db, 'Other')
    created = await users.create(actor(), UserCreate.model_validate(payload(access=[str(first)])))
    update = users.repository.update
    async def ambiguous(snapshot: dict, changes: dict) -> dict:
        await update(snapshot, changes)
        raise AutoReconnect('test lost acknowledgement')
    with patch.object(users.repository, 'update', ambiguous):
        with pytest.raises(AutoReconnect):
            await users.update(actor(), ObjectId(created.id), UserUpdate(portfolioAccess=[str(second)]))
    assert (await users.snapshot(ObjectId(created.id)))['portfolioAccess'] == [second]
    for identifier in (first, second):
        assert (await db.portfolios.find_one({'_id': identifier}))['_applicationReservations']


async def test_deleted_snapshot_missing_detail_and_delete_stale_are_nonwrites(db):
    """Reject nonexistent accounts and stale deactivation without changing state."""
    users = await service(db)
    with pytest.raises(DomainError) as error:
        await users.detail(actor(), ObjectId())
    assert error.value.status == 404
    account = await users.create(actor(), UserCreate.model_validate(payload()))
    identifier = ObjectId(account.id)
    snapshot = await users.snapshot(identifier)
    await users.update(actor(), identifier, UserUpdate(name='Winner'))
    with pytest.raises(DomainError) as error:
        await users.delete(actor(), identifier, snapshot['updatedAt'])
    assert error.value.status == 409
    assert (await users.snapshot(identifier))['status'] == 'Active'
    current = await users.snapshot(identifier)
    await db.users.delete_one({'_id': identifier})
    with pytest.raises(DomainError) as error:
        await users.persist(actor(), current, {'name': 'Gone'}, 'edit')
    assert error.value.status == 404
