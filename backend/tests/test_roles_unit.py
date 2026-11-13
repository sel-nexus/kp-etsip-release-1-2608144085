"""Verify bounded role services with real Mongo state and audit requery."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from bson import ObjectId
from api.core.audit import AuditService
from api.core.errors import DomainError
from api.core.policy import Principal, ROLE_MAXIMUM
from api.domains.roles.repository import RoleRepository
from api.domains.roles.service import RoleService
from api.domains.roles.schemas import RoleEnsure, RoleUpdate

@pytest.fixture
async def service(db):
    """Compose the production repository and durable audit implementation."""
    return RoleService(RoleRepository(db), AuditService(db))

@pytest.fixture
def principal():
    """Provide an authorized service actor without mocking persistence."""
    return Principal(ObjectId(), 'Administrator', ROLE_MAXIMUM['Administrator'], (), False, 'Test Admin')

@pytest.mark.parametrize('name', list(ROLE_MAXIMUM))
async def test_ensure_update_restore_and_boundaries(service, principal, db, name):
    role = await service.ensure(principal, RoleEnsure(name=name))
    identifier = ObjectId(role.id)
    assert set(role.permissions) == ROLE_MAXIMUM[name]
    stored = await db.roles.find_one({'_id': identifier})
    assert stored['description'] == role.description and stored['createdAt'] == role.createdAt
    reduced = await service.update(principal, identifier, RoleUpdate(permissions=[]))
    assert reduced.permissions == [] and reduced.updatedAt > role.updatedAt
    before = await db.roles.find_one({'_id': identifier})
    existing = await service.ensure(principal, RoleEnsure(name=name))
    assert existing.permissions == [] and await db.roles.find_one({'_id': identifier}) == before
    denied = next((action for action in ['administer', 'delete', 'export'] if action not in ROLE_MAXIMUM[name]), None)
    if denied:
        with pytest.raises(DomainError) as failure:
            await service.update(principal, identifier, RoleUpdate(permissions=[denied]))
        assert failure.value.status == 422
        assert await db.roles.find_one({'_id': identifier}) == before
    with pytest.raises(DomainError) as failure:
        await service.update(principal, identifier, RoleUpdate(permissions=['view'], expectedUpdatedAt=role.updatedAt))
    assert failure.value.status == 409 and await db.roles.find_one({'_id': identifier}) == before
    restored = await service.update(principal, identifier, RoleUpdate(permissions=sorted(ROLE_MAXIMUM[name]), expectedUpdatedAt=reduced.updatedAt))
    assert set((await db.roles.find_one({'_id': identifier}))['permissions']) == ROLE_MAXIMUM[name]
    assert restored.createdAt == role.createdAt
    events = await db.audit_logs.find({'entityId': identifier}).to_list(None)
    assert [row['action'] for row in events] == ['create', 'permissionChange', 'permissionChange']
    assert all(row['userId'] == principal.user_id and row['entityType'] == 'role' for row in events)

async def test_list_empty_supported_only_and_ensure_race(service, principal, db):
    assert (await service.list(principal)).items == []
    results = await asyncio.gather(*(service.ensure(principal, RoleEnsure(name='Engineer')) for _ in range(12)))
    assert len({row.id for row in results}) == 1
    assert await db.roles.count_documents({'name': 'Engineer'}) == 1
    assert await db.audit_logs.count_documents({'action': 'create'}) == 1
    await db.roles.insert_one({'name': 'Custom'})
    assert [row.name for row in (await service.list(principal)).items] == ['Engineer']
    custom = await db.roles.find_one({'name': 'Custom'})
    with pytest.raises(DomainError) as failure:
        await service.update(principal, custom['_id'], RoleUpdate(permissions=[]))
    assert failure.value.status == 404

@pytest.mark.parametrize('operation', ['list', 'ensure', 'update'])
async def test_service_denial_precedes_writes(service, db, operation):
    actor = Principal(ObjectId(), 'Engineer', ROLE_MAXIMUM['Engineer'], (), False, 'Engineer')
    with pytest.raises(DomainError) as failure:
        if operation == 'list': await service.list(actor)
        elif operation == 'ensure': await service.ensure(actor, RoleEnsure(name='Engineer'))
        else: await service.update(actor, ObjectId(), RoleUpdate(permissions=[]))
    assert failure.value.status == 403
    assert await db.roles.count_documents({}) == 0 and await db.audit_logs.count_documents({}) == 0

async def test_missing_and_atomic_version_conflict(service, principal, db):
    with pytest.raises(DomainError) as failure:
        await service.update(principal, ObjectId(), RoleUpdate(permissions=[]))
    assert failure.value.status == 404
    role = await service.ensure(principal, RoleEnsure(name='Engineer'))
    original = service.repository.update
    async def competing(snapshot, changes):
        await db.roles.update_one({'_id': snapshot['_id']}, {'$set': {'updatedAt': datetime.now(timezone.utc), 'permissions': ['view']}})
        return await original(snapshot, changes)
    with patch.object(service.repository, 'update', competing):
        with pytest.raises(DomainError) as failure:
            await service.update(principal, ObjectId(role.id), RoleUpdate(permissions=[]))
    assert failure.value.status == 409
    assert (await db.roles.find_one({'_id': ObjectId(role.id)}))['permissions'] == ['view']
    assert await db.audit_logs.count_documents({'action': 'permissionChange'}) == 0
    async def disappearing(snapshot, changes):
        await db.roles.delete_one({'_id': snapshot['_id']})
        return await original(snapshot, changes)
    with patch.object(service.repository, 'update', disappearing):
        with pytest.raises(DomainError) as failure:
            await service.update(principal, ObjectId(role.id), RoleUpdate(permissions=[]))
    assert failure.value.status == 404
    assert await db.roles.find_one({'_id': ObjectId(role.id)}) is None

@pytest.mark.parametrize('operation', ['ensure', 'update'])
async def test_service_audit_failure_preserves_partial_write(service, principal, db, operation):
    """Fail only the required audit acknowledgement, not domain persistence."""
    from pymongo.errors import AutoReconnect
    role = await service.ensure(principal, RoleEnsure(name='Engineer')) if operation == 'update' else None
    before = await db.audit_logs.count_documents({})
    async def failure(document):
        raise AutoReconnect('test audit outage')
    with patch.object(service.audit.collection, 'insert_one', failure):
        with pytest.raises(DomainError) as caught:
            if operation == 'ensure':
                await service.ensure(principal, RoleEnsure(name='Engineer'))
            else:
                await service.update(principal, ObjectId(role.id), RoleUpdate(permissions=[]))
    assert caught.value.status == 503 and caught.value.code == 'AUDIT_WRITE_FAILED'
    assert caught.value.correlation
    stored = await db.roles.find_one({'name': 'Engineer'})
    assert stored['permissions'] == ([] if operation == 'update' else sorted(ROLE_MAXIMUM['Engineer']))
    assert await db.audit_logs.count_documents({}) == before

async def test_unique_index_losing_insert_returns_existing_without_reset(service, principal, db):
    """Exercise duplicate-key recovery while keeping all database operations real."""
    original = service.repository.collection.update_one
    async def winning_insert_then_duplicate(query, update, **kwargs):
        await original(query, update, **kwargs)
        row = await db.roles.find_one({'name': 'Engineer'})
        await db.roles.update_one({'_id': row['_id']}, {'$set': {'permissions': ['view']}})
        # Mongo raises the actual unique-index exception for the competing insert.
        await db.roles.insert_one({**update['$setOnInsert']})
    with patch.object(service.repository.collection, 'update_one', winning_insert_then_duplicate):
        role = await service.ensure(principal, RoleEnsure(name='Engineer'))
    assert role.permissions == ['view']
    assert await db.roles.count_documents({'name': 'Engineer'}) == 1
    assert await db.audit_logs.count_documents({}) == 0
