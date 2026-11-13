"""Exercise service methods against real persistence and pure policy boundaries."""
import pytest
from bson import ObjectId
from pymongo.errors import OperationFailure
from api.core.audit import AuditService
from api.core.policy import Principal, Scope, ROLE_MAXIMUM, require_permission, portfolio_scope, validate_permissions, password_gate
from api.core.errors import DomainError, Forbidden, Unauthenticated
from api.core.security import hash_password, verify_password, create_access_token
from api.domains.auth.repository import AuthRepository
from api.domains.auth.service import AuthService
from api.domains.auth.schemas import LoginRequest

def service(db, app):
    return AuthService(AuthRepository(db), AuditService(db), app.state.settings)
async def test_service_happy_resolve_current_logout(db, app, identity):
    user,password = identity
    auth = service(db,app)
    result = await auth.login(LoginRequest(email=user['email'], password=password))
    principal = await auth.resolve(result.token)
    assert principal.portfolio_access == tuple(user['portfolioAccess'])
    assert (await auth.current_user(principal)).name == user['name']
    assert (await auth.logout(principal)).message == 'Signed out'
    assert (await db.users.find_one({'_id':user['_id']}))['lastLogin'] is not None
    assert await db.audit_logs.count_documents({'details':'Sign-in succeeded'}) == 1

@pytest.mark.parametrize('case', ['wrong','unknown','corrupt_hash','long_password'])
async def test_service_rejects_invalid_credentials_with_failure_audit(db, app, identity, case):
    user,password = identity
    if case == 'wrong': password = 'wrong'
    if case == 'unknown': user['email'] = 'unknown@example.com'
    if case == 'corrupt_hash': await db.users.update_one({'_id':user['_id']},{'$set':{'passwordHash':'broken'}})
    if case == 'long_password': password = 'a'*73
    with pytest.raises(Unauthenticated):
        await service(db,app).login(LoginRequest(email=user['email'],password=password))
    assert await db.audit_logs.count_documents({'details':'Sign-in failed'}) == 1
    assert (await db.users.find_one({'_id':user['_id']}))['lastLogin'] is None
    if case == 'unknown':
        event = await db.audit_logs.find_one({'details': 'Sign-in failed'})
        assert event['userId'] is None and event['entityId'] is None
        assert event['userName'] == 'Unknown account'
        assert user['email'] not in str(event)

async def test_login_rejects_missing_stored_name_with_safe_failure_audit(db, app, identity):
    """Reject an incomplete real Mongo identity without losing failure evidence."""
    user, password = identity
    assert (await db.users.update_one({'_id': user['_id']}, {'$unset': {'name': ''}})).modified_count == 1
    before = await db.users.find_one({'_id': user['_id']})
    assert 'name' not in before
    with pytest.raises(Unauthenticated) as failure:
        await service(db, app).login(LoginRequest(email=user['email'], password=password))
    assert failure.value.status == 401 and failure.value.code == 'UNAUTHENTICATED'
    assert failure.value.message == 'Unable to authenticate'
    stored = await db.users.find_one({'_id': user['_id']})
    assert stored == before and stored['lastLogin'] is None
    events = await db.audit_logs.find({}).to_list(None)
    assert len(events) == 1
    assert events[0]['action'] == 'login' and events[0]['details'] == 'Sign-in failed'
    assert events[0]['entityType'] == 'user'
    assert events[0]['userId'] == user['_id'] and events[0]['entityId'] == user['_id']
    assert events[0]['userName'] == 'Incomplete account'
    assert user['email'] not in str(events) and password not in str(events)
    assert user['passwordHash'] not in str(events)

@pytest.mark.parametrize('change', ['deleted', 'inactive'])
async def test_login_rejects_account_changed_before_real_timestamp_write(db, app, identity, change):
    """Interleave a persisted account change before the real conditional update."""
    user, password = identity
    before = await db.users.find_one({'_id': user['_id']})

    class InterleavedRepository(AuthRepository):
        """Keep every repository operation on the real Mongo driver."""
        async def mark_login(self, user_id, now):
            """Change persisted eligibility, then execute the original update."""
            if change == 'deleted':
                await self.users.delete_one({'_id': user_id})
            else:
                await self.users.update_one({'_id': user_id}, {'$set': {'status': 'Inactive'}})
            return await super().mark_login(user_id, now)

    auth = AuthService(InterleavedRepository(db), AuditService(db), app.state.settings)
    with pytest.raises(Unauthenticated) as error:
        await auth.login(LoginRequest(email=user['email'], password=password))
    assert error.value.code == 'UNAUTHENTICATED'
    assert error.value.message == 'Unable to authenticate'
    stored = await db.users.find_one({'_id': user['_id']})
    if change == 'deleted':
        assert stored is None
    else:
        assert stored['status'] == 'Inactive' and stored['lastLogin'] is None
        assert stored['updatedAt'] == before['updatedAt']
    events = await db.audit_logs.find({}).to_list(None)
    assert len(events) == 1
    assert events[0]['details'] == 'Sign-in failed' and events[0]['action'] == 'login'
    assert events[0]['userId'] == user['_id'] and events[0]['entityId'] == user['_id']
    assert password not in str(events)


async def test_real_audit_failure_prevents_token_and_exposes_partial_timestamp(db, app, identity):
    user,password = identity
    await db.command({'collMod':'audit_logs','validator':{'impossible':{'$exists':True}},'validationLevel':'strict'})
    with pytest.raises(DomainError) as error:
        await service(db,app).login(LoginRequest(email=user['email'],password=password))
    assert error.value.code == 'AUDIT_WRITE_FAILED' and error.value.correlation
    assert (await db.users.find_one({'_id':user['_id']}))['lastLogin'] is not None
    assert await db.audit_logs.count_documents({}) == 0
    with pytest.raises(Unauthenticated):
        await service(db,app).login(LoginRequest(email=user['email'],password='wrong'))

@pytest.mark.parametrize('patch', [{'status':'Inactive'},{'role':'Custom'},{'portfolioAccess':['bad-id']}])
async def test_service_current_and_logout_reject_changed_identity(db,app,identity,patch):
    user,_ = identity
    auth = service(db,app)
    principal = await auth.resolve(create_access_token(user['_id'],app.state.settings))
    await db.users.update_one({'_id':user['_id']},{'$set':patch})
    for operation in (auth.current_user,auth.logout):
        with pytest.raises(Unauthenticated): await operation(principal)

@pytest.mark.parametrize('permissions', ['view', ['view', None], ['view', {'action': 'edit'}], None])
async def test_service_rejects_persisted_malformed_role_permissions(db, app, identity, permissions):
    """Reject non-array, non-string elements and missing persisted permissions."""
    user, _ = identity
    auth = service(db, app)
    token = create_access_token(user['_id'], app.state.settings)
    principal = await auth.resolve(token)
    mutation = {'$unset': {'permissions': ''}} if permissions is None else {'$set': {'permissions': permissions}}
    assert (await db.roles.update_one({'name': user['role']}, mutation)).modified_count == 1
    stored = await db.roles.find_one({'name': user['role']})
    if permissions is None:
        assert 'permissions' not in stored
    else:
        assert stored['permissions'] == permissions
    for operation, argument in ((auth.resolve, token), (auth.current_user, principal), (auth.logout, principal)):
        with pytest.raises(Unauthenticated) as failure:
            await operation(argument)
        assert failure.value.status == 401 and failure.value.code == 'UNAUTHENTICATED'
        assert failure.value.message == 'Unable to authenticate'
    assert (await db.users.find_one({'_id': user['_id']}))['lastLogin'] is None
    assert await db.audit_logs.count_documents({}) == 0


@pytest.mark.parametrize('key', ['name', 'portfolioAccess', 'role', 'status'])
async def test_service_rejects_persisted_missing_required_user_keys(db, app, identity, key):
    """Reload genuinely incomplete Mongo records and fail with generic rejection."""
    user, _ = identity
    auth = service(db, app)
    token = create_access_token(user['_id'], app.state.settings)
    principal = await auth.resolve(token)
    assert (await db.users.update_one({'_id': user['_id']}, {'$unset': {key: ''}})).modified_count == 1
    before = await db.users.find_one({'_id': user['_id']})
    assert key not in before
    for operation, argument in ((auth.resolve, token), (auth.current_user, principal), (auth.logout, principal)):
        with pytest.raises(Unauthenticated) as failure:
            await operation(argument)
        assert failure.value.status == 401 and failure.value.code == 'UNAUTHENTICATED'
        assert failure.value.message == 'Unable to authenticate'
    assert await db.users.find_one({'_id': user['_id']}) == before
    assert await db.audit_logs.count_documents({}) == 0


@pytest.mark.parametrize('role', list(ROLE_MAXIMUM))
@pytest.mark.parametrize('action', ['view','create','edit','delete','export','administer'])
def test_all_six_role_action_ceiling(role,action):
    principal = Principal(ObjectId(),role,frozenset(ROLE_MAXIMUM['Administrator']),(),False,'Test')
    if action in ROLE_MAXIMUM[role]: require_permission(principal,action,'application')
    else:
        with pytest.raises(Forbidden): require_permission(principal,action,'application')

@pytest.mark.parametrize('role', list(ROLE_MAXIMUM))
def test_scope_empty_assigned_and_resource_restrictions(role):
    portfolio = ObjectId()
    principal = Principal(ObjectId(),role,ROLE_MAXIMUM[role],(),False,'Test')
    empty = portfolio_scope(principal)
    assert empty.predicate() == ({} if role in ('Administrator','Executive','Auditor') else {'portfolioId':{'$in':[]}})
    assigned = portfolio_scope(Principal(ObjectId(),role,ROLE_MAXIMUM[role],(portfolio,),False,'Test'))
    assert assigned.predicate('_id') == {'_id':{'$in':[portfolio]}}
    assert assigned.includes(portfolio) and not assigned.includes(ObjectId())
    if role != 'Administrator':
        with pytest.raises(Forbidden): require_permission(principal,'edit','portfolio')
        with pytest.raises(Forbidden): require_permission(principal,'view','user')
    if role not in ('Administrator','Auditor'):
        with pytest.raises(Forbidden): require_permission(principal,'view','audit')

@pytest.mark.parametrize('role', list(ROLE_MAXIMUM))
def test_permission_edit_bounds_and_stored_reduction(role):
    assert validate_permissions(role,[]) == frozenset()
    assert validate_permissions(role,list(ROLE_MAXIMUM[role])) == ROLE_MAXIMUM[role]
    with pytest.raises(DomainError): validate_permissions(role,['unknown'])
    principal = Principal(ObjectId(),role,frozenset(),(),False,'Test')
    with pytest.raises(Forbidden): require_permission(principal,'view','application')

def test_gate_exact_methods_and_paths_and_invalid_scope():
    p = Principal(ObjectId(),'Administrator',ROLE_MAXIMUM['Administrator'],(),True,'Test')
    for method,path in [('GET','/api/auth/me'),('POST','/api/auth/logout'),('POST','/api/auth/change-password')]: password_gate(p,path,method)
    for method,path in [('GET','/api/auth/change-password'),('POST','/api/auth/preferences'),('GET','/api/applications')]:
        with pytest.raises(DomainError) as error: password_gate(p,path,method)
        assert error.value.code == 'PASSWORD_CHANGE_REQUIRED'
    with pytest.raises(DomainError): require_permission(p,'view','application')
    with pytest.raises(ValueError): Scope(None).predicate('$where')
    with pytest.raises(DomainError): validate_permissions('Custom',[])

async def test_bcrypt_full_credential_and_negative():
    secret = 'generated-test-only'
    hashed = await hash_password(secret)
    assert hashed.startswith('$2b$')
    assert await verify_password(secret,hashed)
    assert not await verify_password('different',hashed)
    assert not await verify_password(secret,'malformed')
    assert not await verify_password('a'*73,hashed)
