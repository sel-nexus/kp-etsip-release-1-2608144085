"""Verify profile service transitions and rejection branches against real Mongo."""
import asyncio
import pytest
from api.core.audit import AuditService
from api.core.errors import DomainError
from api.core.security import create_access_token, verify_password
from api.domains.auth.repository import AuthRepository
from api.domains.auth.service import AuthService
from api.domains.auth.profile_service import ProfileService
from api.domains.auth.profile_schemas import PasswordChangeRequest, PreferencesRequest

async def profile_context(db, app, identity):
    """Build real services and a persisted principal without logging in."""
    user, password = identity
    auth = AuthService(AuthRepository(db), AuditService(db), app.state.settings)
    principal = await auth.resolve(create_access_token(user['_id'], app.state.settings))
    return ProfileService(auth), principal, user, password

@pytest.mark.parametrize('gated', [True, False])
async def test_password_replacement_persists_hash_and_clears_gate(db, app, identity, gated):
    service, principal, user, password = await profile_context(db, app, identity)
    await db.users.update_one({'_id': user['_id']}, {'$set': {'mustChangePassword': gated}})
    replacement = 'é' * 36
    result = await service.change_password(principal, PasswordChangeRequest(currentPassword=password, newPassword=replacement))
    stored = await db.users.find_one({'_id': user['_id']})
    assert not stored['mustChangePassword'] and not result.mustChangePassword
    assert await verify_password(replacement, stored['passwordHash'])
    assert not await verify_password(password, stored['passwordHash'])
    assert stored['updatedAt'] > user['updatedAt']
    assert 'passwordHash' not in result.model_dump()
    event = await db.audit_logs.find_one({'userId': user['_id']})
    assert event['action'] == 'edit' and event['entityId'] == user['_id']
    assert event['details'] == 'Changed password'
    assert password not in str(event) and replacement not in str(event) and stored['passwordHash'] not in str(event)

@pytest.mark.parametrize('corrupt', [False, True])
async def test_bad_current_password_preserves_all_state(db, app, identity, corrupt):
    service, principal, user, password = await profile_context(db, app, identity)
    if corrupt:
        await db.users.update_one({'_id': user['_id']}, {'$set': {'passwordHash': 'broken', 'mustChangePassword': True}})
    before = await db.users.find_one({'_id': user['_id']})
    with pytest.raises(DomainError) as error:
        await service.change_password(principal, PasswordChangeRequest(currentPassword='wrong', newPassword='new'))
    assert error.value.status == 403
    assert await db.users.find_one({'_id': user['_id']}) == before
    assert await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('operation', ['password', 'preference'])
@pytest.mark.parametrize('change', ['inactive', 'missing', 'role_missing'])
async def test_profile_rejects_invalid_live_identity(db, app, identity, operation, change):
    service, principal, user, password = await profile_context(db, app, identity)
    if change == 'inactive':
        await db.users.update_one({'_id': user['_id']}, {'$set': {'status': 'Inactive'}})
    elif change == 'missing':
        await db.users.delete_one({'_id': user['_id']})
    else:
        await db.roles.delete_one({'name': user['role']})
    before = await db.users.find_one({'_id': user['_id']})
    with pytest.raises(DomainError) as error:
        if operation == 'password':
            await service.change_password(principal, PasswordChangeRequest(currentPassword=password, newPassword='new'))
        else:
            await service.save_preferences(principal, PreferencesRequest(defaultLandingPage='profile'))
    assert error.value.status == 401
    assert await db.users.find_one({'_id': user['_id']}) == before
    assert await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('role,destination,allowed', [
    ('Engineer','dashboard',True), ('Read Only','reports',True), ('Executive','portfolios',True),
    ('Auditor','audit',True), ('Administrator','users',True), ('Administrator','roles',True),
    ('Engineer','users',False), ('Executive','roles',False), ('Read Only','audit',False),
    ('Engineer','applications',True), ('Engineer','profile',True),
])
async def test_landing_resource_boundaries_and_persisted_requery(db, app, identity, role, destination, allowed):
    service, principal, user, _ = await profile_context(db, app, identity)
    await db.users.update_one({'_id': user['_id']}, {'$set': {'role': role}})
    before = await db.users.find_one({'_id': user['_id']})
    if allowed:
        result = await service.save_preferences(principal, PreferencesRequest(defaultLandingPage=destination))
        assert result.defaultLandingPage == destination
        stored = await db.users.find_one({'_id': user['_id']})
        assert stored['defaultLandingPage'] == destination and stored['passwordHash'] == before['passwordHash']
        assert await db.audit_logs.count_documents({'action': 'edit', 'details': 'Updated landing preference'}) == 1
    else:
        with pytest.raises(DomainError) as error:
            await service.save_preferences(principal, PreferencesRequest(defaultLandingPage=destination))
        assert error.value.status == 403
        assert await db.users.find_one({'_id': user['_id']}) == before
        assert await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('case', ['gate', 'reduced_view', 'reduced_admin'])
async def test_landing_checks_current_gate_and_permissions(db, app, identity, case):
    service, principal, user, _ = await profile_context(db, app, identity)
    destination = 'dashboard'
    if case == 'gate':
        await db.users.update_one({'_id': user['_id']}, {'$set': {'mustChangePassword': True}})
    elif case == 'reduced_view':
        await db.roles.update_one({'name': 'Engineer'}, {'$set': {'permissions': []}})
    else:
        await db.users.update_one({'_id': user['_id']}, {'$set': {'role': 'Administrator'}})
        await db.roles.update_one({'name': 'Administrator'}, {'$set': {'permissions': ['view']}})
        destination = 'users'
    before = await db.users.find_one({'_id': user['_id']})
    with pytest.raises(DomainError) as error:
        await service.save_preferences(principal, PreferencesRequest(defaultLandingPage=destination))
    assert error.value.status == 403
    assert await db.users.find_one({'_id': user['_id']}) == before

@pytest.mark.parametrize('operation', ['password', 'preference'])
async def test_audit_failure_reports_partial_write_not_success(db, app, identity, operation):
    service, principal, user, password = await profile_context(db, app, identity)
    await db.command({'collMod': 'audit_logs', 'validator': {'impossible': {'$exists': True}}, 'validationLevel': 'strict'})
    with pytest.raises(DomainError) as error:
        if operation == 'password':
            await service.change_password(principal, PasswordChangeRequest(currentPassword=password, newPassword='new'))
        else:
            await service.save_preferences(principal, PreferencesRequest(defaultLandingPage='profile'))
    assert error.value.code == 'AUDIT_WRITE_FAILED' and error.value.status == 503 and error.value.correlation
    stored = await db.users.find_one({'_id': user['_id']})
    if operation == 'password':
        assert await verify_password('new', stored['passwordHash'])
    else:
        assert stored['defaultLandingPage'] == 'profile'
    assert await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('change,status', [('stale',409), ('inactive',401), ('missing',401)])
async def test_conditional_persist_conflict_and_disappearing_identity(db, app, identity, change, status):
    service, _, user, _ = await profile_context(db, app, identity)
    snapshot = await service.repository.get_by_id(user['_id'])
    if change == 'stale':
        await db.users.update_one({'_id': user['_id']}, {'$set': {'defaultLandingPage': 'reports', 'updatedAt': user['updatedAt'].replace(year=2030)}})
    elif change == 'inactive':
        await db.users.update_one({'_id': user['_id']}, {'$set': {'status': 'Inactive'}})
    else:
        await db.users.delete_one({'_id': user['_id']})
    before = await db.users.find_one({'_id': user['_id']})
    with pytest.raises(DomainError) as error:
        await service.persist(snapshot, {'defaultLandingPage': 'profile'}, 'Updated landing preference')
    assert error.value.status == status
    assert await db.users.find_one({'_id': user['_id']}) == before
    assert await db.audit_logs.count_documents({}) == 0

async def test_credential_snapshot_cannot_overwrite_concurrent_hash(db, app, identity):
    """Protect the verified hash even when another writer fails to advance its timestamp."""
    service, _, user, _ = await profile_context(db, app, identity)
    snapshot = await service.repository.get_credentials_by_id(user['_id'])
    await db.users.update_one({'_id': user['_id']}, {'$set': {'passwordHash': 'concurrent-hash'}})
    before = await db.users.find_one({'_id': user['_id']})
    with pytest.raises(DomainError) as error:
        await service.persist(snapshot, {'passwordHash': 'must-not-write', 'mustChangePassword': False}, 'Changed password')
    assert error.value.status == 409
    assert await db.users.find_one({'_id': user['_id']}) == before
    assert await db.audit_logs.count_documents({}) == 0
